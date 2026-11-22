"""Personnel report: strength and movement for a period, by unit, region and rank, for the caller's jurisdiction.

Counts only. No names, service numbers or any personal data leave this endpoint (the row-level CSV remains the controlled
`/personnel/export/`, which needs a fresh MFA code). Scope is the caller's `personnel.view` units, so a station commander gets the
station, a regional commander the region and headquarters everything. Reading it is audited with the number of units shown.

Definitions (written here so the figures can be explained to the ministry):
* on file  = every record in scope, whatever its status.   * serving = on file minus retired, discharged and died.
* joined   = records created in the period.                * left = status changed to retired, discharged or died, effective in the period.
* promoted = rank changes effective in the period (the first rank given at registration is not a promotion).
* A unit's row counts the people recorded directly in that unit; a region's row adds everything beneath it.
"""
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.core.errors import field_error
from apps.core.orgpaths import region_id
from apps.organization.models import OrganizationalUnit
from apps.vehicles.views import _uid, _unit_brief

from .models import Personnel, PersonnelHistory
from .services import NOT_SERVING

STATUSES = [s.value for s in Personnel.Status]
LEAVING = [s.value for s in NOT_SERVING]
MAX_DAYS = 366


def _period(p):
    today = timezone.localdate()
    try:
        d1 = date.fromisoformat(p["to"]) if p.get("to") else today
        d0 = date.fromisoformat(p["from"]) if p.get("from") else d1 - timedelta(days=29)
    except ValueError:
        raise field_error("from", "invalid_date", "Use YYYY-MM-DD.")
    if d1 < d0:
        raise field_error("to", "before_from", "The end date cannot be before the start date.")
    if (d1 - d0).days > MAX_DAYS:
        raise field_error("to", "range_too_long", "Choose a period of at most one year.")
    return d0, d1


def _zero():
    return {"on_file": 0, "serving": 0, **{s: 0 for s in STATUSES}, "joined": 0, "left": 0, "promoted": 0}


def build(user, unit, d0, d1):
    q = scope.unit_scope_q(user, "personnel.view", "org_unit__")
    if q is None:
        return None
    people = Personnel.objects.filter(q)
    if unit is not None:
        people = people.filter(org_unit__path__startswith=unit.path)
    tz = timezone.get_current_timezone()
    since = timezone.make_aware(datetime.combine(d0, time.min), tz)
    until = timezone.make_aware(datetime.combine(d1, time.min), tz) + timedelta(days=1)

    rows = {}
    def row(uid):
        return rows.setdefault(uid, _zero())
    for r in people.values("org_unit_id", "status").annotate(n=Count("id")):
        x = row(r["org_unit_id"])
        x[r["status"]] += r["n"]
        x["on_file"] += r["n"]
        if r["status"] not in LEAVING:
            x["serving"] += r["n"]
    for r in people.filter(created_at__gte=since, created_at__lt=until).values("org_unit_id").annotate(n=Count("id")):
        row(r["org_unit_id"])["joined"] += r["n"]
    hist = PersonnelHistory.objects.filter(personnel__in=people, effective_date__gte=d0, effective_date__lte=d1)
    for r in hist.filter(field="status", new_ref__in=LEAVING).values("personnel__org_unit_id").annotate(n=Count("id")):
        row(r["personnel__org_unit_id"])["left"] += r["n"]
    for r in hist.filter(field="rank").exclude(old_ref="").values("personnel__org_unit_id").annotate(n=Count("id")):
        row(r["personnel__org_unit_id"])["promoted"] += r["n"]

    units = {u.pk: u for u in OrganizationalUnit.objects.filter(pk__in=list(rows))}
    out_units, regions = [], {}
    keys = [k for k in _zero()]
    for uid, x in rows.items():
        u = units.get(uid)
        if u is None:
            continue
        rid = region_id(u.path) or ""
        out_units.append({"unit": _unit_brief(u), "path": u.path, "_rid": rid, **x})
        g = regions.setdefault(rid, _zero())
        for k in keys:
            g[k] += x[k]
    names = {str(u.pk): u for u in OrganizationalUnit.objects.filter(pk__in=[r for r in regions if r])}
    out_regions = [{"unit": _unit_brief(names.get(rid)), **g} for rid, g in regions.items()]
    totals = _zero()
    for g in regions.values():
        for k in keys:
            totals[k] += g[k]
    ranks = [{"name_en": r["rank__name_en"], "name_so": r["rank__name_so"], "on_file": r["n"], "serving": r["s"]} for r in
             people.values("rank__name_en", "rank__name_so", "rank__sort_order").annotate(n=Count("id"), s=Count("id", filter=~Q(status__in=LEAVING)))
             .order_by("-rank__sort_order")]
    out_units.sort(key=lambda r: r["path"])
    for r in out_units:
        del r["path"]
        r["region"] = _unit_brief(names.get(r.pop("_rid")))
    return {"from": d0, "to": d1, "as_of": timezone.now(), "totals": totals, "regions": sorted(out_regions, key=lambda r: (r["unit"] or {}).get("code", "")),
            "units": out_units, "ranks": ranks}


class PersonnelReportViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("personnel.view", "any")}

    def list(self, request):
        """?from=YYYY-MM-DD&to=YYYY-MM-DD (default the last 30 days) and optionally ?unit= for one unit and everything below it."""
        p = request.query_params
        unit = None
        if p.get("unit"):
            unit = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).first() if _uid(p["unit"]) else None
            if unit is None or not scope.can(request.user, "personnel.view", unit=unit):
                raise Http404
        d0, d1 = _period(p)
        data = build(request.user, unit, d0, d1)
        if data is None:
            raise Http404
        record_read(request, "personnel.read_report", entity_type="personnel_report", count=len(data["units"]))
        return Response(data)
