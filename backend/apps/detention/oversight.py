"""Custody oversight dashboard: what each station's detention unit is really doing, rolled up by district and region.

Read-only, built from the register and the facility records; nothing is stored. Scope: only stations inside the caller's
detention.view scope, so a station commander sees their station, a district chief the district, a regional commander the region and
headquarters everything. A facility record is shown with its real status (not verified / operational / out of use) because an
automatically created record is not proof that a jail works."""
from datetime import timedelta

from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.organization.models import OrganizationalUnit
from apps.vehicles.views import _uid

from datetime import date, datetime, time

from . import capacity as cap, cellrules, hierarchy
from .models import CustodyFacility, CustodyIncident, DetentionRecord as R
from .views import court_flags, overdue_q, review_hours

MAX_DAYS = 366


def _group(qs, key="org_unit_id"):
    return {row[key]: row["n"] for row in qs.values(key).annotate(n=Count("id"))}


def _brief(u):
    return None if u is None else {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}


def build(user, unit=None, days=30, since=None, until=None):
    """since/until (aware datetimes) set the period for admissions, releases and transfers; by default the last `days` days."""
    now = timezone.now()
    until = until or now
    since = since or (until - timedelta(days=days))
    q = scope.unit_scope_q(user, "detention.view")
    if q is None:
        return None
    units = OrganizationalUnit.objects.filter(q, active=True).select_related("unit_type")
    if unit is not None:
        units = units.filter(path__startswith=unit.path)
    has_jail = CustodyFacility.objects.filter(kind="jail_center").values("org_unit_id")
    stations = list(units.filter(Q(unit_type__code="POLICE_STATION") | Q(pk__in=has_jail)).order_by("path"))
    ids = [s.pk for s in stations]
    by_id = hierarchy.index()
    facs = list(CustodyFacility.objects.filter(kind="jail_center", org_unit_id__in=ids).order_by("name_en"))
    stats = cap.stats_for([f.pk for f in facs])
    fac_by_unit = {}
    for f in facs:
        fac_by_unit.setdefault(f.org_unit_id, []).append(f)

    reg = R.objects.filter(org_unit_id__in=ids).exclude(status="void")
    held_qs = reg.filter(status="in_custody")
    held = _group(held_qs)
    overdue = _group(reg.filter(overdue_q(now)))
    unplaced = _group(held_qs.filter(Q(facility__isnull=True) | ~Q(facility__status="operational") | Q(facility__active=False)))
    admitted = _group(reg.filter(booked_at__gte=since, booked_at__lt=until, transferred_from__isnull=True))
    received = _group(reg.filter(received_at__gte=since, received_at__lt=until))
    released = _group(reg.filter(status="released", ended_at__gte=since, ended_at__lt=until))
    transferred = _group(reg.filter(status="transferred", ended_at__gte=since, ended_at__lt=until))
    outcomes = {}
    for row in reg.filter(status__in=("released", "transferred"), ended_at__gte=since, ended_at__lt=until).values("org_unit_id", "outcome").annotate(n=Count("id")):
        outcomes.setdefault(row["org_unit_id"], {})[row["outcome"]] = row["n"]
    court_soon, remand_expired, hearing_passed = {}, {}, {}
    for r in held_qs.prefetch_related("hearings"):
        f = court_flags(r, now)
        for key, acc in (("court_soon", court_soon), ("remand_expired", remand_expired), ("hearing_passed", hearing_passed)):
            if f[key]:
                acc[r.org_unit_id] = acc.get(r.org_unit_id, 0) + 1
    open_incidents = _group(CustodyIncident.objects.filter(org_unit_id__in=ids, reviewed_at__isnull=True))
    incidents_period = _group(CustodyIncident.objects.filter(org_unit_id__in=ids, occurred_at__gte=since, occurred_at__lt=until))
    cell_flags = cellrules.flagged_counts(ids)
    incoming = _group(R.objects.filter(destination_unit_id__in=ids, status="transferred", outcome="transfer_station", received_as__isnull=True),
                      key="destination_unit_id")

    rows = []
    for st in stations:
        fl = fac_by_unit.get(st.pk, [])
        usable = [f for f in fl if f.usable]
        sums = [cap.summarise(f, stats[f.pk]) for f in usable]
        known = [s["capacity"] for s in sums if s["capacity"] is not None]
        capacity = sum(known) if known else None
        occupied_usable = sum(s["occupied"] for s in sums)
        if usable:
            state = "operational"
        elif any(f.status == "unverified" and f.active for f in fl):
            state = "unverified"
        elif fl:
            state = "out_of_use"
        else:
            state = "no_facility"
        region, district, _chain = hierarchy.lineage(st, by_id)
        n_held = held.get(st.pk, 0)
        rows.append({
            "unit": _brief(st), "region": _brief(region), "district": _brief(district), "facility_state": state,
            "facilities": [{"id": str(f.pk), "code": f.code, "name_en": f.name_en, "name_so": f.name_so, "status": f.status, "active": f.active, "usable": f.usable,
                            **cap.summarise(f, stats[f.pk])} for f in fl],
            "in_custody": n_held, "capacity": capacity, "available": None if capacity is None else max(capacity - occupied_usable, 0),
            "over_capacity": capacity is not None and occupied_usable > capacity, "overdue_reviews": overdue.get(st.pk, 0),
            "held_without_verified_facility": unplaced.get(st.pk, 0), "incoming": incoming.get(st.pk, 0),
            "admitted": admitted.get(st.pk, 0), "received": received.get(st.pk, 0), "released": released.get(st.pk, 0), "transferred_out": transferred.get(st.pk, 0),
            "outcomes": outcomes.get(st.pk, {}), "court_soon": court_soon.get(st.pk, 0), "remand_expired": remand_expired.get(st.pk, 0),
            "hearing_passed": hearing_passed.get(st.pk, 0), "open_incidents": open_incidents.get(st.pk, 0), "incidents": incidents_period.get(st.pk, 0),
            "cell_flags": cell_flags.get(st.pk, 0)})

    def roll(items):
        t = {"stations": len(items), "operational": 0, "unverified": 0, "out_of_use": 0, "no_facility": 0, "in_custody": 0, "overdue_reviews": 0,
             "capacity": 0, "available": 0, "stations_with_known_capacity": 0, "over_capacity_stations": 0, "held_without_verified_facility": 0,
             "incoming": 0, "admitted": 0, "received": 0, "released": 0, "transferred_out": 0,
             "court_soon": 0, "remand_expired": 0, "hearing_passed": 0, "open_incidents": 0, "incidents": 0, "cell_flags": 0}
        for r in items:
            t[r["facility_state"]] += 1
            for k in ("in_custody", "overdue_reviews", "held_without_verified_facility", "incoming", "admitted", "received", "released", "transferred_out",
                      "court_soon", "remand_expired", "hearing_passed", "open_incidents", "incidents", "cell_flags"):
                t[k] += r[k]
            if r["capacity"] is not None:
                t["capacity"] += r["capacity"]
                t["available"] += r["available"]
                t["stations_with_known_capacity"] += 1
            t["over_capacity_stations"] += bool(r["over_capacity"])
        return t

    def groups(key):
        acc = {}
        for r in rows:
            g = r[key]
            acc.setdefault(g["id"] if g else "", {"unit": g, "rows": []})["rows"].append(r)
        return [{"unit": v["unit"], **roll(v["rows"])} for v in acc.values()]

    return {"as_of": now, "since": since, "until": until, "days": days, "review_hours": review_hours(), "totals": roll(rows), "regions": groups("region"),
            "districts": [g for g in groups("district") if g["unit"]], "stations_without_district": sum(1 for r in rows if r["district"] is None),
            "stations": rows}


class DetentionOversightViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("detention.view", "any"), "report": ("detention.view", "any"), "hierarchy": ("detention.verify", "any")}

    def list(self, request):
        p = request.query_params
        unit = None
        if p.get("unit"):
            unit = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).first() if _uid(p["unit"]) else None
            if unit is None or not scope.can(request.user, "detention.view", unit=unit):
                raise Http404
        try:
            days = min(max(int(p.get("days", 30)), 1), MAX_DAYS)
        except ValueError:
            days = 30
        data = build(request.user, unit, days)
        if data is None:
            raise Http404
        record_read(request, "detention.read_oversight", entity_type="detention_oversight", count=len(data["stations"]))
        return Response(data)

    @action(detail=False, methods=["get"])
    def report(self, request):
        """Custody report for a period (?from=YYYY-MM-DD&to=YYYY-MM-DD, default the last 30 days) for the caller's stations, or one unit and
        everything below it (?unit=). Same figures as the dashboard, with the outcome of each release or transfer. Audited."""
        p = request.query_params
        unit = None
        if p.get("unit"):
            unit = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).first() if _uid(p["unit"]) else None
            if unit is None or not scope.can(request.user, "detention.view", unit=unit):
                raise Http404
        tz = timezone.get_current_timezone()
        try:
            since = timezone.make_aware(datetime.combine(date.fromisoformat(p["from"]), time.min), tz) if p.get("from") else None
            until = timezone.make_aware(datetime.combine(date.fromisoformat(p["to"]), time.min), tz) + timedelta(days=1) if p.get("to") else None
        except ValueError:
            from apps.core.errors import field_error
            raise field_error("from", "invalid_date", "Use YYYY-MM-DD.")
        if since and until and since >= until:
            from apps.core.errors import field_error
            raise field_error("to", "before_from", "The end date cannot be before the start date.")
        data = build(request.user, unit, 30, since, until)
        if data is None:
            raise Http404
        record_read(request, "detention.read_report", entity_type="detention_report", count=len(data["stations"]))
        return Response(data)

    @action(detail=False, methods=["get"])
    def hierarchy(self, request):
        """Hierarchy and custody-setup findings for the whole chart. Needs detention.verify as a global grant (headquarters)."""
        if not scope.can(request.user, "detention.verify"):
            raise Http404
        record_read(request, "detention.read_hierarchy_check", entity_type="detention_oversight")
        return Response(hierarchy.check())
