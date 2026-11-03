import uuid

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.logistics.models import Asset
from apps.organization.models import OrganizationalUnit
from apps.weapons.models import WeaponCustody

from .models import InventoryCount, InventoryLine

MAX_LINES = 2000
R = InventoryLine.Result
COUNTED = (Asset.Status.IN_STOCK, Asset.Status.ISSUED, Asset.Status.MAINTENANCE, Asset.Status.MISSING)  # lost/retired are not expected on the shelf


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise ValidationError({field: ["A valid id is required."]})


def _line_out(ln):
    return {"id": str(ln.pk), "expected_identifier": ln.expected_identifier, "expected_type": ln.expected_type,
            "expected_holder": ln.expected_holder, "expected_status": ln.expected_status, "result": ln.result,
            "observed_identifier": ln.observed_identifier, "note": ln.note,
            "checked_at": ln.checked_at.isoformat() if ln.checked_at else None, "checked_by": ln.checked_by_username}


def _progress(count):
    rows = dict(count.lines.values_list("result").annotate(n=Count("pk")))
    out = {k: rows.get(k, 0) for k in (R.PENDING, R.VERIFIED, R.MISSING, R.MISMATCH, R.UNLISTED)}
    out["total"] = sum(rows.values())
    return out


def _count_out(c, progress=None):
    return {"id": str(c.pk), "kind": c.kind, "status": c.status, "note": c.note,
            "org_unit": {"id": str(c.org_unit_id), "code": c.org_unit.code, "name_en": c.org_unit.name_en, "name_so": c.org_unit.name_so},
            "opened_by": c.opened_by_username, "opened_at": c.opened_at.isoformat(),
            "submitted_by": c.submitted_by_username, "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None,
            "signed_by": c.signed_by_username, "signed_at": c.signed_at.isoformat() if c.signed_at else None, "sign_note": c.sign_note,
            "progress": progress if progress is not None else _progress(c)}


class InventoryViewSet(viewsets.GenericViewSet):
    queryset = InventoryCount.objects.none()
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("weapons.view", "any"), "retrieve": ("weapons.view", "any"),
        "create": ("weapons.manage", "any"), "check": ("weapons.manage", "any"), "found": ("weapons.manage", "any"),
        "annotate": ("weapons.manage", "any"), "submit": ("weapons.manage", "any"), "sign": ("weapons.manage", "any"),
        "cancel": ("weapons.manage", "any"),
    }

    # ---- helpers
    def _visible(self, code="weapons.view"):
        q = scope.unit_scope_q(self.request.user, code, "org_unit__")
        return InventoryCount.objects.none() if q is None else InventoryCount.objects.filter(q).select_related("org_unit")

    def _get(self, pk, code="weapons.view"):
        obj = self._visible(code).filter(pk=_uuid(pk, "id")).first()
        if obj is None:
            raise NotFound()
        return obj

    def _open_only(self, c, *statuses):
        statuses = statuses or (InventoryCount.Status.OPEN,)
        if c.status not in statuses:
            raise ValidationError({"status": [f"This count is {c.status}; that step is no longer possible."]})

    # ---- reading
    def list(self, request):
        qs = self._visible()
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        if request.query_params.get("org_unit"):
            unit = OrganizationalUnit.objects.filter(pk=_uuid(request.query_params["org_unit"], "org_unit")).first()
            if unit:
                qs = qs.filter(org_unit__path__startswith=unit.path)
        return Response([_count_out(c) for c in qs[:100]])

    def retrieve(self, request, pk=None):
        c = self._get(pk)
        record_read(request, "inventory.view", entity_type="inventory_count", entity_id=str(c.pk), org_unit=c.org_unit)
        order = {R.PENDING: 0, R.MISSING: 1, R.MISMATCH: 2, R.UNLISTED: 3, R.VERIFIED: 4}
        lines = sorted(c.lines.all(), key=lambda ln: (order.get(ln.result, 9), ln.expected_identifier))
        return Response({**_count_out(c), "lines": [_line_out(ln) for ln in lines]})

    # ---- steps
    def create(self, request):
        unit = OrganizationalUnit.objects.filter(pk=_uuid(request.data.get("org_unit"), "org_unit"), active=True).first()
        if unit is None:
            raise ValidationError({"org_unit": ["Choose a unit."]})
        if not scope.can(request.user, "weapons.manage", unit):
            raise PermissionDenied()
        kind = request.data.get("kind", InventoryCount.Kind.CYCLIC)
        if kind not in InventoryCount.Kind.values:
            raise ValidationError({"kind": ["Unknown kind of count."]})
        if InventoryCount.objects.filter(org_unit=unit, status__in=(InventoryCount.Status.OPEN, InventoryCount.Status.SUBMITTED)).exists():
            raise ValidationError({"org_unit": ["A count for this unit is already in progress."]})
        q = scope.unit_scope_q(request.user, "weapons.manage", "org_unit__")
        assets = list(Asset.objects.filter(q, weapon__isnull=False, org_unit__path__startswith=unit.path, status__in=COUNTED)
                      .select_related("weapon")[:MAX_LINES + 1])
        if len(assets) > MAX_LINES:
            raise ValidationError({"org_unit": [f"Too many weapons for one count (over {MAX_LINES}). Count a smaller unit."]})
        custody = {c.asset_id: c for c in WeaponCustody.objects.filter(asset_id__in=[a.pk for a in assets], returned_at__isnull=True)
                   .select_related("personnel")}
        with transaction.atomic():
            count = InventoryCount.objects.create(org_unit=unit, kind=kind, note=str(request.data.get("note", ""))[:300],
                                                  opened_by_id=request.user.pk, opened_by_username=request.user.username)
            lines = []
            for a in assets:
                c = custody.get(a.pk)
                holder = f"{c.personnel.full_name} ({c.personnel.service_number or 'no service number'})" if c else "In the unit's store"
                lines.append(InventoryLine(count=count, asset=a, expected_identifier=a.identifier, expected_status=a.status,
                                           expected_type=f"{a.weapon.weapon_type} {a.weapon.make_model}".strip()[:120], expected_holder=holder[:200]))
            InventoryLine.objects.bulk_create(lines)
            record("inventory.open", request=request, entity_type="inventory_count", entity_id=count.pk,
                   metadata={"unit": unit.code, "kind": kind, "lines": len(lines)})
        return Response(_count_out(count), status=201)

    def _line(self, c, request):
        line = c.lines.filter(pk=_uuid(request.data.get("line"), "line")).first()
        if line is None:
            raise NotFound()
        return line

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        """Record what was found for one listed weapon: verified, missing, or a different serial number."""
        c = self._get(pk, "weapons.manage")
        self._open_only(c)
        line = self._line(c, request)
        result = request.data.get("result")
        if result not in (R.VERIFIED, R.MISSING, R.MISMATCH) or line.result == R.UNLISTED:
            raise ValidationError({"result": ["Choose verified, missing or different serial number."]})
        observed = str(request.data.get("observed_identifier", "")).strip()[:64]
        if result == R.MISMATCH and (not observed or observed == line.expected_identifier):
            raise ValidationError({"observed_identifier": ["Enter the serial number actually read off the item."]})
        line.result, line.observed_identifier = result, (observed if result == R.MISMATCH else "")
        if "note" in request.data:
            line.note = str(request.data.get("note", ""))[:300]
        line.checked_at, line.checked_by_username = timezone.now(), request.user.username
        line.save()
        return Response(_line_out(line))

    @action(detail=True, methods=["post"])
    def found(self, request, pk=None):
        """An item is on hand that the register does not list for this unit."""
        c = self._get(pk, "weapons.manage")
        self._open_only(c)
        serial = str(request.data.get("identifier", "")).strip()[:64]
        if not serial:
            raise ValidationError({"identifier": ["Enter the serial number read off the item."]})
        if c.lines.filter(Q(expected_identifier=serial) | Q(observed_identifier=serial)).exists():
            raise ValidationError({"identifier": ["That serial number is already on this count."]})
        asset = Asset.objects.filter(identifier=serial, weapon__isnull=False).select_related("org_unit", "weapon").first()
        where = f"The register shows it with {asset.org_unit.code} ({asset.status})" if asset else "The register has no weapon with this serial number"
        line = InventoryLine.objects.create(count=c, asset=asset, expected_identifier="", observed_identifier=serial, expected_holder=where[:200],
                                            expected_type=(f"{asset.weapon.weapon_type} {asset.weapon.make_model}".strip()[:120] if asset else ""),
                                            result=R.UNLISTED, note=str(request.data.get("note", ""))[:300],
                                            checked_at=timezone.now(), checked_by_username=request.user.username)
        return Response(_line_out(line), status=201)

    @action(detail=True, methods=["post"])
    def annotate(self, request, pk=None):
        """Add or change the explanation on a line (needed for every shortage or mismatch before sign-off)."""
        c = self._get(pk, "weapons.manage")
        self._open_only(c, InventoryCount.Status.OPEN, InventoryCount.Status.SUBMITTED)
        line = self._line(c, request)
        line.note = str(request.data.get("note", ""))[:300]
        line.save(update_fields=["note"])
        return Response(_line_out(line))

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        c = self._get(pk, "weapons.manage")
        self._open_only(c)
        pending = c.lines.filter(result=R.PENDING).count()
        if pending:
            raise ValidationError({"lines": [f"{pending} weapons have not been checked yet."]})
        c.status, c.submitted_at = InventoryCount.Status.SUBMITTED, timezone.now()
        c.submitted_by_id, c.submitted_by_username = request.user.pk, request.user.username
        c.save(update_fields=["status", "submitted_at", "submitted_by_id", "submitted_by_username"])
        record("inventory.submit", request=request, entity_type="inventory_count", entity_id=c.pk, metadata={"unit": c.org_unit.code, **_progress(c)})
        return Response(_count_out(c))

    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        c = self._get(pk, "weapons.manage")
        self._open_only(c, InventoryCount.Status.SUBMITTED)
        if not scope.can(request.user, "weapons.manage", c.org_unit):
            raise PermissionDenied()
        if c.submitted_by_id == request.user.pk:
            raise PermissionDenied("A different person must sign off the count.")
        unexplained = [ln.expected_identifier or ln.observed_identifier for ln in c.lines.exclude(result=R.VERIFIED) if len(ln.note.strip()) < 3]
        if unexplained:
            raise ValidationError({"lines": ["Every shortage or mismatch needs an explanation before sign-off: " + ", ".join(unexplained[:10])]})
        c.status, c.signed_at = InventoryCount.Status.SIGNED, timezone.now()
        c.signed_by_id, c.signed_by_username = request.user.pk, request.user.username
        c.sign_note = str(request.data.get("note", ""))[:300]
        c.save(update_fields=["status", "signed_at", "signed_by_id", "signed_by_username", "sign_note"])
        record("inventory.sign", request=request, entity_type="inventory_count", entity_id=c.pk, metadata={"unit": c.org_unit.code, **_progress(c)})
        return Response(_count_out(c))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        c = self._get(pk, "weapons.manage")
        self._open_only(c, InventoryCount.Status.OPEN, InventoryCount.Status.SUBMITTED)
        c.status, c.cancelled_at = InventoryCount.Status.CANCELLED, timezone.now()
        c.save(update_fields=["status", "cancelled_at"])
        record("inventory.cancel", request=request, entity_type="inventory_count", entity_id=c.pk, metadata={"unit": c.org_unit.code})
        return Response(_count_out(c))
