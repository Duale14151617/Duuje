"""PPE rules. Unit-level stock and procurement live in the logistics ledger; this module books what each person holds.

* issue    : store -> person (booked in the unit ledger as an issue under the same voucher number)
* return   : person -> store (booked in the unit ledger as a return)
* damaged / lost / retired : written off the person only; the store already gave the item up when it was issued.
* replace  : one transaction that writes the old item off the person (damaged / retired) and issues a new one, paired by `group`.
Every mutation re-checks scope on the server, takes the stock line's row lock, and is audited."""
import uuid
from datetime import date

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record
from apps.core.errors import field_error
from apps.logistics import services as logi
from apps.personnel.services import NOT_SERVING

from .models import PpeInspection, PpeMovement

PREFIX = "ppe"
SIGN = {"issue": 1, "return": -1, "damaged": -1, "lost": -1, "retired": -1}
CONDITIONS = {c.value for c in PpeMovement.Condition}


def is_ppe_category(category):
    return category.code.startswith(PREFIX)


def held(person_id, line_id):
    return PpeMovement.objects.filter(personnel_id=person_id, stock_line_id=line_id).aggregate(s=Sum("delta"))["s"] or 0


def _qty(quantity):
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 0 < quantity <= 10**6:
        raise field_error("quantity", "quantity_invalid")
    return quantity


def _book(request, person, line, kind, quantity, *, size="", serial="", condition="new", reference="", authority_ref="", note="",
          group=None):
    """Caller holds the stock-line row lock and is inside transaction.atomic()."""
    user = request.user
    who = person.service_number or str(person.pk)
    txn = None
    if kind == "issue":
        txn = logi._apply(user, line.pk, "issue", -quantity, f"PPE issued to {who}", external_ref=reference, authority_ref=authority_ref)
    elif kind == "return":
        txn = logi._apply(user, line.pk, "return", quantity, f"PPE returned by {who}", external_ref=reference, authority_ref=authority_ref)
    row = PpeMovement.objects.create(
        personnel=person, stock_line=line, kind=kind, delta=SIGN[kind] * quantity, size=size, serial=serial, condition=condition,
        reference=reference, authority_ref=authority_ref, note=note, group=group, store_transaction=txn,
        actor_id=user.pk, actor_username=user.username)
    record(f"ppe.{kind}", request=request, entity_type="ppe_movement", entity_id=row.pk,
           metadata={"personnel": str(person.pk), "stock_line": str(line.pk), "delta": row.delta, "reference": reference,
                     "authority_ref": authority_ref, "store_transaction": str(txn.pk) if txn else None})
    return row


def _clean(kind, quantity, d):
    if kind not in SIGN:
        raise field_error("kind", "invalid_kind")
    quantity = _qty(quantity)
    out = {k: str(d.get(k) or "").strip()[:n] for k, n in (("size", 20), ("serial", 64), ("reference", 60), ("authority_ref", 150), ("note", 300))}
    out["condition"] = d.get("condition") or ("new" if kind == "issue" else "good")
    if out["condition"] not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    if kind in ("issue", "return") and not out["reference"]:
        raise field_error("reference", "voucher_required")
    if kind in ("damaged", "lost", "retired") and not out["note"]:
        raise field_error("note", "reason_required")
    if kind == "lost" and not out["authority_ref"]:
        raise field_error("authority_ref", "authorization_required")
    return quantity, out


def _check_line(request, line):
    if not is_ppe_category(line.category):
        raise field_error("category", "not_ppe")
    logi.usable(line.category, "stock")
    logi.authorize(request, line.org_unit, line.category)


def _check_person(person, line):
    if person.status in NOT_SERVING:
        raise field_error("personnel", "person_not_serving")
    if not person.org_unit.path.startswith(line.org_unit.path):
        raise field_error("personnel", "person_outside_unit")


def post(request, person, line, kind, quantity, d):
    quantity, c = _clean(kind, quantity, d)
    _check_line(request, line)
    if kind == "issue":
        _check_person(person, line)
    from apps.logistics.models import StockLine
    with transaction.atomic():
        locked = StockLine.objects.select_for_update().get(pk=line.pk)  # serialises writers on this PPE line
        if kind != "issue" and quantity > held(person.pk, locked.pk):
            raise field_error("quantity", "ppe_exceeds_held")
        return _book(request, person, locked, kind, quantity, **c)


def replace(request, person, line, quantity, out_kind, d):
    """Replace damaged or worn-out PPE: write `quantity` off the person (damaged or retired) and issue the same number new."""
    if out_kind not in ("damaged", "retired"):
        raise field_error("kind", "invalid_kind")
    quantity = _qty(quantity)
    _check_line(request, line)
    _check_person(person, line)
    reason = str(d.get("note") or "").strip()[:300]
    if not reason:
        raise field_error("note", "reason_required")
    ref = str(d.get("reference") or "").strip()[:60]
    if not ref:
        raise field_error("reference", "voucher_required")
    base = {k: str(d.get(k) or "").strip()[:n] for k, n in (("size", 20), ("serial", 64), ("authority_ref", 150))}
    new_condition = d.get("condition") or "new"
    if new_condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    from apps.logistics.models import StockLine
    group = uuid.uuid4()
    with transaction.atomic():
        locked = StockLine.objects.select_for_update().get(pk=line.pk)
        if quantity > held(person.pk, locked.pk):
            raise field_error("quantity", "ppe_exceeds_held")
        old = _book(request, person, locked, out_kind, quantity, condition="unserviceable", note=reason, group=group, **base)
        new = _book(request, person, locked, "issue", quantity, condition=new_condition, reference=ref, note=f"Replacement. {reason}"[:300],
                    group=group, **base)
        record("ppe.replace", request=request, entity_type="ppe_movement", entity_id=new.pk,
               metadata={"personnel": str(person.pk), "group": str(group), "quantity": quantity, "out": out_kind})
    return old, new


def inspect(request, person, line, condition, inspected_on, next_due, note):
    _check_line(request, line)
    if condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    today = timezone.localdate()
    try:
        seen = date.fromisoformat(str(inspected_on)) if inspected_on else today
        due = date.fromisoformat(str(next_due)) if next_due else None
    except ValueError:
        raise field_error("inspected_on", "invalid_date", "Use a date like 2026-03-01.")
    if seen > today:
        raise field_error("inspected_on", "date_in_future")
    if due is not None and due <= seen:
        raise field_error("next_due", "due_before_inspection")
    if held(person.pk, line.pk) <= 0:
        raise field_error("personnel", "ppe_not_held")
    note = str(note or "").strip()[:300]
    if condition == "unserviceable" and not note:
        raise field_error("note", "note_required")
    with transaction.atomic():
        row = PpeInspection.objects.create(personnel=person, stock_line=line, inspected_on=seen, condition=condition, next_due=due,
                                           note=note, actor_id=request.user.pk, actor_username=request.user.username)
        record("ppe.inspect", request=request, entity_type="ppe_inspection", entity_id=row.pk,
               metadata={"personnel": str(person.pk), "stock_line": str(line.pk), "condition": condition,
                         "next_due": due.isoformat() if due else None})
    return row


def person_ppe(person):
    """One person's PPE: what they hold per line, their latest inspection, and the complete history (newest first)."""
    sums = {lid: s for lid, s in PpeMovement.objects.filter(personnel=person).values_list("stock_line_id").annotate(s=Sum("delta"))}
    latest = {}
    for i in PpeInspection.objects.filter(personnel=person).order_by("inspected_on", "created_at"):
        latest[i.stock_line_id] = i
    rows = list(PpeMovement.objects.filter(personnel=person).select_related("stock_line__category", "stock_line__org_unit")[:300])
    lines = {r.stock_line_id: r.stock_line for r in rows}
    from apps.logistics.models import StockLine
    missing = set(sums) - set(lines)
    if missing:
        lines.update({l.pk: l for l in StockLine.objects.filter(pk__in=missing).select_related("category", "org_unit")})
    holdings = []
    for lid, qty in sums.items():
        l = lines[lid]
        i = latest.get(lid)
        holdings.append({"stock_line": str(lid), "category": {"code": l.category.code, "name_en": l.category.name_en, "name_so": l.category.name_so},
                         "unit": {"id": str(l.org_unit_id), "name_en": l.org_unit.name_en, "name_so": l.org_unit.name_so}, "held": qty,
                         "last_inspected_on": i.inspected_on if i else None, "condition": i.condition if i else None,
                         "next_due": i.next_due if i else None})
    history = [{"id": str(r.pk), "kind": r.kind, "quantity": abs(r.delta), "size": r.size, "serial": r.serial, "condition": r.condition,
                "reference": r.reference, "authority_ref": r.authority_ref, "note": r.note, "actor": r.actor_username,
                "stock_line": str(r.stock_line_id), "group": str(r.group) if r.group else None,
                "category": {"code": r.stock_line.category.code, "name_en": r.stock_line.category.name_en, "name_so": r.stock_line.category.name_so},
                "at": r.created_at} for r in rows]
    return sorted(holdings, key=lambda h: h["category"]["code"]), history
