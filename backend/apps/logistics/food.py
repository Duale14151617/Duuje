"""Food stores: supplier receipts with expiry, store-to-unit allocations with delivery acknowledgement, warnings.

Food is an ordinary stock category (its code starts with "food"), so every movement is an entry in the same append-only stock
ledger and the balance can never go negative. This module adds what food needs on top: who supplied it, when it expires, which
Army order allowed a movement, and proof that it arrived. HQ administrators act directly here (every action is audited and
carries its order or delivery note reference); the quantities cannot be changed afterwards, only corrected by a further entry.
"""
from datetime import date, timedelta

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.accounts import scope
from apps.audit.services import record
from apps.core.concurrency import versioned_update
from apps.core.errors import field_error

from . import services as svc
from .models import FoodAllocation, FoodBatch, InventoryCategory, StockLine, Supplier

PERM = "food.manage"


class InvalidState(APIException):
    status_code = 409
    default_detail = "That is not allowed in the current state."
    default_code = "invalid_transition"


def _text(value, field, code, maxlen, required=True):
    value = str(value or "").strip()
    if required and not value:
        raise field_error(field, code, "Required.")
    if len(value) > maxlen:
        raise field_error(field, "too_long", "Too long.")
    return value


def _qty(value, field="quantity"):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise field_error(field, "invalid_quantity", "Enter a whole number above zero.")
    if n <= 0 or n > 100_000_000:
        raise field_error(field, "invalid_quantity", "Enter a whole number above zero.")
    return n


def _day(value, field, required=True):
    if value in (None, ""):
        if required:
            raise field_error(field, "invalid_date", "Required.")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(field, "invalid_date", "Use a date like 2026-01-31.")


def food_category(category):
    if not category.code.startswith("food"):
        raise field_error("category", "not_food_category", "That category is not a food category.")
    svc.usable(category, "stock")


def _order(d):
    ref = _text(d.get("order_ref"), "order_ref", "order_required", 150)
    officer = _text(d.get("issuing_officer"), "issuing_officer", "issuing_officer_required", 150)
    return ref, officer, _day(d.get("order_date"), "order_date")


# ------------------------------------------------------------------ suppliers
def supplier_create(request, d):
    name = _text(d.get("name"), "name", "name_required", 150)
    if Supplier.objects.filter(name__iexact=name).exists():
        raise field_error("name", "supplier_exists", "A supplier with that name is already on file.")
    with transaction.atomic():
        s = Supplier.objects.create(name=name, phone=_text(d.get("phone"), "phone", "", 30, False),
                                    address=_text(d.get("address"), "address", "", 200, False), notes=_text(d.get("notes"), "notes", "", 300, False))
        record("food.supplier_create", request=request, entity_type="supplier", entity_id=s.pk, metadata={"name": s.name})
    return s


def supplier_update(request, s, d, expected):
    fields = {}
    if "name" in d:
        fields["name"] = _text(d["name"], "name", "name_required", 150)
        if Supplier.objects.filter(name__iexact=fields["name"]).exclude(pk=s.pk).exists():
            raise field_error("name", "supplier_exists", "A supplier with that name is already on file.")
    for key, n in (("phone", 30), ("address", 200), ("notes", 300)):
        if key in d:
            fields[key] = _text(d[key], key, "", n, False)
    if "active" in d:
        fields["active"] = bool(d["active"])
    with transaction.atomic():
        s = versioned_update(s, fields, expected)
        record("food.supplier_update", request=request, entity_type="supplier", entity_id=s.pk, metadata={"fields": sorted(fields)})
    return s


# ------------------------------------------------------------------ receipts
def receive(request, d):
    from apps.organization.models import OrganizationalUnit

    category = InventoryCategory.objects.filter(pk=str(d.get("category") or "")).first() if _isid(d.get("category")) else None
    unit = OrganizationalUnit.objects.filter(pk=str(d.get("org_unit") or "")).first() if _isid(d.get("org_unit")) else None
    supplier = Supplier.objects.filter(pk=str(d.get("supplier") or "")).first() if _isid(d.get("supplier")) else None
    if category is None:
        raise field_error("category", "category_invalid", "Choose a category.")
    if unit is None:
        raise field_error("org_unit", "org_unit_invalid", "That unit cannot be used.")
    if supplier is None or not supplier.active:
        raise field_error("supplier", "supplier_invalid", "Choose an active supplier.")
    food_category(category)
    svc.placeable(unit)
    svc.authorize(request, unit, category, perm=PERM)
    quantity = _qty(d.get("quantity"))
    received_on = _day(d.get("received_on"), "received_on", required=False) or date.today()
    expires_on = _day(d.get("expires_on"), "expires_on", required=False)
    if expires_on and expires_on < received_on:
        raise field_error("expires_on", "expires_before_received", "The expiry date is before the delivery date.")
    note = _text(d.get("delivery_note_ref"), "delivery_note_ref", "delivery_note_required", 60)
    order_ref = _text(d.get("order_ref"), "order_ref", "order_required", 150)
    batch_ref = _text(d.get("batch_ref"), "batch_ref", "", 60, False)
    if FoodBatch.objects.filter(supplier=supplier, delivery_note_ref=note, source="receipt").exists():
        raise field_error("delivery_note_ref", "duplicate_delivery_note", "That delivery note was already entered for this supplier.")
    with transaction.atomic():
        line, _ = StockLine.objects.get_or_create(category=category, org_unit=unit, defaults={
            "uom": _text(d.get("uom"), "uom", "", 16, False) or "kg", "reorder_level": 0})
        txn = svc._apply(request.user, line.pk, "receive", quantity, f"Supplier: {supplier.name}"[:300],
                         external_ref=note, authority_ref=order_ref)
        batch = FoodBatch.objects.create(
            stock_line=line, supplier=supplier, batch_ref=batch_ref, quantity=quantity, remaining=quantity, received_on=received_on,
            expires_on=expires_on, source="receipt", delivery_note_ref=note, authority_ref=order_ref, txn=txn,
            created_by=request.user, created_by_username=request.user.username)
        record("food.receive", request=request, entity_type="stock_line", entity_id=line.pk,
               metadata={"supplier": str(supplier.pk), "quantity": quantity, "delivery_note": note, "order_ref": order_ref,
                         "expires_on": expires_on.isoformat() if expires_on else None, "balance": txn.balance_after})
    return batch


def _isid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


# ------------------------------------------------------------------ allocations
def _consume(line, quantity):
    """Take `quantity` from the store's batches, earliest expiry first. Returns [{"batch", "qty"}] (any part not covered by
    a batch is stock that never went through this module)."""
    taken, need = [], quantity
    batches = FoodBatch.objects.select_for_update().filter(stock_line=line, remaining__gt=0).order_by(
        F("expires_on").asc(nulls_last=True), "received_on", "created_at")
    for b in batches:
        if need == 0:
            break
        n = min(b.remaining, need)
        FoodBatch.objects.filter(pk=b.pk).update(remaining=F("remaining") - n)
        taken.append({"batch": str(b.pk), "qty": n})
        need -= n
    return taken


def issue(request, d):
    from apps.organization.models import OrganizationalUnit

    line = StockLine.objects.select_related("category", "org_unit").filter(pk=str(d.get("stock_line") or "")).first() \
        if _isid(d.get("stock_line")) else None
    to_unit = OrganizationalUnit.objects.filter(pk=str(d.get("to_unit") or "")).first() if _isid(d.get("to_unit")) else None
    if line is None:
        raise field_error("stock_line", "stock_line_invalid", "Choose a store.")
    if to_unit is None:
        raise field_error("to_unit", "org_unit_invalid", "That unit cannot be used.")
    food_category(line.category)
    if to_unit.pk == line.org_unit_id:
        raise field_error("to_unit", "no_change", "Choose a different unit.")
    svc.placeable(to_unit, "to_unit")
    svc.authorize(request, line.org_unit, line.category, perm=PERM)
    svc.authorize(request, to_unit, line.category, perm=PERM)
    quantity = _qty(d.get("quantity"))
    order_ref, officer, order_date = _order(d)
    note = _text(d.get("issue_note_ref"), "issue_note_ref", "issue_note_required", 60)
    with transaction.atomic():
        alloc = FoodAllocation(from_line=line, to_unit=to_unit, quantity=quantity, order_ref=order_ref, issuing_officer=officer,
                               order_date=order_date, issue_note_ref=note, issued_by=request.user, issued_by_username=request.user.username)
        svc._apply(request.user, line.pk, "transfer_out", -quantity, f"Allocation to {to_unit.name_en}"[:300], counterpart=to_unit,
                   group=alloc.group, external_ref=note, authority_ref=order_ref)  # raises insufficient_stock; nothing else is written
        alloc.consumed = _consume(line, quantity)
        alloc.save()
        record("food.allocation_issue", request=request, entity_type="food_allocation", entity_id=alloc.pk,
               metadata={"from": str(line.org_unit_id), "to": str(to_unit.pk), "quantity": quantity, "order_ref": order_ref,
                         "issue_note": note, "group": str(alloc.group)})
    return alloc


def acknowledge(request, alloc, d, expected):
    received_by = _text(d.get("received_by_name"), "received_by_name", "receiver_required", 150)
    receipt_note = _text(d.get("receipt_note_ref"), "receipt_note_ref", "receipt_note_required", 60)
    with transaction.atomic():
        alloc = FoodAllocation.objects.select_for_update().select_related("from_line__category", "from_line__org_unit", "to_unit").get(pk=alloc.pk)
        if alloc.status != "issued":
            raise InvalidState()
        category = alloc.from_line.category
        svc.authorize(request, alloc.to_unit, category, perm=PERM)
        dest, _ = StockLine.objects.get_or_create(category=category, org_unit=alloc.to_unit, defaults={"uom": alloc.from_line.uom})
        txn = svc._apply(request.user, dest.pk, "transfer_in", alloc.quantity, f"Allocation from {alloc.from_line.org_unit.name_en}"[:300],
                         counterpart=alloc.from_line.org_unit, group=alloc.group, external_ref=receipt_note, authority_ref=alloc.order_ref)
        covered = 0
        for part in alloc.consumed:
            orig = FoodBatch.objects.get(pk=part["batch"])
            FoodBatch.objects.create(
                stock_line=dest, supplier=orig.supplier, batch_ref=orig.batch_ref, quantity=part["qty"], remaining=part["qty"],
                received_on=date.today(), expires_on=orig.expires_on, source="allocation", delivery_note_ref=receipt_note,
                authority_ref=alloc.order_ref, txn=txn, created_by=request.user, created_by_username=request.user.username)
            covered += part["qty"]
        if covered < alloc.quantity:  # the part of the stock that had no batch behind it stays "unbatched" and says so
            FoodBatch.objects.create(
                stock_line=dest, batch_ref="unbatched", quantity=alloc.quantity - covered, remaining=alloc.quantity - covered,
                received_on=date.today(), source="allocation", delivery_note_ref=receipt_note, authority_ref=alloc.order_ref, txn=txn,
                created_by=request.user, created_by_username=request.user.username)
        alloc = versioned_update(alloc, {"status": "delivered", "delivered_at": timezone.now(), "received_by_name": received_by,
                                         "receipt_note_ref": receipt_note, "acknowledged_by": request.user,
                                         "acknowledged_by_username": request.user.username}, expected)
        record("food.allocation_deliver", request=request, entity_type="food_allocation", entity_id=alloc.pk,
               metadata={"quantity": alloc.quantity, "receipt_note": receipt_note, "received_by": received_by, "group": str(alloc.group)})
    return alloc


def cancel(request, alloc, d, expected):
    reason = _text(d.get("reason"), "reason", "reason_required", 300)
    with transaction.atomic():
        alloc = FoodAllocation.objects.select_for_update().select_related("from_line__category", "from_line__org_unit", "to_unit").get(pk=alloc.pk)
        if alloc.status != "issued":
            raise InvalidState()
        svc.authorize(request, alloc.from_line.org_unit, alloc.from_line.category, perm=PERM)
        txn = svc._apply(request.user, alloc.from_line_id, "transfer_in", alloc.quantity, f"Allocation cancelled: {reason}"[:300],
                   counterpart=alloc.to_unit, group=alloc.group, external_ref=alloc.issue_note_ref, authority_ref=alloc.order_ref)
        covered = 0
        for part in alloc.consumed:
            FoodBatch.objects.filter(pk=part["batch"]).update(remaining=F("remaining") + part["qty"])
            covered += part["qty"]
        if covered < alloc.quantity:
            FoodBatch.objects.create(
                stock_line=alloc.from_line, batch_ref="returned", quantity=alloc.quantity - covered, remaining=alloc.quantity - covered,
                received_on=date.today(), source="allocation", delivery_note_ref=alloc.issue_note_ref, authority_ref=alloc.order_ref,
                txn=txn, created_by=request.user, created_by_username=request.user.username)
        alloc = versioned_update(alloc, {"status": "cancelled", "cancel_reason": reason, "cancelled_at": timezone.now()}, expected)
        record("food.allocation_cancel", request=request, entity_type="food_allocation", entity_id=alloc.pk,
               metadata={"quantity": alloc.quantity, "reason": reason, "group": str(alloc.group)})
    return alloc


# ------------------------------------------------------------------ warnings
def warnings(user, days=30):
    """Stores the caller may see: below reorder level, food that has expired or expires within `days`, and stores whose batches do
    not add up to the ledger balance."""
    q = scope.unit_scope_q(user, "food.view", "org_unit__")
    if q is None:
        return {"low_stock": [], "expiring": [], "unbatched": []}
    lines = list(StockLine.objects.filter(q, category__code__startswith="food").select_related("category", "org_unit"))
    ids = [ln.pk for ln in lines]
    today, horizon = date.today(), date.today() + timedelta(days=days)
    low = [{"stock_line": str(ln.pk), "org_unit": ln.org_unit.name_en, "category": ln.category.name_en,
            "quantity": ln.quantity, "reorder_level": ln.reorder_level, "uom": ln.uom}
           for ln in lines if ln.reorder_level > 0 and ln.quantity <= ln.reorder_level]
    soon = FoodBatch.objects.filter(stock_line__in=ids, remaining__gt=0, expires_on__isnull=False, expires_on__lte=horizon
                                    ).select_related("stock_line__org_unit", "stock_line__category", "supplier").order_by("expires_on")
    expiring = [{"batch": str(b.pk), "stock_line": str(b.stock_line_id), "org_unit": b.stock_line.org_unit.name_en,
                 "category": b.stock_line.category.name_en, "remaining": b.remaining, "uom": b.stock_line.uom,
                 "expires_on": b.expires_on.isoformat(), "expired": b.expires_on < today, "batch_ref": b.batch_ref,
                 "supplier": b.supplier.name if b.supplier_id else ""} for b in soon]
    sums = dict(FoodBatch.objects.filter(stock_line__in=ids).order_by().values("stock_line").annotate(s=Sum("remaining")).values_list("stock_line", "s"))
    unbatched = [{"stock_line": str(ln.pk), "org_unit": ln.org_unit.name_en, "category": ln.category.name_en,
                  "ledger": ln.quantity, "batched": sums.get(ln.pk, 0)} for ln in lines if (sums.get(ln.pk) or 0) != ln.quantity]
    return {"low_stock": low, "expiring": expiring, "unbatched": unbatched}
