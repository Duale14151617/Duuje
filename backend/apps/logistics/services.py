"""Logistics rules. Every mutation re-checks scope and the restricted-equipment permission on the server."""
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts import scope
from apps.audit.services import record
from apps.core.concurrency import versioned_update
from apps.core.errors import field_error
from apps.core.exceptions import VersionConflict
from apps.core.middleware import get_correlation_id
from apps.core.orgpaths import region_id
from apps.organization.models import OrganizationalUnit
from apps.workflows.services import InvalidTransition

from .models import (Asset, AssetEvent, Reconciliation, ReconciliationLine, StockLine,
                     StockTransaction)

IDENT_RE = re.compile(r"^[A-Z0-9][A-Z0-9/_.-]{1,63}$")
ASSET_RULES = {  # action -> (allowed from-statuses, resulting status)
    "issue": ({"in_stock"}, "issued"),
    "return": ({"issued"}, "in_stock"),
    "maintenance": ({"in_stock"}, "maintenance"),
    "restore": ({"maintenance", "missing", "lost"}, "in_stock"),
    "missing": ({"in_stock", "issued", "maintenance"}, "missing"),
    "lost": ({"in_stock", "issued", "maintenance", "missing"}, "lost"),
    "retire": ({"in_stock", "maintenance", "lost", "missing"}, "retired"),
    "transfer": ({"in_stock"}, "in_stock"),
}
NOTE_REQUIRED = {"missing", "lost", "retire"}


class BalanceChanged(VersionConflict):
    default_detail = "The stock balance changed. Reload and try again."
    default_code = "balance_changed"


def visible_q(user, unit_prefix, cat_prefix):
    """Rows the user may see: normal categories under logistics.view, restricted ones only under logistics.restricted."""
    q = Q(pk__in=[])
    normal = scope.unit_scope_q(user, "logistics.view", unit_prefix)
    if normal is not None:
        q = normal & Q(**{f"{cat_prefix}restricted": False})
    restricted = scope.unit_scope_q(user, "logistics.restricted", unit_prefix)
    if restricted is not None:
        q = q | (restricted & Q(**{f"{cat_prefix}restricted": True}))
    return q


def authorize(request, unit, category=None, perm="logistics.manage"):
    user = request.user
    ok = scope.can(user, perm, unit=unit)
    if ok and category is not None and category.restricted:
        ok = scope.can(user, "logistics.restricted", unit=unit)
    if not ok:
        record("access.denied", request=request, outcome="denied", entity_type="logistics",
               metadata={"permission": perm, "unit": str(unit.pk), "restricted": bool(category and category.restricted)})
        raise PermissionDenied("You do not have permission to do that here.", code="permission_denied")


def placeable(unit, field="org_unit"):
    if unit.level not in ("branch_command", "unit") or not unit.active:
        raise field_error(field, "unit_level_invalid")


def usable(category, kind):
    if category.kind != kind:
        raise field_error("category", "category_kind_mismatch")
    if category.approval_status != "approved" or not category.active:
        raise field_error("category", "category_not_approved")


# ------------------------------------------------------------------ stock
def create_stock_line(request, category, unit, uom, reorder_level):
    usable(category, "stock")
    placeable(unit)
    authorize(request, unit, category)
    if StockLine.objects.filter(category=category, org_unit=unit).exists():
        raise field_error("category", "stock_line_exists")
    with transaction.atomic():
        line = StockLine.objects.create(category=category, org_unit=unit, uom=uom or "units", reorder_level=reorder_level)
        record("stock.line_create", request=request, entity_type="stock_line", entity_id=line.pk,
               metadata={"category": category.code, "unit": str(unit.pk)})
    return line


def _apply(user, line_id, kind, delta, reason, counterpart=None, group=None, expected_balance=None, external_ref="", authority_ref="",
           unit_cost=None, currency=""):
    """Caller must already be inside transaction.atomic(). The row lock serialises concurrent writers."""
    line = StockLine.objects.select_for_update().get(pk=line_id)
    if expected_balance is not None and expected_balance != line.quantity:
        raise BalanceChanged()
    new = line.quantity + delta
    if new < 0:
        raise field_error("quantity", "insufficient_stock")
    StockLine.objects.filter(pk=line.pk).update(quantity=new, version=F("version") + 1, updated_at=timezone.now())
    return StockTransaction.objects.create(
        stock_line=line, kind=kind, delta=delta, balance_after=new, reason=(reason or "")[:300],
        counterpart_unit=counterpart, group=group, actor=user, actor_username=user.username,
        external_ref=(external_ref or "")[:60], authority_ref=(authority_ref or "")[:150], correlation_id=get_correlation_id(),
        unit_cost=unit_cost, currency=currency or "")


def post_stock(request, line, kind, delta, reason, expected_balance=None, external_ref="", unit_cost=None, currency=""):
    if line.category.code.startswith("ammunition"):
        raise field_error("category", "use_ammunition_ledger")  # ammunition has its own ledger with vouchers and authorizations
    authorize(request, line.org_unit, line.category)
    usable(line.category, "stock")
    with transaction.atomic():
        if unit_cost is not None and kind != "receive":
            raise field_error("unit_cost", "cost_only_on_receipt")
        txn = _apply(request.user, line.pk, kind, delta, reason, expected_balance=expected_balance, external_ref=external_ref,
                     unit_cost=unit_cost, currency=currency)
        record(f"stock.{kind}", request=request, entity_type="stock_line", entity_id=line.pk,
               metadata={"delta": delta, "balance": txn.balance_after, "external_ref": external_ref or None,
                         "unit_cost": str(unit_cost) if unit_cost is not None else None})
    return txn


def transfer_stock(request, line, to_unit, quantity, reason):
    if to_unit.pk == line.org_unit_id:
        raise field_error("to_unit", "no_change")
    placeable(to_unit, "to_unit")
    authorize(request, line.org_unit, line.category)
    authorize(request, to_unit, line.category)  # may only push stock into units you also manage
    usable(line.category, "stock")
    with transaction.atomic():
        dest, _ = StockLine.objects.get_or_create(category=line.category, org_unit=to_unit, defaults={"uom": line.uom})
        for pk in sorted([line.pk, dest.pk], key=str):  # fixed lock order avoids deadlocks
            StockLine.objects.select_for_update().get(pk=pk)
        group = uuid.uuid4()
        out = _apply(request.user, line.pk, "transfer_out", -quantity, reason, counterpart=to_unit, group=group)
        _apply(request.user, dest.pk, "transfer_in", quantity, reason, counterpart=line.org_unit, group=group)
        record("stock.transfer", request=request, entity_type="stock_line", entity_id=line.pk,
               metadata={"to_unit": str(to_unit.pk), "quantity": quantity, "group": str(group)})
    return out


# ------------------------------------------------------------------ assets
def _event(user, asset, kind, from_status="", to_status="", from_unit=None, to_unit=None, note=""):
    return AssetEvent.objects.create(asset=asset, kind=kind, from_status=from_status, to_status=to_status,
                                     from_unit=from_unit, to_unit=to_unit, note=note[:300], actor=user,
                                     actor_username=user.username)


def register_asset(request, category, unit, identifier, description, weapon_register=False, details=None):
    if category.code.startswith("weapon") and not weapon_register:
        raise field_error("category", "use_weapon_register")  # weapons need their type and custody record: see apps.weapons
    usable(category, "asset")
    placeable(unit)
    authorize(request, unit, category)
    identifier = identifier.strip().upper()
    if not IDENT_RE.match(identifier):
        raise field_error("identifier", "identifier_invalid")
    if Asset.objects.filter(category=category, identifier=identifier).exists():
        raise field_error("identifier", "asset_duplicate")
    extra = clean_details(details or {})
    with transaction.atomic():
        asset = Asset.objects.create(category=category, org_unit=unit, identifier=identifier, description=description, **extra)
        _event(request.user, asset, "register", to_status="in_stock", to_unit=unit,
               note=f"Acquired {extra['acquired_on']}, ref {extra['procurement_ref']}"[:300] if extra.get("acquired_on") and extra.get("procurement_ref") else "")
        record("asset.register", request=request, entity_type="asset", entity_id=asset.pk,
               metadata={"category": category.code, "unit": str(unit.pk)})
    return asset


def change_asset(request, asset, action, expected_version, note="", to_unit=None):
    user = request.user
    allowed_from, target = ASSET_RULES[action]
    authorize(request, asset.org_unit, asset.category)
    from apps.weapons import services as weapons  # a weapon in a soldier's custody is not moved by ordinary asset actions
    weapons.guard_asset_change(asset, action)
    if asset.version != expected_version:
        raise VersionConflict()
    if asset.status not in allowed_from:
        raise InvalidTransition()
    if action in NOTE_REQUIRED and not note.strip():
        raise field_error("note", "note_required")
    changes = {"status": target}
    if action in ("issue", "transfer"):
        if to_unit is None:
            raise field_error("to_unit", "required")
        placeable(to_unit, "to_unit")
        if to_unit.pk == asset.org_unit_id:
            raise field_error("to_unit", "no_change")
        authorize(request, to_unit, asset.category)
        changes.update(issued_to_unit=to_unit) if action == "issue" else changes.update(org_unit=to_unit, custodian=None)
    elif action == "return" or target != "issued":
        changes["issued_to_unit"] = None
    with transaction.atomic():
        locked = Asset.objects.select_for_update().get(pk=asset.pk)
        if locked.version != expected_version:
            raise VersionConflict()
        if locked.status not in allowed_from:
            raise InvalidTransition()
        old_status, old_unit = locked.status, locked.org_unit
        updated = versioned_update(locked, changes, expected_version)
        _event(user, updated, action, old_status, updated.status, old_unit if action == "transfer" else None,
               to_unit, note)
        weapons.close_custody_on_loss(updated, action, user)
        record(f"asset.{action}", request=request, entity_type="asset", entity_id=updated.pk,
               metadata={"from": old_status, "to": updated.status, "to_unit": str(to_unit.pk) if to_unit else None})
    return updated


# ------------------------------------------------------------------ asset lifecycle details
CONDITIONS = {c.value for c in Asset.Condition}
DETAIL_FIELDS = ("manufacturer", "model", "condition", "acquisition_cost", "currency", "acquired_on", "procurement_ref",
                 "next_inspection_due")


def _date(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(field, "invalid_date", "Use a date like 2026-03-01.")


def clean_details(d):
    """Validate the optional lifecycle fields of an asset and return only the ones that were supplied."""
    out = {}
    for f, size in (("manufacturer", 80), ("model", 80), ("procurement_ref", 60)):
        if f in d:
            out[f] = str(d[f] or "").strip()[:size]
    if "condition" in d:
        if d["condition"] not in CONDITIONS:
            raise field_error("condition", "invalid_condition")
        out["condition"] = d["condition"]
    for f in ("acquired_on", "next_inspection_due"):
        if f in d:
            out[f] = _date(d[f], f)
    if "acquisition_cost" in d:
        raw = d["acquisition_cost"]
        if raw in (None, ""):
            out["acquisition_cost"] = None
        else:
            try:
                cost = Decimal(str(raw))
            except InvalidOperation:
                raise field_error("acquisition_cost", "invalid_amount")
            if not cost.is_finite() or cost < 0 or cost >= Decimal(10) ** 12:
                raise field_error("acquisition_cost", "invalid_amount")
            out["acquisition_cost"] = cost.quantize(Decimal("0.01"))
    cur = str(d.get("currency") or "").strip().upper()
    if out.get("acquisition_cost") is not None and not cur:
        raise field_error("currency", "required")
    if cur and not re.fullmatch(r"[A-Z]{3}", cur):
        raise field_error("currency", "invalid_currency")
    if "currency" in d or out.get("acquisition_cost") is not None:
        out["currency"] = cur
    return out


def update_details(request, asset, details, expected_version):
    """Edit procurement facts in place. The asset is never re-created, so no duplicate record and its history stays attached."""
    authorize(request, asset.org_unit, asset.category)
    extra = clean_details(details)
    extra.pop("condition", None)  # a condition change is an inspection or condition event, not a silent edit
    if not extra:
        raise field_error("details", "no_change")
    with transaction.atomic():
        locked = Asset.objects.select_for_update().get(pk=asset.pk)
        updated = versioned_update(locked, extra, expected_version)
        _event(request.user, updated, "details", note="Updated: " + ", ".join(sorted(extra)))
        record("asset.details", request=request, entity_type="asset", entity_id=updated.pk, metadata={"fields": sorted(extra)})
    return updated


def inspect_asset(request, asset, condition, next_due, note, expected_version, inspected_on=None):
    """Record an inspection: sets the condition seen, the inspection date and the next due date, with an event in the history."""
    authorize(request, asset.org_unit, asset.category)
    if asset.status == "retired":
        raise InvalidTransition()
    if condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    today = timezone.localdate()
    seen = _date(inspected_on, "inspected_on") or today
    if seen > today:
        raise field_error("inspected_on", "date_in_future")
    due = _date(next_due, "next_inspection_due")
    if due is not None and due <= seen:
        raise field_error("next_inspection_due", "due_before_inspection")
    if condition == "unserviceable" and not (note or "").strip():
        raise field_error("note", "note_required")
    with transaction.atomic():
        locked = Asset.objects.select_for_update().get(pk=asset.pk)
        old = locked.condition
        updated = versioned_update(locked, {"condition": condition, "last_inspected_on": seen, "next_inspection_due": due}, expected_version)
        _event(request.user, updated, "inspection", note=f"{old} -> {condition}. {(note or '')[:200]}".strip())
        record("asset.inspect", request=request, entity_type="asset", entity_id=updated.pk,
               metadata={"from": old, "to": condition, "next_due": due.isoformat() if due else None})
    return updated


def replace_asset(request, asset, identifier, note, expected_version, details=None):
    """Replace an asset: register the successor in the same unit, retire the old one and link them. Both histories stay."""
    authorize(request, asset.org_unit, asset.category)
    if asset.replaced_by_id or asset.status not in ("in_stock", "maintenance", "lost", "missing"):
        raise InvalidTransition()
    if not (note or "").strip():
        raise field_error("note", "note_required")
    from apps.weapons import services as weapons
    weapons.guard_asset_change(asset, "retire")
    ident = (identifier or "").strip().upper()
    if not IDENT_RE.match(ident):
        raise field_error("identifier", "identifier_invalid")
    if Asset.objects.filter(category=asset.category, identifier=ident).exists():
        raise field_error("identifier", "asset_duplicate")
    extra = clean_details(details or {})
    with transaction.atomic():
        locked = Asset.objects.select_for_update().get(pk=asset.pk)
        if locked.version != expected_version:
            raise VersionConflict()
        if locked.replaced_by_id or locked.status not in ("in_stock", "maintenance", "lost", "missing"):
            raise InvalidTransition()
        new = Asset.objects.create(category=locked.category, org_unit=locked.org_unit, identifier=ident,
                                   description=locked.description, **extra)
        old_status = locked.status
        updated = versioned_update(locked, {"status": "retired", "issued_to_unit": None, "replaced_by": new}, expected_version)
        _event(request.user, new, "register", to_status="in_stock", to_unit=new.org_unit, note=f"Replaces {locked.identifier}")
        _event(request.user, updated, "replaced", old_status, "retired", note=f"Replaced by {ident}. {note.strip()[:200]}")
        weapons.close_custody_on_loss(updated, "retire", request.user)
        record("asset.replace", request=request, entity_type="asset", entity_id=updated.pk,
               metadata={"replacement": str(new.pk), "identifier": ident})
    return updated, new


def set_custodian(request, asset, candidate, expected_version):
    authorize(request, asset.org_unit, asset.category)
    if candidate is not None:
        ok = candidate.is_active and scope.can(candidate, "logistics.manage", unit=asset.org_unit) and (
            not asset.category.restricted or scope.can(candidate, "logistics.restricted", unit=asset.org_unit))
        if not ok:
            raise field_error("user", "custodian_not_authorised")
    with transaction.atomic():
        updated = versioned_update(asset, {"custodian": candidate}, expected_version)
        _event(request.user, updated, "custodian", note=candidate.username if candidate else "cleared")
        record("asset.custodian", request=request, entity_type="asset", entity_id=updated.pk,
               metadata={"custodian": str(candidate.pk) if candidate else None})
    return updated


# ------------------------------------------------------------------ reconciliation
def start_reconciliation(request, unit, notes=""):
    placeable(unit)
    authorize(request, unit, perm="logistics.reconcile")
    restricted = scope.can(request.user, "logistics.restricted", unit=unit)
    with transaction.atomic():
        if Reconciliation.objects.filter(org_unit=unit, status="open").exists():
            raise field_error("org_unit", "reconciliation_open")
        rec = Reconciliation.objects.create(org_unit=unit, includes_restricted=restricted, started_by=request.user,
                                            notes=notes[:300])
        lines = []
        stock = StockLine.objects.filter(org_unit=unit).select_related("category")
        assets = Asset.objects.filter(org_unit=unit, status__in=["in_stock", "maintenance", "missing"]).select_related("category")
        if not restricted:
            stock, assets = stock.filter(category__restricted=False), assets.filter(category__restricted=False)
        for s in stock:
            lines.append(ReconciliationLine(reconciliation=rec, stock_line=s, label=f"{s.category.name_en} ({s.uom})",
                                            expected_quantity=s.quantity))
        for a in assets:
            lines.append(ReconciliationLine(reconciliation=rec, asset=a, label=f"{a.category.name_en} {a.identifier}"))
        if not lines:
            raise field_error("org_unit", "nothing_to_reconcile")
        ReconciliationLine.objects.bulk_create(lines)
        record("reconciliation.start", request=request, entity_type="reconciliation", entity_id=rec.pk,
               metadata={"unit": str(unit.pk), "lines": len(lines), "restricted": restricted})
    return rec


def _auth_recon(request, rec):
    authorize(request, rec.org_unit, perm="logistics.reconcile")
    if rec.includes_restricted and not scope.can(request.user, "logistics.restricted", unit=rec.org_unit):
        record("access.denied", request=request, outcome="denied", entity_type="reconciliation", entity_id=rec.pk,
               metadata={"permission": "logistics.restricted"})
        raise PermissionDenied("You do not have permission to do that here.", code="permission_denied")


def count_lines(request, rec, items):
    _auth_recon(request, rec)
    if rec.status != "open":
        raise InvalidTransition()
    by_id = {str(l.pk): l for l in rec.lines.all()}
    for item in items:
        line = by_id.get(str(item.get("id")))
        if line is None:
            raise field_error("lines", "line_not_found")
        if line.stock_line_id:
            q = item.get("counted_quantity")
            if not isinstance(q, int) or isinstance(q, bool) or not 0 <= q <= 10**9:
                raise field_error("lines", "invalid_count")
            line.counted_quantity = q
        else:
            f = item.get("found")
            if not isinstance(f, bool):
                raise field_error("lines", "invalid_count")
            line.found = f
    with transaction.atomic():
        for line in by_id.values():
            line.save()
        record("reconciliation.count", request=request, entity_type="reconciliation", entity_id=rec.pk,
               metadata={"lines": len(items)})


def complete_reconciliation(request, rec, expected_version):
    _auth_recon(request, rec)
    if rec.version != expected_version:
        raise VersionConflict()
    if rec.status != "open":
        raise InvalidTransition()
    lines = list(rec.lines.select_related("stock_line", "asset"))
    if any((l.stock_line_id and l.counted_quantity is None) or (l.asset_id and l.found is None) for l in lines):
        raise field_error("lines", "reconciliation_incomplete")
    variances = missing = 0
    with transaction.atomic():
        for l in lines:
            if l.stock_line_id:
                current = StockLine.objects.select_for_update().get(pk=l.stock_line_id).quantity
                delta = l.counted_quantity - current  # against the *current* balance, not the snapshot
                if delta:
                    _apply(request.user, l.stock_line_id, "adjust", delta, f"Reconciliation {rec.pk}", authority_ref=f"Reconciliation {rec.pk}")
                    variances += 1
            else:
                a = Asset.objects.select_for_update().get(pk=l.asset_id)
                if not l.found and a.status in ("in_stock", "maintenance"):
                    Asset.objects.filter(pk=a.pk).update(status="missing", version=F("version") + 1, updated_at=timezone.now())
                    _event(request.user, a, "reconcile_missing", a.status, "missing", note=f"Reconciliation {rec.pk}")
                    missing += 1
                elif l.found and a.status == "missing":
                    Asset.objects.filter(pk=a.pk).update(status="in_stock", version=F("version") + 1, updated_at=timezone.now())
                    _event(request.user, a, "reconcile_found", "missing", "in_stock", note=f"Reconciliation {rec.pk}")
        updated = versioned_update(rec, {"status": "completed", "completed_by": request.user,
                                         "completed_at": timezone.now()}, expected_version)
        record("reconciliation.complete", request=request, entity_type="reconciliation", entity_id=rec.pk,
               metadata={"variances": variances, "missing": missing})
    return updated


def cancel_reconciliation(request, rec, expected_version):
    _auth_recon(request, rec)
    if rec.version != expected_version:
        raise VersionConflict()
    if rec.status != "open":
        raise InvalidTransition()
    with transaction.atomic():
        updated = versioned_update(rec, {"status": "cancelled"}, expected_version)
        record("reconciliation.cancel", request=request, entity_type="reconciliation", entity_id=rec.pk)
    return updated


# ------------------------------------------------------------------ summary
def summary(user):
    q = scope.unit_scope_q(user, "logistics.report", "org_unit__")
    if q is None:
        return {"rows": []}
    restricted = scope.unit_scope_q(user, "logistics.restricted", "org_unit__")
    allowed = (q & Q(category__restricted=False)) | ((q & restricted & Q(category__restricted=True)) if restricted is not None else Q(pk__in=[]))
    regions = {str(r.pk): r for r in OrganizationalUnit.objects.filter(level="region")}
    rows = {}

    def row(cat, path):
        rid = region_id(path)
        key = (cat.pk, rid)
        if key not in rows:
            r = regions.get(rid)
            rows[key] = {"category": {"id": str(cat.pk), "code": cat.code, "name_en": cat.name_en, "name_so": cat.name_so,
                                      "restricted": cat.restricted},
                         "region": {"id": rid, "code": r.code if r else "", "name_en": r.name_en if r else "", "name_so": r.name_so if r else ""},
                         "stock_lines": 0, "quantity": 0, "below_reorder": 0, "assets": {}}
        return rows[key]

    # Grouped in the database (category x unit), never one Python iteration per stock line or asset.
    from django.db.models import Count, Sum
    from .models import InventoryCategory
    cats = {c.pk: c for c in InventoryCategory.objects.all()}
    grouped = (StockLine.objects.filter(allowed).values("category", "org_unit__path")
               .annotate(n=Count("pk"), qty=Sum("quantity"), low=Count("pk", filter=Q(reorder_level__gt=0, quantity__lte=F("reorder_level")))))
    for g in grouped:
        r = row(cats[g["category"]], g["org_unit__path"])
        r["stock_lines"] += g["n"]
        r["quantity"] += g["qty"] or 0
        r["below_reorder"] += g["low"]
    for cid, path, status, n in Asset.objects.filter(allowed).values_list("category", "org_unit__path", "status").annotate(n=Count("pk")):
        r = row(cats[cid], path)
        r["assets"][status] = r["assets"].get(status, 0) + n
    return {"rows": sorted(rows.values(), key=lambda x: (x["category"]["code"], x["region"]["code"]))}


# ------------------------------------------------------------------ equipment lifecycle summary (dashboard)
def equipment_summary(user, today=None):
    """Asset lifecycle figures for everything the user may see: status, condition, inspections due, acquisition spend and categories
    waiting for approval. A fixed number of grouped queries; prices only for users who may see logistics reports."""
    from datetime import timedelta
    from django.db.models import Count, DecimalField, Sum
    from django.db.models.functions import Coalesce
    today = today or timezone.localdate()
    horizon = today + timedelta(days=30)
    assets = Asset.objects.filter(visible_q(user, "org_unit__", "category__"))
    live = assets.exclude(status="retired")
    status = dict(assets.values_list("status").annotate(n=Count("pk")))
    condition = dict(live.values_list("condition").annotate(n=Count("pk")))
    out = {
        "assets": sum(status.values()), "by_status": status, "by_condition": condition,
        "inspection_due": live.filter(next_inspection_due__isnull=False, next_inspection_due__lte=horizon).count(),
        "inspection_overdue": live.filter(next_inspection_due__isnull=False, next_inspection_due__lt=today).count(),
        "awaiting_replacement": live.filter(condition="unserviceable").count(),
        "replaced": assets.filter(replaced_by__isnull=False).count(),
        "acquisition": {"visible": False, "by_currency": []},
        "pending_approvals": {"categories": 0},
    }
    if scope.has_anywhere(user, "logistics.report"):
        rows = (assets.filter(acquisition_cost__isnull=False).values("currency")
                .annotate(total=Coalesce(Sum("acquisition_cost"), 0, output_field=DecimalField(max_digits=18, decimal_places=2)), n=Count("pk")).order_by("currency"))
        out["acquisition"] = {"visible": True, "by_currency": [{"currency": r["currency"], "total": str(r["total"]), "assets": r["n"]} for r in rows]}
    can_approve = scope.can(user, "logistics.approve")
    can_restricted = scope.can(user, "logistics.restricted_approve")
    if can_approve or can_restricted:
        from .models import InventoryCategory
        cats = InventoryCategory.objects.filter(approval_status="draft", active=True)
        if not can_approve:
            cats = cats.filter(restricted=True)
        elif not can_restricted:
            cats = cats.filter(restricted=False)
        out["pending_approvals"]["categories"] = cats.count()
    return out
