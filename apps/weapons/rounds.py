"""Rounds held by a soldier: issue from the unit's ammunition store, return, expenditure and loss. Balances are derived.

Issue and return are also booked in the unit's ammunition ledger (so the store balance always matches), under the same voucher
number. Expenditure and loss only write rounds off the soldier: the store already gave them up at issue.
"""
from django.db import transaction
from django.db.models import Sum

from apps.audit.services import record
from apps.core.errors import field_error
from apps.logistics import ammunition as ammo
from apps.logistics import services as logi
from apps.logistics.models import StockLine, StockTransaction
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from .models import SoldierRounds

SIGN = {"issue": 1, "return": -1, "expended": -1, "lost": -1}


def held(person_id, line_id):
    return SoldierRounds.objects.filter(personnel_id=person_id, stock_line_id=line_id).aggregate(s=Sum("delta"))["s"] or 0


def post(request, person, line, kind, quantity, reference="", authority_ref="", note=""):
    user = request.user
    if kind not in SIGN:
        raise field_error("kind", "invalid_kind")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 0 < quantity <= 10**9:
        raise field_error("quantity", "quantity_invalid")
    reference, authority_ref, note = (reference or "").strip()[:60], (authority_ref or "").strip()[:150], (note or "").strip()[:300]
    if not ammo.is_ammunition(line.category):
        raise field_error("category", "not_ammunition")
    if kind in ("issue", "return") and not reference:
        raise field_error("reference", "voucher_required")
    if kind in ("expended", "lost") and not note:
        raise field_error("note", "reason_required")
    if kind == "lost" and not authority_ref:
        raise field_error("authority_ref", "authorization_required")
    logi.authorize(request, line.org_unit, line.category)
    if kind == "issue":
        if person.status in NOT_SERVING:
            raise field_error("personnel", "person_not_serving")
        if not person.org_unit.path.startswith(line.org_unit.path):
            raise field_error("personnel", "person_outside_unit")
    with transaction.atomic():
        locked = StockLine.objects.select_for_update().get(pk=line.pk)  # serialises writers on this ammunition line
        if kind != "issue" and quantity > held(person.pk, locked.pk):
            raise field_error("quantity", "rounds_exceed_held")
        who = person.service_number or str(person.pk)
        txn = None
        if kind == "issue":
            txn = ammo.post(request, locked, "issue", quantity, reason=f"Issued to {who}"[:300], external_ref=reference,
                            authority_ref=authority_ref, via_soldier=True)
        elif kind == "return":
            txn = ammo.post(request, locked, "return", quantity, reason=f"Returned by {who}"[:300], external_ref=reference,
                            authority_ref=authority_ref, via_soldier=True)
        row = SoldierRounds.objects.create(personnel=person, stock_line=locked, kind=kind, delta=SIGN[kind] * quantity,
                                           reference=reference, authority_ref=authority_ref, note=note, store_transaction=txn,
                                           actor_id=user.pk, actor_username=user.username)
        record(f"weapon.rounds_{kind}", request=request, entity_type="soldier_rounds", entity_id=row.pk,
               metadata={"personnel": str(person.pk), "stock_line": str(locked.pk), "delta": row.delta, "reference": reference,
                         "authority_ref": authority_ref, "store_transaction": str(txn.pk) if txn else None})
    return row


def _by_kind(qs):
    return {k: s for k, s in qs.values_list("kind").annotate(s=Sum("delta"))}


def history(person, line=None, limit=500):
    """Complete issue, return, expenditure and loss history of one soldier (newest first), with the running balance per ammunition
    line and the unit-ledger movement each issue or return mirrors."""
    qs = SoldierRounds.objects.filter(personnel=person)
    if line is not None:
        qs = qs.filter(stock_line=line)
    oldest_first = list(qs.select_related("stock_line__category", "stock_line__org_unit").order_by("created_at", "id"))
    running, out = {}, []
    for r in oldest_first:
        running[r.stock_line_id] = running.get(r.stock_line_id, 0) + r.delta
        out.append({"id": str(r.pk), "kind": r.kind, "quantity": abs(r.delta), "delta": r.delta, "balance_after": running[r.stock_line_id],
                    "stock_line": str(r.stock_line_id),
                    "category": {"code": r.stock_line.category.code, "name_en": r.stock_line.category.name_en, "name_so": r.stock_line.category.name_so},
                    "reference": r.reference, "authority_ref": r.authority_ref, "note": r.note, "actor": r.actor_username,
                    "store_transaction": str(r.store_transaction_id) if r.store_transaction_id else None, "at": r.created_at})
    out.reverse()
    return out[:limit], running


def disposition(line, start, end):
    """Accountability for one ammunition line over a period, keeping the two places rounds can be apart:
    physical store stock (the unit ledger) and rounds held by soldiers (the soldier ledger). Each round is in exactly one of
    them, or has been written off as expended or lost, so store balance + rounds held by soldiers is what is still accountable.

    The unit statement shows issues and returns and the store balance; expended and lost rounds are shown here, never as a
    second deduction from the store. The checks compare the two ledgers movement by movement."""
    rows = SoldierRounds.objects.filter(stock_line=line)
    period = rows.filter(created_at__date__range=(start, end))
    pk = _by_kind(period)
    issued, returned, expended, lost = pk.get("issue", 0), -pk.get("return", 0), -pk.get("expended", 0), -pk.get("lost", 0)
    held_start = rows.filter(created_at__date__lt=start).aggregate(s=Sum("delta"))["s"] or 0
    held_end = rows.filter(created_at__date__lte=end).aggregate(s=Sum("delta"))["s"] or 0
    store = ammo.totals([line], start, end)
    moves = StockTransaction.objects.filter(stock_line=line, created_at__date__range=(start, end))
    linked = moves.filter(soldier_rounds__isnull=False)
    linked_issued = -(linked.filter(kind="issue").aggregate(s=Sum("delta"))["s"] or 0)
    linked_returned = linked.filter(kind="return").aggregate(s=Sum("delta"))["s"] or 0
    unlinked_rows = period.filter(kind__in=["issue", "return"], store_transaction__isnull=True).count()
    per_end = {pid: s for pid, s in rows.filter(created_at__date__lte=end).values_list("personnel_id").annotate(s=Sum("delta"))}
    per = {}
    for pid, kind, s in period.values_list("personnel_id", "kind").annotate(s=Sum("delta")):
        per.setdefault(pid, {})[kind] = s
    people = {p.pk: p for p in Personnel.objects.filter(pk__in=set(per) | set(per_end)).select_related("rank", "org_unit")}
    soldiers = []
    for pid in sorted(set(per) | set(per_end), key=lambda i: people[i].full_name):
        p, k = people[pid], per.get(pid, {})
        soldiers.append({"personnel": {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                                       "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}},
                         "issued": k.get("issue", 0), "returned": -k.get("return", 0), "expended": -k.get("expended", 0),
                         "lost": -k.get("lost", 0), "held": per_end.get(pid, 0)})
    negative = sum(1 for x in soldiers if x["held"] < 0)
    arithmetic_ok = held_start + issued - returned - expended - lost == held_end
    checks = {"issues_match_store": linked_issued == issued, "returns_match_store": linked_returned == returned,
              "unlinked_rows": unlinked_rows, "negative_holdings": negative, "arithmetic_ok": arithmetic_ok}
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "store": {"balance_start": store["balance_start"], "issued": store["issued"], "issued_to_soldiers": linked_issued,
                  "issued_other": store["issued"] - linked_issued, "returned": store["returned"], "returned_from_soldiers": linked_returned,
                  "returned_other": store["returned"] - linked_returned, "balance_end": store["remaining"], "current": line.quantity},
        "soldiers": {"held_start": held_start, "issued": issued, "returned": returned, "expended": expended, "lost": lost, "held_end": held_end},
        "accountable_end": store["remaining"] + held_end,  # physical store + still on soldiers; expended and lost are gone
        "per_soldier": soldiers,
        "checks": checks,
        "consistent": checks["issues_match_store"] and checks["returns_match_store"] and unlinked_rows == 0 and negative == 0 and arithmetic_ok,
    }
