"""Read-only aggregate analytics (2.0).

Design rules:
* Nothing here reads data the caller could not already read elsewhere. Every query is limited by a *scope object*,
  which answers "which rows of this section may the caller see?" in exactly the way the module that owns the data does.
* Aggregates only: no person-level or asset-level rows are ever returned.
* Restricted logistics categories are excluded entirely (they keep their own, separately permissioned workflow).
* Integration clients get approved report content only and small cells withheld (see `protect`).
"""
import uuid
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from rest_framework.exceptions import NotFound

from apps.accounts import scope as acl
from apps.core.errors import field_error
from apps.logistics.models import Asset, StockLine
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel, PersonnelHistory
from apps.training.models import TrainingRecord
from apps.workflows.models import Submission

# analytics section -> the existing permission that already governs that data
SECTION_PERMISSION = {
    "personnel": "personnel.view",
    "reports": "reports.summary",
    "logistics": "logistics.report",
    "training": "training.report",
}
SECTIONS = tuple(SECTION_PERMISSION)
PIPELINE_PERMISSION = "reports.view"  # workflow-state metrics need more than "approved summaries"
MAX_ROWS = 5000


# ---------------------------------------------------------------------------------------------------- scopes
class UserScope:
    """What a signed-in user may see: exactly their existing scoped permissions."""

    kind = "user"
    min_cell = 0

    def __init__(self, user):
        self.user = user

    def sections(self):
        return [s for s in SECTIONS if acl.has_anywhere(self.user, SECTION_PERMISSION[s])]

    def q(self, section, prefix, code=None):
        """Q limiting rows to units covered by the section's permission; None means 'nothing'."""
        if section not in self.sections():
            return None
        return acl.unit_scope_q(self.user, code or SECTION_PERMISSION[section], prefix)

    def can_see_unit(self, unit):
        return any(acl.can(self.user, SECTION_PERMISSION[s], unit=unit) for s in self.sections())

    def default_unit(self):
        return OrganizationalUnit.objects.filter(level="headquarters").first()

    def pipeline_q(self, prefix):
        return acl.unit_scope_q(self.user, PIPELINE_PERMISSION, prefix)


class ClientScope:
    """What an integration client may see: its sections, inside its unit subtree, aggregates of approved content only."""

    kind = "client"

    def __init__(self, client, min_cell):
        self.client = client
        self.min_cell = min_cell

    def sections(self):
        return [s for s in SECTIONS if s in (self.client.scopes or [])]

    def q(self, section, prefix, code=None):
        if section not in self.sections():
            return None
        return Q(**{f"{prefix}path__startswith": self.client.org_unit.path})

    def can_see_unit(self, unit):
        return unit.path.startswith(self.client.org_unit.path)

    def default_unit(self):
        return self.client.org_unit

    def pipeline_q(self, prefix):
        return None  # clients never see workflow-state (unapproved) metrics


# ------------------------------------------------------------------------------------------------ parameters
def parse_date(value, name):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise field_error(name, "invalid_date", "Invalid date.")


def parse_filters(params, scope_obj):
    """Validate ?from=&to=&unit= . A unit the caller cannot see behaves exactly like one that does not exist."""
    start, end = parse_date(params.get("from"), "from"), parse_date(params.get("to"), "to")
    if start and end and end < start:
        raise field_error("to", "date_range_invalid", "End is before start.")
    unit = None
    raw = params.get("unit")
    if raw:
        try:
            pk = uuid.UUID(raw)
        except ValueError:
            raise field_error("unit", "invalid_id", "Invalid identifier.")
        unit = OrganizationalUnit.objects.filter(pk=pk).first()
        if unit is None or not scope_obj.can_see_unit(unit):
            raise NotFound()
    return {"from": start, "to": end, "unit": unit}


def _limit(q, prefix, unit):
    if q is None or unit is None:
        return q
    return q & Q(**{f"{prefix}path__startswith": unit.path})


def _window(f):
    """Default time-series window: the last 12 whole months."""
    today = timezone.localdate()
    start = f["from"] or (today.replace(day=1) - timedelta(days=335)).replace(day=1)
    return start, f["to"] or today


# -------------------------------------------------------------------------------------- small-cell protection
def protect(rows, min_cell, key="count"):
    """Wrap a distribution as {total, rows, suppressed}. With min_cell > 0, cells below it are withheld, and the
    total is withheld too when anything was (otherwise total minus the shown cells would reveal them). A lone
    suppressed cell also hides the next-smallest, so it cannot be recovered by subtraction."""
    rows = [dict(r) for r in rows]
    total = sum(r[key] for r in rows)
    if min_cell <= 0:
        return {"total": total, "rows": rows, "suppressed": False}
    low = [r for r in rows if r[key] < min_cell]
    if low:
        rest = sorted((r for r in rows if r[key] >= min_cell), key=lambda r: r[key])
        if len(low) == 1 and rest:
            low.append(rest[0])
        for r in low:
            r[key] = None
    return {"total": None if low else total, "rows": rows, "suppressed": bool(low)}


def _month(d):
    return d.strftime("%Y-%m") if d else None


# ----------------------------------------------------------------------------------------------- personnel
def personnel(s, f):
    q = s.q("personnel", "org_unit__")
    if q is None:
        return None
    people = Personnel.objects.filter(_limit(q, "org_unit__", f["unit"]))
    by_status = people.values("status").order_by("status").annotate(count=Count("id"))
    by_rank = (people.values("rank__code", "rank__name_en", "rank__name_so", "rank__sort_order")
               .order_by("rank__sort_order").annotate(count=Count("id")))
    by_branch = people.values("branch__code", "branch__name_en", "branch__name_so").order_by("branch__code").annotate(count=Count("id"))
    paths = list(people.values("org_unit__path").order_by("org_unit__path").annotate(count=Count("id")))

    base = f["unit"] or s.default_unit()
    base_path = base.path if base else "/"
    here, children = 0, defaultdict(int)
    for row in paths:
        path = row["org_unit__path"]
        if not path.startswith(base_path):
            continue
        rest = path[len(base_path):].strip("/")
        if not rest:
            here += row["count"]
        else:
            children[base_path + rest.split("/")[0] + "/"] += row["count"]
    names = {u.path: u for u in OrganizationalUnit.objects.filter(path__in=list(children))}
    child_rows = [{"unit": {"id": str(names[p].pk), "code": names[p].code, "name_en": names[p].name_en,
                            "name_so": names[p].name_so, "level": names[p].level}, "count": n}
                  for p, n in sorted(children.items()) if p in names]

    start, end = _window(f)
    hist_q = _limit(s.q("personnel", "personnel__org_unit__"), "personnel__org_unit__", f["unit"])
    hist = (PersonnelHistory.objects.filter(hist_q, effective_date__gte=start, effective_date__lte=end)
            .annotate(m=TruncMonth("effective_date")).values("m", "field").order_by("m", "field").annotate(count=Count("id")))
    changes = [{"month": _month(r["m"]), "field": r["field"], "count": r["count"]} for r in hist]
    return {
        "focus": {"unit": str(base.pk) if base else None, "directly_in_unit": here},
        "by_status": protect([{"status": r["status"], "count": r["count"]} for r in by_status], s.min_cell),
        "by_rank": protect([{"code": r["rank__code"], "name_en": r["rank__name_en"], "name_so": r["rank__name_so"],
                             "count": r["count"]} for r in by_rank], s.min_cell),
        "by_branch": protect([{"code": r["branch__code"], "name_en": r["branch__name_en"], "name_so": r["branch__name_so"],
                               "count": r["count"]} for r in by_branch], s.min_cell),
        "by_child_unit": protect(child_rows, s.min_cell),
        "changes_by_month": protect(changes, s.min_cell),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
    }


# ------------------------------------------------------------------------------------------------- reports
def reports(s, f):
    q = s.q("reports", "org_unit__")
    if q is None:
        return None
    start, end = _window(f)
    base = Submission.objects.filter(_limit(q, "org_unit__", f["unit"]))
    approved = base.filter(status="approved", decided_at__date__gte=start, decided_at__date__lte=end)
    by_type = (approved.values("report_type__code", "report_type__name_en", "report_type__name_so")
               .order_by("report_type__code").annotate(count=Count("id")))
    by_month = approved.annotate(m=TruncMonth("decided_at")).values("m").order_by("m").annotate(count=Count("id"))
    out = {
        "approved_by_type": protect([{"code": r["report_type__code"], "name_en": r["report_type__name_en"],
                                      "name_so": r["report_type__name_so"], "count": r["count"]} for r in by_type], s.min_cell),
        "approved_by_month": protect([{"month": _month(r["m"]), "count": r["count"]} for r in by_month], s.min_cell),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
    }
    pq = s.pipeline_q("org_unit__")  # users with reports.view only: workflow-state metrics
    if pq is not None:
        pipe = Submission.objects.filter(_limit(pq, "org_unit__", f["unit"]), updated_at__date__gte=start, updated_at__date__lte=end)
        status_rows = pipe.values("status").order_by("status").annotate(count=Count("id"))
        spans = list(pipe.filter(decided_at__isnull=False, submitted_at__isnull=False)
                     .values_list("submitted_at", "decided_at")[:MAX_ROWS])
        hours = sorted(((d - b).total_seconds() / 3600) for b, d in spans if d >= b)
        out["pipeline"] = {
            "by_status": protect([{"status": r["status"], "count": r["count"]} for r in status_rows], 0),
            "decided_sample": len(hours),
            "turnaround_hours": {"median": round(hours[len(hours) // 2], 1) if hours else None,
                                 "mean": round(sum(hours) / len(hours), 1) if hours else None},
        }
    return out


# ----------------------------------------------------------------------------------------------- logistics
def logistics(s, f):
    q = s.q("logistics", "org_unit__")
    if q is None:
        return None
    q = _limit(q, "org_unit__", f["unit"]) & Q(category__restricted=False)  # restricted equipment is never aggregated here
    stock = StockLine.objects.filter(q)
    by_cat = (stock.values("category__code", "category__name_en", "category__name_so").order_by("category__code")
              .annotate(total=Sum("quantity"), lines=Count("id")))
    low = stock.filter(reorder_level__gt=0, quantity__lte=F("reorder_level")).count()
    assets = Asset.objects.filter(q).values("status").order_by("status").annotate(count=Count("id"))
    return {
        "stock_by_category": protect([{"code": r["category__code"], "name_en": r["category__name_en"],
                                       "name_so": r["category__name_so"], "count": r["total"] or 0, "lines": r["lines"]}
                                      for r in by_cat], s.min_cell),
        "low_stock_lines": low if s.min_cell <= 0 or low >= s.min_cell else None,
        "assets_by_status": protect([{"status": r["status"], "count": r["count"]} for r in assets], s.min_cell),
        "excludes_restricted": True,
    }


# ------------------------------------------------------------------------------------------------- training
def training(s, f):
    q = s.q("training", "personnel__org_unit__")
    if q is None:
        return None
    start, end = _window(f)
    recs = TrainingRecord.objects.filter(_limit(q, "personnel__org_unit__", f["unit"]), start_date__gte=start, start_date__lte=end)
    rows = (recs.values("course__code", "course__name_en", "course__name_so", "status").order_by("course__code")
            .annotate(count=Count("id")))
    per = {}
    for r in rows:
        c = per.setdefault(r["course__code"], {"code": r["course__code"], "name_en": r["course__name_en"],
                                               "name_so": r["course__name_so"], "statuses": {}})
        c["statuses"][r["status"]] = r["count"]
    courses = []
    for c in per.values():
        total = sum(c["statuses"].values())
        counted = total - c["statuses"].get("withdrawn", 0)  # withdrawn people are not part of the rate
        done = c["statuses"].get("completed", 0)
        courses.append({**{k: c[k] for k in ("code", "name_en", "name_so")}, "count": total, "statuses": c["statuses"],
                        "completion_rate": round(done / counted, 3) if counted else None})
    shown = protect(courses, s.min_cell)
    if s.min_cell > 0:  # per-status breakdowns of a small course would leak the withheld count
        for r in shown["rows"]:
            if r["count"] is None:
                r["statuses"], r["completion_rate"] = None, None
    done_m = (recs.filter(status="completed", completed_on__isnull=False).annotate(m=TruncMonth("completed_on"))
              .values("m").order_by("m").annotate(count=Count("id")))
    return {"by_course": shown,
            "completions_by_month": protect([{"month": _month(r["m"]), "count": r["count"]} for r in done_m], s.min_cell),
            "period": {"from": start.isoformat(), "to": end.isoformat()}}


COMPUTE = {"personnel": personnel, "reports": reports, "logistics": logistics, "training": training}


def compute(s, section, filters):
    """Returns the section's data, or None when the scope does not allow that section at all."""
    return COMPUTE[section](s, filters)
