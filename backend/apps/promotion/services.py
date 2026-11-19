"""Promotion eligibility rules, shared by the eligibility list and by proposals, so a proposal can never be made for someone
the list would not show as eligible."""
from datetime import date

from django.utils import timezone

from apps.personnel.models import PersonnelHistory
from apps.ranks.models import Rank

from .models import PromotionRule

RETIRED_FROM = 1000  # retired ranks are parked at 1000+ and never compared (see Rank.sort_order)
BLOCKING_STATUS = {"suspended", "jailed"}
STATES = ("eligible", "not_yet", "blocked", "no_rule", "no_next")


def months_between(start: date, end: date) -> int:
    """Whole months from start to end (never negative)."""
    m = (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)
    return max(0, m)


def _next_rank(rule, rank, ranks_by_branch):
    """The rank this one is promoted to: the one named in the rule, else the very next rank up in the same service.
    It is never skipped to a later rank: if the next one is not approved yet, nobody can be promoted into it."""
    if rule.next_rank_id:
        return rule.next_rank
    ups = [r for r in ranks_by_branch.get(rank.branch_id, []) if rank.sort_order < r.sort_order < RETIRED_FROM]
    return min(ups, key=lambda r: r.sort_order) if ups else None


def _usable(nxt, rank):
    return nxt is not None and nxt.active and nxt.approval_status == "approved" and nxt.branch_id == rank.branch_id


def evaluate(people, today=None):
    """One row per person (the Personnel objects must have `rank` and `org_unit` loaded):
    {person, rule, next_rank, rank_since, since_source, months, required, months_left, state}."""
    today = today or timezone.localdate()
    people = list(people)
    rules = {r.rank_id: r for r in PromotionRule.objects.filter(active=True).select_related("next_rank")}
    ranks_by_branch = {}
    for r in Rank.objects.filter(active=True, sort_order__lt=RETIRED_FROM):
        ranks_by_branch.setdefault(r.branch_id, []).append(r)
    since = {}
    for h in PersonnelHistory.objects.filter(personnel_id__in=[p.pk for p in people], field="rank").order_by("-effective_date", "-recorded_at"):
        since.setdefault(h.personnel_id, (h.effective_date, bool(h.old_ref)))  # latest rank entry per person; no old rank = first entry
    out = []
    for p in people:
        rule = rules.get(p.rank_id)
        start, changed = since.get(p.pk) or (p.created_at.date(), False)
        months = months_between(start, today)
        nxt = _next_rank(rule, p.rank, ranks_by_branch) if rule else None
        if rule is None:
            state = "no_rule"
        elif p.status in BLOCKING_STATUS:
            state = "blocked"
        elif months < rule.min_months:
            state = "not_yet"
        elif not _usable(nxt, p.rank):
            state = "no_next"
        else:
            state = "eligible"
        out.append({"person": p, "rule": rule, "next_rank": nxt, "rank_since": start, "since_source": "history" if changed else "record",
                    "months": months, "required": rule.min_months if rule else None,
                    "months_left": max(0, rule.min_months - months) if rule else None, "state": state})
    return out
