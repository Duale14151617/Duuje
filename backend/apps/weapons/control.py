"""Ammunition control: training events that must balance, warning flags, and the incident trace.

None of this proves who fired a round. It shows who held which weapon and which rounds at a given time, and it makes unusual
patterns easy to see. A flag is a reason to look, never a conclusion.
"""
from datetime import timedelta
from statistics import median

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.audit.services import record
from apps.core.errors import field_error
from apps.logistics.models import StockLine

from .models import AmmoEvent, SoldierRounds, WeaponCustody

HEAVY_FACTOR = 3       # a soldier drew more than this many times the median draw of the soldiers in the same unit and ammunition line
HEAVY_MIN_ROUNDS = 100  # ...and at least this many rounds, so small numbers never raise a flag
LOSS_REPEAT = 2         # this many losses in the window
LOSS_WINDOW_DAYS = 90
OVERDUE_DAYS = 2        # an event still open this long after its date


def person_brief(p):
    return {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
            "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}}


def category_brief(line):
    c = line.category
    return {"code": c.code, "name_en": c.name_en, "name_so": c.name_so}


def event_out(e):
    return {"id": str(e.pk), "name": e.name, "event_date": e.event_date.isoformat(), "status": e.status,
            "org_unit": {"id": str(e.org_unit_id), "code": e.org_unit.code, "name_en": e.org_unit.name_en, "name_so": e.org_unit.name_so},
            "created_by": e.created_by_username, "closed_at": e.closed_at, "closed_by": e.closed_by_username}


def event_summary(event):
    """Per soldier and ammunition type: drawn under the event, handed back, fired, lost, and what is still outstanding."""
    rows = (SoldierRounds.objects.filter(event=event).order_by().values_list("personnel_id", "stock_line_id", "kind").annotate(s=Sum("delta")))
    per = {}
    for pid, lid, kind, s in rows:
        per.setdefault((pid, lid), {})[kind] = s
    from apps.personnel.models import Personnel
    people = {p.pk: p for p in Personnel.objects.filter(pk__in={k[0] for k in per}).select_related("rank")}
    lines = {l.pk: l for l in StockLine.objects.filter(pk__in={k[1] for k in per}).select_related("category")}
    soldiers, totals = [], {"issued": 0, "returned": 0, "expended": 0, "lost": 0, "outstanding": 0}
    for (pid, lid), k in sorted(per.items(), key=lambda kv: people[kv[0][0]].full_name):
        issued, returned, expended, lost = k.get("issue", 0), -k.get("return", 0), -k.get("expended", 0), -k.get("lost", 0)
        outstanding = issued - returned - expended - lost
        soldiers.append({"personnel": person_brief(people[pid]), "category": category_brief(lines[lid]), "issued": issued,
                         "returned": returned, "expended": expended, "lost": lost, "outstanding": outstanding})
        for key, val in (("issued", issued), ("returned", returned), ("expended", expended), ("lost", lost), ("outstanding", outstanding)):
            totals[key] += val
    return {"event": event_out(event), "soldiers": soldiers, "totals": totals,
            "balanced": all(s["outstanding"] == 0 for s in soldiers)}


def close_event(request, event):
    """Close an event once every round drawn under it is accounted for. Anything outstanding must first be returned, written off
    as expended or recorded as lost (with its authorisation), all under this event."""
    with transaction.atomic():
        locked = AmmoEvent.objects.select_for_update().select_related("org_unit").get(pk=event.pk)
        if locked.status != AmmoEvent.Status.OPEN:
            raise field_error("event", "event_closed")
        summary = event_summary(locked)
        if not summary["balanced"]:
            raise field_error("event", "event_not_reconciled", f"{summary['totals']['outstanding']} rounds are still outstanding.")
        locked.status = AmmoEvent.Status.CLOSED
        locked.closed_at = timezone.now()
        locked.closed_by_username = request.user.username
        locked.save(update_fields=["status", "closed_at", "closed_by_username"])
        record("weapon.ammo_event_close", request=request, entity_type="ammo_event", entity_id=locked.pk,
               metadata={"issued": summary["totals"]["issued"], "expended": summary["totals"]["expended"],
                         "returned": summary["totals"]["returned"], "lost": summary["totals"]["lost"]})
    return locked


def flags(rows_qs, events_qs, days=30):
    """Warning flags over the last `days` days. `rows_qs` is the soldier-rounds rows and `events_qs` the events the caller may see."""
    since = timezone.now() - timedelta(days=days)
    recent = rows_qs.filter(created_at__gte=since)
    from apps.personnel.models import Personnel

    def people_for(ids):
        return {p.pk: p for p in Personnel.objects.filter(pk__in=ids).select_related("rank", "org_unit")}

    # 1. rounds written off as expended with no training event behind them
    no_event = list(recent.filter(kind="expended", event__isnull=True).order_by().values_list("personnel_id", "stock_line_id")
                    .annotate(n=Count("pk"), rounds=Sum("delta")))
    # 2. drawing far more than the others in the same unit and ammunition line
    draws = list(recent.filter(kind="issue").order_by().values_list("personnel_id", "stock_line_id", "personnel__org_unit_id").annotate(total=Sum("delta")))
    by_group = {}
    for pid, lid, uid, total in draws:
        by_group.setdefault((lid, uid), []).append((pid, total))
    heavy = []
    for (lid, uid), items in by_group.items():
        if len(items) < 3:
            continue
        med = median(t for _, t in items)
        for pid, total in items:
            if total >= HEAVY_MIN_ROUNDS and total > HEAVY_FACTOR * med:
                heavy.append((pid, lid, total, med))
    # 3. repeated losses
    loss_since = timezone.now() - timedelta(days=LOSS_WINDOW_DAYS)
    losses = [(pid, lid, n, r) for pid, lid, n, r in rows_qs.filter(kind="lost", created_at__gte=loss_since).order_by()
              .values_list("personnel_id", "stock_line_id").annotate(n=Count("pk"), r=Sum("delta")) if n >= LOSS_REPEAT]
    # 3b. rounds drawn with no lot number, or with no training event, so the draw cannot be traced to a delivery or a purpose
    no_lot = list(recent.filter(kind="issue", lot="").order_by().values_list("personnel_id", "stock_line_id").annotate(n=Count("pk"), rounds=Sum("delta")))
    no_ev = list(recent.filter(kind="issue", event__isnull=True).order_by().values_list("personnel_id", "stock_line_id").annotate(n=Count("pk"), rounds=Sum("delta")))
    # 4. events left open
    overdue = list(events_qs.filter(status="open", event_date__lte=timezone.localdate() - timedelta(days=OVERDUE_DAYS)).select_related("org_unit"))

    every = [no_event, heavy, losses, no_lot, no_ev]
    people = people_for({x[0] for grp in every for x in grp})
    lines = {l.pk: l for l in StockLine.objects.filter(pk__in={x[1] for grp in every for x in grp}).select_related("category")}

    def entry(pid, lid, **extra):
        return {"personnel": person_brief(people[pid]), "category": category_brief(lines[lid]), **extra}
    return {
        "days": days,
        "expended_without_event": [entry(p, l, entries=n, rounds=-r) for p, l, n, r in no_event],
        "heavy_draw": [entry(p, l, rounds=t, unit_median=m) for p, l, t, m in heavy],
        "repeated_loss": [entry(p, l, entries=n, rounds=-r) for p, l, n, r in losses],
        "issued_without_lot": [entry(p, l, entries=n, rounds=r) for p, l, n, r in no_lot],
        "issued_without_event": [entry(p, l, entries=n, rounds=r) for p, l, n, r in no_ev],
        "events_overdue": [event_out(e) for e in overdue],
    }


def trace(request_user_scope_rows, assets_qs, serial, lot, at, txns_qs=None):
    """Who held the weapon and which rounds at time `at`, and who drew a given lot. Reports records only."""
    out = {"at": at, "weapon": None, "lot": None}
    if serial:
        asset = assets_qs.filter(identifier__iexact=serial).first()
        if asset is not None:
            chain = list(WeaponCustody.objects.filter(asset=asset).select_related("personnel__rank").order_by("-issued_at")[:20])
            holder = next((c for c in chain if c.issued_at <= at and (c.returned_at is None or c.returned_at > at)), None)
            held, drawn = [], []
            if holder is not None:
                p = holder.personnel
                rows = request_user_scope_rows.filter(personnel=p)
                per_line = rows.filter(created_at__lte=at).order_by().values_list("stock_line_id").annotate(s=Sum("delta"))
                lines = {l.pk: l for l in StockLine.objects.filter(pk__in=[x[0] for x in per_line]).select_related("category")}
                held = [{"category": category_brief(lines[lid]), "rounds": s} for lid, s in per_line if s]
                window = rows.filter(kind="issue", created_at__lte=at, created_at__gte=at - timedelta(days=7)).select_related("stock_line__category", "event")
                drawn = [{"category": category_brief(r.stock_line), "rounds": r.delta, "reference": r.reference, "lot": r.lot,
                          "event": r.event.name if r.event_id else None, "at": r.created_at} for r in window.order_by("-created_at")[:50]]
            out["weapon"] = {"serial": asset.identifier,
                             "holder_at_time": None if holder is None else {
                                 "personnel": person_brief(holder.personnel), "issued_at": holder.issued_at, "returned_at": holder.returned_at,
                                 "authority_ref": holder.authority_ref},
                             "rounds_held_at_time": held, "rounds_drawn_in_previous_7_days": drawn,
                             "custody_chain": [{"personnel": person_brief(c.personnel), "issued_at": c.issued_at, "returned_at": c.returned_at,
                                                "outcome": c.outcome} for c in chain]}
    if lot:
        rows = (request_user_scope_rows.filter(kind="issue", lot__iexact=lot)
                .select_related("personnel__rank", "personnel__org_unit", "stock_line__category", "event").order_by("-created_at")[:200])
        received, in_store = [], []
        if txns_qs is not None:
            tx = txns_qs.filter(lot__iexact=lot).select_related("stock_line__org_unit", "stock_line__category")
            received = [{"kind": x.kind, "rounds": x.delta, "reference": x.external_ref, "at": x.created_at,
                         "unit": {"code": x.stock_line.org_unit.code, "name_en": x.stock_line.org_unit.name_en, "name_so": x.stock_line.org_unit.name_so},
                         "category": category_brief(x.stock_line)} for x in tx.filter(kind__in=["opening", "receive"]).order_by("created_at")[:50]]
            per_line = tx.order_by().values_list("stock_line_id").annotate(s=Sum("delta"))
            lines = {l.pk: l for l in StockLine.objects.filter(pk__in=[x[0] for x in per_line]).select_related("org_unit", "category")}
            in_store = [{"unit": {"code": lines[lid].org_unit.code, "name_en": lines[lid].org_unit.name_en, "name_so": lines[lid].org_unit.name_so},
                         "category": category_brief(lines[lid]), "rounds": s} for lid, s in per_line if s > 0]
        out["lot"] = {"lot": lot, "received": received, "in_store": in_store, "issues": [{"personnel": person_brief(r.personnel),
                                              "unit": {"code": r.personnel.org_unit.code, "name_en": r.personnel.org_unit.name_en,
                                                       "name_so": r.personnel.org_unit.name_so},
                                              "category": category_brief(r.stock_line), "rounds": r.delta, "reference": r.reference,
                                              "event": r.event.name if r.event_id else None, "at": r.created_at} for r in rows]}
    return out
