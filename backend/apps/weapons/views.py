import uuid

from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.logistics.models import Asset, AssetEvent, InventoryCategory
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from . import services as svc
from .models import WeaponCustody, WeaponDetail


def _uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _scoped(user, code="weapons.view"):
    q1 = scope.unit_scope_q(user, code, "org_unit__")
    q2 = scope.unit_scope_q(user, code, "issued_to_unit__")
    if q1 is None and q2 is None:
        return Asset.objects.none()
    q = (q1 if q1 is not None else Q(pk__in=[])) | (q2 if q2 is not None else Q(pk__in=[]))
    return Asset.objects.filter(q, weapon__isnull=False)


def _unit_brief(u):
    return None if u is None else {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}


def _custody_out(c):
    p = c.personnel
    return {"id": str(c.pk), "personnel": {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                                           "status": p.status, "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}},
            "issued_at": c.issued_at, "issued_by": c.issued_by_username, "authority_ref": c.authority_ref,
            "issue_condition": c.issue_condition, "issue_note": c.issue_note, "returned_at": c.returned_at,
            "returned_by": c.returned_by_username, "outcome": c.outcome, "return_condition": c.return_condition,
            "return_note": c.return_note}


def _out(a, custody=None, detail=False):
    w = a.weapon
    d = {"id": str(a.pk), "serial": a.identifier, "category": {"id": str(a.category_id), "code": a.category.code,
                                                              "name_en": a.category.name_en, "name_so": a.category.name_so},
         "org_unit": _unit_brief(a.org_unit), "issued_to_unit": _unit_brief(a.issued_to_unit), "status": a.status,
         "weapon_type": w.weapon_type, "make_model": w.make_model, "caliber": w.caliber, "condition": w.condition,
         "description": a.description, "version": a.version,
         "custody": _custody_out(custody) if custody is not None else None}
    if detail:
        d["custody_history"] = [_custody_out(c) for c in WeaponCustody.objects.filter(asset=a).select_related("personnel__rank")]
        d["events"] = [{"kind": e.kind, "from_status": e.from_status, "to_status": e.to_status, "note": e.note,
                        "actor": e.actor_username, "at": e.created_at} for e in AssetEvent.objects.filter(asset=a).order_by("-created_at")[:200]]
    return d


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


class WeaponViewSet(viewsets.GenericViewSet):
    """Auditable weapon register, for explicitly authorized personnel only (weapons.view / weapons.manage inside the unit's scope,
    plus the restricted-category rule of the asset ledger). Weapons are tracked by unique serial number; counts are derived."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    permission_map = {
        "list": ("weapons.view", "any"), "retrieve": ("weapons.view", "unit"), "summary": ("weapons.view", "any"),
        "categories": ("weapons.manage", "any"), "people": ("weapons.manage", "any"), "create": ("weapons.manage", "any"),
        "issue": ("weapons.manage", "unit"), "give_back": ("weapons.manage", "unit"), "condition": ("weapons.manage", "unit"),
    }

    def scope_unit(self, obj):
        return svc.effective_unit(obj)

    def get_queryset(self):
        return _scoped(self.request.user).select_related("category", "org_unit", "issued_to_unit", "weapon")

    def _custody_map(self, assets):
        ids = [a.pk for a in assets]
        return {c.asset_id: c for c in WeaponCustody.objects.filter(asset_id__in=ids, returned_at__isnull=True)
                .select_related("personnel__rank")}

    def list(self, request):
        qs = self.get_queryset()
        p = request.query_params
        if p.get("q"):
            q = p["q"].strip()[:60]
            qs = qs.filter(Q(identifier__icontains=q) | Q(weapon__weapon_type__icontains=q) | Q(weapon__make_model__icontains=q))
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("condition"):
            qs = qs.filter(weapon__condition=p["condition"])
        unit = uuid_param(request, "org_unit")
        if unit:
            base = OrganizationalUnit.objects.filter(pk=unit).first()
            qs = qs.filter(Q(org_unit__path__startswith=base.path) | Q(issued_to_unit__path__startswith=base.path)) if base else qs.none()
        if p.get("in_custody") == "1":
            qs = qs.filter(custody__isnull=False, custody__returned_at__isnull=True)  # has an OPEN custody row (never-issued weapons have none)
        holder = uuid_param(request, "personnel")
        if holder:
            qs = qs.filter(custody__returned_at__isnull=True, custody__personnel_id=holder)
        page = self.paginate_queryset(qs.distinct().order_by("identifier"))
        cm = self._custody_map(page)
        record_read(request, "weapon.read_list", entity_type="weapon_register", org_unit=unit if unit else None, count=len(page))
        return self.get_paginated_response([_out(a, cm.get(a.pk)) for a in page])

    def retrieve(self, request, pk=None):
        a = self.get_object()
        record_read(request, "weapon.read_detail", entity_type="weapon", entity_id=a.pk, org_unit=svc.effective_unit(a))
        return Response(_out(a, svc.open_custody(a), detail=True))

    @action(detail=False, methods=["get"])
    def categories(self, request):
        rows = InventoryCategory.objects.filter(code__startswith=svc.PREFIX, kind="asset", approval_status="approved", active=True)
        return Response({"results": [{"id": str(c.pk), "code": c.code, "name_en": c.name_en, "name_so": c.name_so} for c in rows]})

    @action(detail=False, methods=["get"])
    def people(self, request):
        """Minimal lookup of serving personnel (name, service number, rank, unit) to issue a weapon to. It does not open any
        personnel record, so a weapons custodian needs no personnel permission."""
        q = scope.unit_scope_q(request.user, "weapons.manage", "org_unit__")
        unit = OrganizationalUnit.objects.filter(pk=_uid(request.query_params.get("org_unit"))).first() if _uid(request.query_params.get("org_unit")) else None
        if q is None or unit is None:
            return Response({"results": []})
        qs = Personnel.objects.filter(q, org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING).select_related("rank", "org_unit")
        term = (request.query_params.get("q") or "").strip()[:60]
        if term:
            qs = qs.filter(Q(full_name__icontains=term) | Q(service_number__icontains=term))
        return Response({"results": [{"id": str(x.pk), "full_name": x.full_name, "service_number": x.service_number,
                                      "rank": {"code": x.rank.code, "name_en": x.rank.name_en, "name_so": x.rank.name_so},
                                      "unit": _unit_brief(x.org_unit)} for x in qs.order_by("full_name")[:20]]})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts derived from the register for a unit and below: nothing is stored or typed in."""
        qs = self.get_queryset()
        unit = OrganizationalUnit.objects.filter(pk=_uid(request.query_params.get("org_unit"))).first() if _uid(request.query_params.get("org_unit")) else None
        if unit is not None:
            qs = qs.filter(Q(org_unit__path__startswith=unit.path) | Q(issued_to_unit__path__startswith=unit.path))
        ids = list(qs.values_list("pk", flat=True))
        record_read(request, "weapon.read_summary", entity_type="weapon_register", org_unit=unit, count=len(ids))
        open_c = WeaponCustody.objects.filter(asset_id__in=ids, returned_at__isnull=True)
        return Response({
            "total": len(ids),
            "by_status": dict(qs.values_list("status").annotate(n=Count("pk"))),
            "by_type": dict(qs.values_list("weapon__weapon_type").annotate(n=Count("pk"))),
            "by_condition": dict(qs.values_list("weapon__condition").annotate(n=Count("pk"))),
            "in_custody": open_c.count(),
            "held_by_non_serving": open_c.filter(personnel__status__in=NOT_SERVING).count(),
        })

    def create(self, request):
        d = json_body(request)
        cat = InventoryCategory.objects.filter(pk=_uid(d.get("category"))).first() if _uid(d.get("category")) else None
        unit = OrganizationalUnit.objects.filter(pk=_uid(d.get("org_unit"))).first() if _uid(d.get("org_unit")) else None
        if cat is None:
            raise field_error("category", "not_a_weapon_category")
        if unit is None:
            raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
        asset = svc.register(request, cat, unit, str(d.get("serial") or ""), d)
        asset = Asset.objects.select_related("category", "org_unit", "issued_to_unit", "weapon").get(pk=asset.pk)
        return Response(_out(asset), status=201)

    def _person(self, request):
        pid = _uid(json_body(request).get("personnel"))
        person = Personnel.objects.select_related("org_unit", "rank").filter(pk=pid).first() if pid else None
        if person is None:
            raise field_error("personnel", "person_unknown")
        return person

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        a = self.get_object()
        d = json_body(request)
        person = self._person(request)
        if not scope.can(request.user, "weapons.manage", unit=person.org_unit):
            raise field_error("personnel", "person_unknown")  # outside the officer's reach reads like an unknown person
        updated = svc.issue(request, a, person, d.get("condition") or "", d.get("authority_ref") or "", d.get("note") or "", require_version(d))
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(_out(updated, svc.open_custody(updated), detail=True))

    @action(detail=True, methods=["post"], url_path="return")
    def give_back(self, request, pk=None):
        a = self.get_object()
        d = json_body(request)
        updated = svc.give_back(request, a, d.get("condition") or "", d.get("note") or "", require_version(d))
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(_out(updated, svc.open_custody(updated), detail=True))

    @action(detail=True, methods=["post"])
    def condition(self, request, pk=None):
        a = self.get_object()
        d = json_body(request)
        svc.set_condition(request, a, d.get("condition") or "", d.get("note") or "")
        a = self.get_queryset().get(pk=a.pk)
        return Response(_out(a, svc.open_custody(a), detail=True))
