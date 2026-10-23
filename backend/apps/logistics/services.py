"""Logistics rules. Every mutation re-checks scope and the restricted-equipment permission on the server."""
import re
import uuid

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


def _apply(user, line_id, kind, delta, reason, counterpart=None, group=None, expected_balance=None, external_ref="", authority_ref=""):
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
        external_ref=(external_ref or "")[:60], authority_ref=(authority_ref or "")[:150], correlation_id=get_correlation_id())


def post_stock(request, line, kind, delta, reason, expected_balance=None):
    if line.category.code.startswith("ammunition"):
        raise field_error("category", "use_ammunition_ledger")  # ammunition has its own ledger with vouchers and authorizations
    authorize(request, line.org_unit, line.category)
    usable(line.category, "stock")
    with transaction.atomic():
        txn = _apply(request.user, line.pk, kind, delta, reason, expected_balance=expected_balance)
        record(f"stock.{kind}", request=request, entity_type="stock_line", entity_id=line.pk,
               metadata={"delta": delta, "balance": txn.balance_after})
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


def register_asset(request, category, unit, identifier, description, weapon_register=False):
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
    with transaction.atomic():
        asset = Asset.objects.create(category=category, org_unit=unit, identifier=identifier, description=description)
        _event(request.user, asset, "register", to_status="in_stock", to_unit=unit)
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

    for s in StockLine.objects.filter(allowed).select_related("category", "org_unit")[:10000]:
        r = row(s.category, s.org_unit.path)
        r["stock_lines"] += 1
        r["quantity"] += s.quantity
        r["below_reorder"] += 1 if s.reorder_level and s.quantity <= s.reorder_level else 0
    for a in Asset.objects.filter(allowed).select_related("category", "org_unit")[:10000]:
        r = row(a.category, a.org_unit.path)
        r["assets"][a.status] = r["assets"].get(a.status, 0) + 1
    return {"rows": sorted(rows.values(), key=lambda x: (x["category"]["code"], x["region"]["code"]))}
