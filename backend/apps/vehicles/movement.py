"""Daily movement report: for one calendar day, what each vehicle in the caller's scope did, from its recorded positions.

Per vehicle: number of positions, first and last position, distance travelled (same drift rule as the route trail), and for each zone the
minutes spent inside and the number of entries and exits. Minutes between two fixes count as inside only when the earlier fix was inside
and the gap is at most GAP_CAP minutes; a longer silence is not counted either way. Vehicles with no position that day are listed as not
reporting. The day runs midnight to midnight in REPORT_TIME_ZONE (default UTC). It is an estimate from reported points, not an odometer.
"""
import csv
import io
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

from apps.accounts import scope

from . import geofences as gf
from .models import Geofence, GeofenceEvent, Vehicle, VehiclePosition

GAP_CAP = timedelta(minutes=30)


def report_tz():
    try:
        return ZoneInfo(getattr(settings, "REPORT_TIME_ZONE", "UTC") or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def day_bounds(day):
    tz = report_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start, end, tz


class _Day:
    """Running totals for one vehicle, fed its positions oldest first."""

    def __init__(self, fences):
        self.n, self.first, self.last, self.dist, self.anchor, self.prev = 0, None, None, 0.0, None, None
        self.minutes = {f.pk: 0.0 for f in fences}

    def feed(self, fences, lat, lon, at, acc, place):
        self.n += 1
        if self.first is None:
            self.first = (at, lat, lon, place)
        self.last = (at, lat, lon, place)
        if self.anchor is None:
            self.anchor = (lat, lon)
        else:
            step = gf.haversine_km(self.anchor[0], self.anchor[1], lat, lon)
            if step >= gf.MIN_STEP_KM:
                self.dist += step
                self.anchor = (lat, lon)
        here = {f.pk: (gf.contains(f, lat, lon) if gf.usable(f, acc) else None) for f in fences}
        if self.prev is not None:
            prev_at, prev_in = self.prev
            gap = at - prev_at
            if gap <= GAP_CAP:
                for f in fences:
                    if prev_in[f.pk] is True:
                        self.minutes[f.pk] += gap.total_seconds() / 60
        self.prev = (at, here)


def build_daily_report(user, day):
    start, end, tz = day_bounds(day)
    out = {"date": day.isoformat(), "timezone": str(tz), "summary": {"vehicles_in_scope": 0, "vehicles_reporting": 0, "vehicles_not_reporting": 0,
                                                                    "positions": 0, "distance_km": 0.0, "zone_events": 0},
           "vehicles": [], "not_reporting": []}
    q_veh = scope.unit_scope_q(user, "vehicles.view", "org_unit__")
    if q_veh is None:
        return out
    vehicles = {v.pk: v for v in Vehicle.objects.filter(q_veh).exclude(status="decommissioned").select_related("org_unit")}
    q_pos = scope.unit_scope_q(user, "vehicles.view", "vehicle__org_unit__")

    events = list(GeofenceEvent.objects.filter(q_pos, occurred_at__gte=start, occurred_at__lt=end).values_list("vehicle_id", "geofence_id", "kind"))
    fence_ids = {e[1] for e in events}
    fences = list(Geofence.objects.filter(active=True) | Geofence.objects.filter(pk__in=fence_ids))
    fences.sort(key=lambda f: f.name.lower())
    counts = {}
    for vid, fid, kind in events:
        counts.setdefault(vid, {}).setdefault(fid, {"enter": 0, "exit": 0})[kind] += 1

    days = {}
    rows = (VehiclePosition.objects.filter(q_pos, voided_at__isnull=True, recorded_at__gte=start, recorded_at__lt=end)
            .exclude(vehicle__status="decommissioned").order_by("vehicle_id", "recorded_at", "id")
            .values_list("vehicle_id", "latitude", "longitude", "recorded_at", "accuracy_m", "place").iterator(chunk_size=5000))
    for vid, lat, lon, at, acc, place in rows:
        days.setdefault(vid, _Day(fences)).feed(fences, float(lat), float(lon), at, acc, place)

    def stamp(t):
        return t.astimezone(tz).isoformat()

    for vid in sorted(days, key=lambda k: vehicles[k].vehicle_id if k in vehicles else ""):
        v, d = vehicles.get(vid), days[vid]
        if v is None:
            continue
        zones = []
        for f in fences:
            c = counts.get(vid, {}).get(f.pk, {"enter": 0, "exit": 0})
            mins = int(round(d.minutes[f.pk]))
            if mins or c["enter"] or c["exit"]:
                zones.append({"geofence_id": str(f.pk), "name": f.name, "minutes_inside": mins, "entered": c["enter"], "left": c["exit"]})
        out["vehicles"].append({
            "vehicle": {"id": str(v.pk), "vehicle_id": v.vehicle_id, "plate": v.plate, "make": v.make, "model": v.model},
            "unit": v.org_unit.code if v.org_unit_id else "", "positions": d.n, "distance_km": round(d.dist, 2),
            "first_at": stamp(d.first[0]), "first_latitude": f"{d.first[1]:.6f}", "first_longitude": f"{d.first[2]:.6f}", "first_place": d.first[3],
            "last_at": stamp(d.last[0]), "last_latitude": f"{d.last[1]:.6f}", "last_longitude": f"{d.last[2]:.6f}", "last_place": d.last[3],
            "zones": zones})
    for v in sorted(vehicles.values(), key=lambda x: x.vehicle_id):
        if v.pk not in days:
            out["not_reporting"].append({"id": str(v.pk), "vehicle_id": v.vehicle_id, "plate": v.plate, "make": v.make, "model": v.model,
                                         "unit": v.org_unit.code if v.org_unit_id else ""})
    s = out["summary"]
    s.update(vehicles_in_scope=len(vehicles), vehicles_reporting=len(out["vehicles"]), vehicles_not_reporting=len(out["not_reporting"]),
             positions=sum(x["positions"] for x in out["vehicles"]), distance_km=round(sum(x["distance_km"] for x in out["vehicles"]), 2),
             zone_events=len(events))
    return out


def safe_cell(value):
    """Spreadsheet formula injection: a cell starting with = + - @ would run as a formula when the file is opened."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def report_csv(report):
    """The report as CSV bytes (UTF-8 with BOM so Excel reads Somali text), one row per vehicle in scope, reporting or not."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "timezone", "vehicle_id", "plate", "make", "model", "unit", "positions", "distance_km", "first_at", "first_place",
                "last_at", "last_place", "zones"])
    for x in report["vehicles"]:
        v = x["vehicle"]
        zones = "; ".join(f"{z['name']}: {z['minutes_inside']} min, in {z['entered']}, out {z['left']}" for z in x["zones"])
        w.writerow([report["date"], report["timezone"], v["vehicle_id"], safe_cell(v["plate"]), safe_cell(v["make"]), safe_cell(v["model"]), x["unit"],
                    x["positions"], x["distance_km"], x["first_at"], safe_cell(x["first_place"]), x["last_at"], safe_cell(x["last_place"]), safe_cell(zones)])
    for v in report["not_reporting"]:
        w.writerow([report["date"], report["timezone"], v["vehicle_id"], safe_cell(v["plate"]), safe_cell(v["make"]), safe_cell(v["model"]), v["unit"],
                    0, "", "", "", "", "", ""])
    return out.getvalue().encode("utf-8-sig")
