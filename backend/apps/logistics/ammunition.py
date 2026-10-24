"""Ammunition ledger. Transaction-based: every balance is derived from the saved movements, never typed in.

Ammunition = stock categories whose code starts with "ammunition" (one category per type or calibre, for example ammunition_762).
It reuses the stock line and the append-only transaction table, and adds the movements an ammunition account needs:

    opening   the opening stock balance (only as the very first entry of a line)
    receive   receipts                              (voucher / delivery note number required)
    return    returned to store                     (voucher required; cannot exceed what was issued)
    issue     issued out                            (voucher required)
    expenditure  recorded expenditure               (reason required)
    loss, damage                                    (reason + documented authorization)
    adjust    authorized adjustment, either way     (reason + documented authorization + logistics.reconcile)
    transfer_in / transfer_out  between units (generic transfer, paired)

Protection: a negative balance is refused (service and database), the same voucher cannot be booked twice for the same kind of
movement on a line (database constraint), an opening balance exists once, rows are append-only, so an adjustment never overwrites
the original values: it adds a new row that keeps who, why and on whose authority.
"""
from datetime import date, datetime, time

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts import scope
from apps.audit.services import record
from apps.core.errors import field_error

from . import services as svc
from .models import Reconciliation, ReconciliationLine, StockLine, StockTransaction

PREFIX = "ammunition"
SIGN = {"opening": 1, "receive": 1, "return": 1, "issue": -1, "expenditure": -1, "loss": -1, "damage": -1, "adjust": 0}
NEEDS_VOUCHER = {"receive", "issue", "return"}
NEEDS_REASON = {"opening", "expenditure", "loss", "damage", "adjust"}
NEEDS_AUTHORITY = {"loss", "damage", "adjust"}


def is_ammunition(category):
    return category.code.startswith(PREFIX)


def post(request, line, kind, quantity, reason="", external_ref="", authority_ref="", counterpart=None, expected_balance=None, via_soldier=False):
    if not is_ammunition(line.category):
        raise field_error("category", "not_ammunition")
    if kind not in SIGN:
        raise field_error("kind", "invalid_kind")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity == 0 or abs(quantity) > 10**9:
        raise field_error("quantity", "quantity_invalid")
    if kind != "adjust" and quantity < 0:
        raise field_error("quantity", "quantity_invalid")  # the kind decides the direction; only an adjustment is signed
    reason, external_ref, authority_ref = (reason or "").strip(), (external_ref or "").strip(), (authority_ref or "").strip()
    if kind in NEEDS_VOUCHER and not external_ref:
        raise field_error("external_ref", "voucher_required")
    if kind in NEEDS_REASON and not reason:
        raise field_error("reason", "reason_required")
    if kind in NEEDS_AUTHORITY and not authority_ref:
        raise field_error("authority_ref", "authorization_required")
    svc.authorize(request, line.org_unit, line.category)
    svc.usable(line.category, "stock")
    if kind == "adjust" and not scope.can(request.user, "logistics.reconcile", unit=line.org_unit):
        record("access.denied", request=request, outcome="denied", entity_type="stock_line", entity_id=line.pk,
               metadata={"action": "ammunition_adjust", "permission": "logistics.reconcile"})
        raise field_error("kind", "adjust_not_authorized")  # adjusting a balance is a separate, explicit authority
    if counterpart is not None:
        svc.placeable(counterpart, "counterpart")
    delta = quantity if kind == "adjust" else SIGN[kind] * quantity
    try:
        with transaction.atomic():
            locked = StockLine.objects.select_for_update().get(pk=line.pk)
            moves = StockTransaction.objects.filter(stock_line=locked)
            if kind == "opening" and moves.exists():
                raise field_error("kind", "opening_not_first")  # an opening balance can only start an empty ledger
            if external_ref and moves.filter(kind=kind, external_ref=external_ref).exists():
                raise field_error("external_ref", "duplicate_movement")
            if kind == "return":
                issued = -(moves.filter(kind="issue").aggregate(s=Sum("delta"))["s"] or 0)
                returned = moves.filter(kind="return").aggregate(s=Sum("delta"))["s"] or 0
                if returned + quantity > issued:
                    raise field_error("quantity", "return_exceeds_issued")
                if not via_soldier:
                    # Rounds issued to a soldier come back only through that soldier's holdings (otherwise they would count twice:
                    # in the store and still on the soldier). The general ledger may return only what was issued to other recipients.
                    linked = moves.filter(soldier_rounds__isnull=False)
                    l_issued = -(linked.filter(kind="issue").aggregate(s=Sum("delta"))["s"] or 0)
                    l_returned = linked.filter(kind="return").aggregate(s=Sum("delta"))["s"] or 0
                    if (returned - l_returned) + quantity > issued - l_issued:
                        raise field_error("quantity", "return_exceeds_unassigned")
            txn = svc._apply(request.user, locked.pk, kind, delta, reason, counterpart=counterpart,
                             expected_balance=expected_balance, external_ref=external_ref, authority_ref=authority_ref)
            record(f"ammunition.{kind}", request=request, entity_type="stock_line", entity_id=locked.pk,
                   metadata={"delta": delta, "balance": txn.balance_after, "external_ref": external_ref,
                             "authority_ref": authority_ref})
    except IntegrityError:  # two officers booking the same voucher at once: the database refuses the second
        raise field_error("external_ref", "duplicate_movement")
    return txn


def _balance_at(line, day, inclusive):
    f = {"created_at__date__lte": day} if inclusive else {"created_at__date__lt": day}
    return (StockTransaction.objects.filter(stock_line=line, **f).order_by("-created_at", "-id")
            .values_list("balance_after", flat=True).first()) or 0


def totals(lines, start, end):
    """Aggregate over lines for a period. Outflows are positive magnitudes; every number comes from saved movements."""
    ids = [l.pk for l in lines]
    moves = StockTransaction.objects.filter(stock_line_id__in=ids, created_at__date__range=(start, end))
    by = {k: s for k, s in moves.values_list("kind").annotate(s=Sum("delta"))}
    up = moves.filter(kind="adjust", delta__gt=0).aggregate(s=Sum("delta"))["s"] or 0
    down = -(moves.filter(kind="adjust", delta__lt=0).aggregate(s=Sum("delta"))["s"] or 0)
    return {
        "balance_start": sum(_balance_at(l, start, False) for l in lines),
        "opening_recorded": by.get("opening", 0), "received": by.get("receive", 0) + by.get("transfer_in", 0),
        "returned": by.get("return", 0), "adjusted_up": up,
        "issued": -by.get("issue", 0), "expended": -by.get("expenditure", 0),
        "lost_damaged": -(by.get("loss", 0) + by.get("damage", 0)), "adjusted_down": down,
        "transferred_out": -by.get("transfer_out", 0),
        "remaining": sum(_balance_at(l, end, True) for l in lines),
    }


def statement(line, start, end):
    """Opening balance, each kind of movement, closing balance, the integrity check and reconciliation discrepancies."""
    moves = StockTransaction.objects.filter(stock_line=line, created_at__date__range=(start, end)).order_by("created_at", "id")
    t = totals([line], start, end)
    computed = (t["balance_start"] + t["opening_recorded"] + t["received"] + t["returned"] + t["adjusted_up"]
                - t["issued"] - t["expended"] - t["lost_damaged"] - t["adjusted_down"] - t["transferred_out"])
    recon = []
    for rl in ReconciliationLine.objects.filter(stock_line=line).select_related("reconciliation").order_by("-reconciliation__started_at")[:20]:
        r = rl.reconciliation
        if r.status == Reconciliation.Status.CANCELLED or rl.counted_quantity is None:
            continue
        recon.append({"reconciliation": str(r.pk), "status": r.status, "started_at": r.started_at, "completed_at": r.completed_at,
                      "expected": rl.expected_quantity, "counted": rl.counted_quantity,
                      "variance": rl.counted_quantity - (rl.expected_quantity or 0),
                      "outstanding": r.status == Reconciliation.Status.OPEN and rl.counted_quantity != rl.expected_quantity})
    return {
        "start": start.isoformat(), "end": end.isoformat(), **t, "closing": t["remaining"],
        "check": {"computed_closing": computed, "matches_balances": computed == t["remaining"],
                  "current_quantity": line.quantity,
                  "matches_current": (t["remaining"] == line.quantity) if end >= timezone.localdate() else None},
        "reconciliations": recon,
        "outstanding_discrepancies": sum(1 for r in recon if r["outstanding"]),
        "transactions": [{"id": str(m.pk), "kind": m.kind, "delta": m.delta, "balance_after": m.balance_after, "reason": m.reason,
                          "external_ref": m.external_ref, "authority_ref": m.authority_ref, "actor": m.actor_username,
                          "counterpart": m.counterpart_unit.code if m.counterpart_unit_id else None, "at": m.created_at}
                         for m in moves.select_related("counterpart_unit")[:500]],
    }
