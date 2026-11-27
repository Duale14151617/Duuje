"""Vehicle position reports (manual or from a phone). No tracker hardware and no outside service: an officer types a position in, or
a phone sends its own location from the browser. Reads need vehicles.view, reports need vehicles.position (both narrowed to the
caller's unit scope); rows are voided with a reason, never deleted; every write is audited."""
import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Q, Subquery
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.accounts.stepup import require_fresh_mfa
from apps.audit.services import client_ip, record, record_read
from apps.core.concurrency import VersionConflict, require_version
from apps.core.errors import field_error
from apps.core.negotiation import IgnoreNegotiation
from apps.core.params import json_body

from . import services as svc
from . import geofences
from .models import Geofence, GeofenceEvent, Vehicle, VehiclePosition, VehicleTracker, VehicleTrip
from .views import _Page, _uid

P = VehiclePosition
STALE_HOURS = 24
MIN_GAP_SECONDS = 20  # one phone cannot flood a vehicle's history
TRAIL_MAX = 500  # points in one route
TRAIL_MIN_STEP_KM = geofences.MIN_STEP_KM  # moves shorter than this are GPS drift, not travel


def _coord(d, name, low, high):
    v = d.get(name)
    if v in (None, ""):
        raise field_error(name, "required", "This field is required.")
    try:
        x = Decimal(str(v).strip()).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        raise field_error(name, "invalid_number", "Enter a number such as 8.405500.")
    if not (low <= x <= high):
        raise field_error(name, "out_of_range", f"Must be between {low} and {high}.")
    return x


def _when(value, name):
    if value in (None, ""):
        return timezone.now()
    dt = parse_datetime(str(value))
    if dt is None:
        raise field_error(name, "invalid_datetime", "Use a date and time such as 2026-11-16T08:30.")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _actor(request):
    return getattr(getattr(request, "user", None), "username", "") or ""


@transaction.atomic
def report_position(request, vehicle, d):
    v = Vehicle.objects.select_for_update().get(pk=vehicle.pk)
    if v.status == "decommissioned":
        raise field_error("vehicle", "decommissioned", "A decommissioned vehicle is read-only.")
    source = d.get("source") or P.Source.MANUAL
    if source not in (P.Source.MANUAL, P.Source.PHONE):  # "tracker" is reserved for the key-authenticated feed
        raise field_error("source", "invalid_choice", "Choose typed in or phone.")
    lat, lon = _coord(d, "latitude", Decimal("-90"), Decimal("90")), _coord(d, "longitude", Decimal("-180"), Decimal("180"))
    at = _when(d.get("recorded_at"), "recorded_at")
    now = timezone.now()
    if at > now + timedelta(minutes=5):
        raise field_error("recorded_at", "future", "A position cannot be in the future.")
    acc = None
    if d.get("accuracy_m") not in (None, ""):
        try:
            acc = int(round(float(d["accuracy_m"])))
        except (TypeError, ValueError):
            raise field_error("accuracy_m", "invalid_number", "Enter a whole number of metres.")
        if acc < 0 or acc > 1_000_000:
            raise field_error("accuracy_m", "invalid_number", "Enter a whole number of metres.")
    if P.objects.filter(vehicle=v, created_by_username=_actor(request), created_at__gte=now - timedelta(seconds=MIN_GAP_SECONDS)).exists():
        raise field_error("vehicle", "too_frequent", f"Wait {MIN_GAP_SECONDS} seconds between reports for the same vehicle.")
    trip = VehicleTrip.objects.filter(vehicle=v, state="open").first()
    row = P.objects.create(vehicle=v, trip=trip, latitude=lat, longitude=lon, accuracy_m=acc, place=svc._text(d, "place", 150), source=source,
                           recorded_at=at, note=svc._text(d, "note", 200), created_by_username=_actor(request))
    geofences.evaluate_position(row)
    record("vehicle.position_report", request=request, entity_type="vehicle_position", entity_id=row.pk,
           metadata={"vehicle_id": v.vehicle_id, "source": source})
    return row


@transaction.atomic
def void_position(request, row, d, version):
    p = P.objects.select_for_update().select_related("vehicle").get(pk=row.pk)
    if p.version != version:
        raise VersionConflict()
    if p.voided_at:
        raise field_error("state", "already_void", "This position is already voided.")
    reason = svc._text(d, "reason", 300, required=True)
    p.voided_at, p.voided_by_username, p.voided_reason = timezone.now(), _actor(request), reason
    p.version += 1
    p.save()
    record("vehicle.position_void", request=request, entity_type="vehicle_position", entity_id=p.pk, metadata={"vehicle_id": p.vehicle.vehicle_id, "reason": reason})
    return p


def _out(p, now=None):
    now = now or timezone.now()
    age = max(int((now - p.recorded_at).total_seconds() // 60), 0)
    return {"id": str(p.pk), "vehicle": {"id": str(p.vehicle.pk), "vehicle_id": p.vehicle.vehicle_id, "plate": p.vehicle.plate, "make": p.vehicle.make,
                                         "model": p.vehicle.model},
            "latitude": str(p.latitude), "longitude": str(p.longitude), "accuracy_m": p.accuracy_m, "place": p.place, "source": p.source,
            "recorded_at": p.recorded_at, "age_minutes": age, "stale": age >= STALE_HOURS * 60, "note": p.note, "trip_id": str(p.trip_id) if p.trip_id else None,
            "recorded_by": p.created_by_username, "void": p.voided_at is not None, "voided_reason": p.voided_reason, "version": p.version}


_haversine_km = geofences.haversine_km


def trail_distance_km(rows):
    """Distance along oldest-first position rows, skipping steps under TRAIL_MIN_STEP_KM measured from the last counted point."""
    total, last = 0.0, None
    for r in rows:
        pt = (float(r.latitude), float(r.longitude))
        if last is None:
            last = pt
            continue
        step = _haversine_km(last[0], last[1], pt[0], pt[1])
        if step >= TRAIL_MIN_STEP_KM:
            total += step
            last = pt
    return round(total, 2)


class VehicleTrackingViewSet(viewsets.GenericViewSet):
    """Last known positions and position history. Out-of-scope rows answer 404."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9a-f\-]{36}"
    permission_map = {"latest": ("vehicles.view", "any"), "history": ("vehicles.view", "any"), "report": ("vehicles.position", "any"),
                      "void": ("vehicles.position", "any"), "trackers": ("vehicles.view", "any"), "tracker_add": ("vehicles.edit", "any"),
                      "tracker_off": ("vehicles.edit", "any"), "tracker_rotate": ("vehicles.edit", "any"),
                      "silent": ("vehicles.view", "any"), "trail": ("vehicles.view", "any"),
                      "fences": ("vehicles.view", "any"), "fence_add": ("vehicles.edit", "any"), "fence_update": ("vehicles.edit", "any"),
                      "fence_events": ("vehicles.view", "any"), "daily_report": ("vehicles.view", "any"),
                      "daily_report_export": ("vehicles.view", "any")}

    def _scoped(self):
        q = scope.unit_scope_q(self.request.user, "vehicles.view", "vehicle__org_unit__")
        return P.objects.none() if q is None else P.objects.filter(q)

    @action(detail=False, methods=["get"])
    def latest(self, request):
        """The newest non-void position of every vehicle in scope that has one (?q= filters by Vehicle ID or plate)."""
        q = scope.unit_scope_q(request.user, "vehicles.view", "org_unit__")
        if q is None:
            return Response({"results": []})
        vq = Vehicle.objects.filter(q).exclude(status="decommissioned")
        s = (request.query_params.get("q") or "").strip()[:40]
        if s:
            vq = vq.filter(vehicle_id__icontains=s.upper()) | vq.filter(plate_key__icontains=svc.plate_key(s) or s)
        newest = P.objects.filter(vehicle=OuterRef("pk"), voided_at__isnull=True).order_by("-recorded_at").values("pk")[:1]
        ids = [x for x in vq.annotate(last=Subquery(newest)).values_list("last", flat=True) if x]
        rows = list(P.objects.filter(pk__in=ids).select_related("vehicle").order_by("-recorded_at")[:500])
        record_read(request, "vehicle.read_positions", entity_type="vehicle_position_latest", count=len(rows))
        now = timezone.now()
        return Response({"results": [_out(p, now) for p in rows], "stale_hours": STALE_HOURS})

    @action(detail=False, methods=["get"])
    def history(self, request):
        p = request.query_params
        key = (p.get("vehicle") or "").strip()
        if not key:
            raise field_error("vehicle", "required", "Choose a vehicle.")
        qs = self._scoped().select_related("vehicle")
        qs = qs.filter(vehicle__vehicle_id=key.upper()) if key.upper().startswith("VEH-") else qs.filter(vehicle_id=_uid(key) or None)
        if p.get("include_void") != "1":
            qs = qs.filter(voided_at__isnull=True)
        if p.get("from"):
            qs = qs.filter(recorded_at__date__gte=svc._date(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(recorded_at__date__lte=svc._date(p["to"], "to"))
        page = self.paginate_queryset(qs.order_by("-recorded_at"))
        record_read(request, "vehicle.read_position_history", entity_type="vehicle_position_history", count=len(page))
        now = timezone.now()
        return self.get_paginated_response([_out(x, now) for x in page])

    @action(detail=False, methods=["get"])
    def silent(self, request):
        """Vehicles that should be reporting but are not: no usable position for ?hours= (default STALE_HOURS, 1 to 720), or none ever.
        Vehicles that are in the workshop or decommissioned are left out, because silence is expected there. Also lists linked GPS
        trackers that have gone quiet. Narrowed to the caller's unit scope."""
        raw = (request.query_params.get("hours") or "").strip()
        try:
            hours = int(raw) if raw else STALE_HOURS
        except ValueError:
            raise field_error("hours", "invalid", "Hours must be a whole number.")
        if not 1 <= hours <= 720:
            raise field_error("hours", "invalid", "Hours must be between 1 and 720.")
        q = scope.unit_scope_q(request.user, "vehicles.view", "org_unit__")
        if q is None:
            return Response({"hours": hours, "vehicles": [], "trackers": []})
        now = timezone.now()
        cutoff = now - timedelta(hours=hours)
        newest = P.objects.filter(vehicle=OuterRef("pk"), voided_at__isnull=True).order_by("-recorded_at").values("recorded_at")[:1]
        vq = (Vehicle.objects.filter(q).exclude(status__in=Vehicle.UNAVAILABLE).annotate(last=Subquery(newest))
              .filter(Q(last__isnull=True) | Q(last__lt=cutoff)).order_by("vehicle_id")[:200])
        vehicles = [{"id": str(v.pk), "vehicle_id": v.vehicle_id, "plate": v.plate, "make": v.make, "model": v.model, "never": v.last is None,
                     "last_seen_at": v.last, "age_minutes": None if v.last is None else max(int((now - v.last).total_seconds() // 60), 0)}
                    for v in vq]
        tq = scope.unit_scope_q(request.user, "vehicles.view", "vehicle__org_unit__")
        trackers = []
        if tq is not None:
            rows = (T.objects.filter(tq, active=True).filter(Q(last_seen_at__lt=cutoff) | Q(last_seen_at__isnull=True, created_at__lt=cutoff))
                    .select_related("vehicle").order_by("last_seen_at")[:200])
            trackers = [_tracker_out(t) for t in rows]
        record_read(request, "vehicle.read_silent", entity_type="vehicle_position_silent", count=len(vehicles) + len(trackers))
        return Response({"hours": hours, "vehicles": vehicles, "trackers": trackers})

    @action(detail=False, methods=["get"])
    def trail(self, request):
        """One vehicle's route over a date range, oldest first, with the distance travelled. At most TRAIL_MAX points (the newest ones
        when there are more; `truncated` says so). Distance adds up straight lines between points and ignores moves under 25 m, so a
        parked vehicle's GPS drift does not add up to kilometres."""
        p = request.query_params
        key = (p.get("vehicle") or "").strip()
        if not key:
            raise field_error("vehicle", "required", "Choose a vehicle.")
        qs = self._scoped().filter(voided_at__isnull=True)
        qs = qs.filter(vehicle__vehicle_id=key.upper()) if key.upper().startswith("VEH-") else qs.filter(vehicle_id=_uid(key) or None)
        if p.get("from"):
            qs = qs.filter(recorded_at__date__gte=svc._date(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(recorded_at__date__lte=svc._date(p["to"], "to"))
        newest_first = list(qs.order_by("-recorded_at")[:TRAIL_MAX + 1])
        truncated = len(newest_first) > TRAIL_MAX
        rows = list(reversed(newest_first[:TRAIL_MAX]))
        points = [{"id": str(r.pk), "latitude": str(r.latitude), "longitude": str(r.longitude), "recorded_at": r.recorded_at, "source": r.source}
                  for r in rows]
        record_read(request, "vehicle.read_position_trail", entity_type="vehicle_position_trail", count=len(points))
        return Response({"points": points, "count": len(points), "truncated": truncated, "distance_km": trail_distance_km(rows)})

    # ---- geofences ------------------------------------------------------------------------------------------------------
    @action(detail=False, methods=["get"], url_path="geofences")
    def fences(self, request):
        """Every fence (a fence is a place, not a person's data, so any role that can see vehicles sees them). Active ones first."""
        rows = Geofence.objects.order_by("-active", "name")
        return Response({"results": [_fence_out(f) for f in rows]})

    @action(detail=False, methods=["post"], url_path="geofences/add")
    def fence_add(self, request):
        d = json_body(request)
        f = create_fence(request, d)
        return Response(_fence_out(f), status=201)

    @action(detail=True, methods=["post"], url_path="geofences/update")
    def fence_update(self, request, pk=None):
        d = json_body(request)
        row = Geofence.objects.filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None:
            raise Http404
        return Response(_fence_out(update_fence(request, row, d, require_version(d))))

    @action(detail=False, methods=["get"], url_path="geofence-events")
    def fence_events(self, request):
        """Crossings, newest first, for vehicles in the caller's scope. ?vehicle= (Vehicle ID or id) ?geofence= ?from= ?to= ?limit= (1 to 500)."""
        p = request.query_params
        q = scope.unit_scope_q(request.user, "vehicles.view", "vehicle__org_unit__")
        if q is None:
            return Response({"results": []})
        qs = GeofenceEvent.objects.filter(q).select_related("geofence", "vehicle")
        key = (p.get("vehicle") or "").strip()
        if key:
            qs = qs.filter(vehicle__vehicle_id=key.upper()) if key.upper().startswith("VEH-") else qs.filter(vehicle_id=_uid(key) or None)
        if p.get("geofence"):
            qs = qs.filter(geofence_id=_uid(p["geofence"]) or None)
        if p.get("from"):
            qs = qs.filter(occurred_at__date__gte=svc._date(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(occurred_at__date__lte=svc._date(p["to"], "to"))
        try:
            limit = int(p.get("limit") or 100)
        except ValueError:
            raise field_error("limit", "invalid", "Limit must be a whole number.")
        if not 1 <= limit <= 500:
            raise field_error("limit", "invalid", "Limit must be between 1 and 500.")
        rows = list(qs.order_by("-occurred_at", "-id")[:limit])
        record_read(request, "vehicle.read_geofence_events", entity_type="vehicle_geofence_event", count=len(rows))
        return Response({"results": [{
            "id": str(e.pk), "kind": e.kind, "occurred_at": e.occurred_at, "latitude": str(e.latitude), "longitude": str(e.longitude),
            "geofence": {"id": str(e.geofence_id), "name": e.geofence.name},
            "vehicle": {"id": str(e.vehicle_id), "vehicle_id": e.vehicle.vehicle_id, "plate": e.vehicle.plate, "make": e.vehicle.make, "model": e.vehicle.model}}
            for e in rows]})

    # ---- daily movement report ------------------------------------------------------------------------------------------
    def _report_day(self, request):
        from . import movement
        raw = (request.query_params.get("date") or "").strip()
        day = svc._date(raw, "date") if raw else timezone.now().astimezone(movement.report_tz()).date()
        if day > timezone.now().astimezone(movement.report_tz()).date():
            raise field_error("date", "future", "Choose today or an earlier day.")
        return day

    @action(detail=False, methods=["get"], url_path="daily-report")
    def daily_report(self, request):
        """What each vehicle in scope did on one day (?date=YYYY-MM-DD, default today). See apps/vehicles/movement.py for how it is worked out."""
        from . import movement
        report = movement.build_daily_report(request.user, self._report_day(request))
        record_read(request, "vehicle.read_daily_report", entity_type="vehicle_daily_report", count=len(report["vehicles"]) + len(report["not_reporting"]))
        return Response(report)

    @action(detail=False, methods=["get"], url_path="daily-report/export", content_negotiation_class=IgnoreNegotiation, throttle_scope="bulk")
    def daily_report_export(self, request):
        """The same report as a CSV file. Needs a fresh authenticator check; the file's SHA-256 is written to the audit log."""
        import hashlib

        from . import movement
        require_fresh_mfa(request)
        report = movement.build_daily_report(request.user, self._report_day(request))
        body = movement.report_csv(report)
        digest = hashlib.sha256(body).hexdigest()
        record("vehicle.export_daily_report", request=request, entity_type="vehicle_daily_report",
               metadata={"date": report["date"], "vehicles": len(report["vehicles"]) + len(report["not_reporting"]), "sha256": digest})
        resp = HttpResponse(body, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="daily-movement-{report["date"]}.csv"'
        resp["Cache-Control"] = "no-store"
        resp["X-Content-SHA256"] = digest
        return resp

    @action(detail=False, methods=["post"])
    def report(self, request):
        d = json_body(request)
        key = str(d.get("vehicle") or "").strip()
        qs = Vehicle.objects.select_related("org_unit")
        v = qs.filter(vehicle_id=key.upper()).first() if key.upper().startswith("VEH-") else (qs.filter(pk=_uid(key)).first() if _uid(key) else None)
        if v is None or not scope.can(request.user, "vehicles.position", unit=v.org_unit):
            raise field_error("vehicle", "unknown", "Unknown vehicle.")
        row = report_position(request, v, d)
        return Response(_out(P.objects.select_related("vehicle").get(pk=row.pk)), status=201)

    @action(detail=False, methods=["get"])
    def trackers(self, request):
        q = scope.unit_scope_q(request.user, "vehicles.view", "vehicle__org_unit__")
        rows = T.objects.none() if q is None else T.objects.filter(q).select_related("vehicle").order_by("-active", "-created_at")[:200]
        return Response({"results": [_tracker_out(t) for t in rows]})

    @action(detail=False, methods=["post"], url_path="trackers/link")
    def tracker_add(self, request):
        d = json_body(request)
        key = str(d.get("vehicle") or "").strip()
        qs = Vehicle.objects.select_related("org_unit")
        v = qs.filter(vehicle_id=key.upper()).first() if key.upper().startswith("VEH-") else (qs.filter(pk=_uid(key)).first() if _uid(key) else None)
        if v is None or not scope.can(request.user, "vehicles.edit", unit=v.org_unit):
            raise field_error("vehicle", "unknown", "Unknown vehicle.")
        t, full = link_tracker(request, v, d)
        return Response({**_tracker_out(T.objects.select_related("vehicle").get(pk=t.pk)), "key": full}, status=201)  # shown once

    @action(detail=True, methods=["post"], url_path="trackers/off")
    def tracker_off(self, request, pk=None):
        d = json_body(request)
        q = scope.unit_scope_q(request.user, "vehicles.view", "vehicle__org_unit__")
        row = T.objects.filter(q).select_related("vehicle__org_unit").filter(pk=_uid(pk)).first() if (q is not None and _uid(pk)) else None
        if row is None or not scope.can(request.user, "vehicles.edit", unit=row.vehicle.org_unit):
            raise Http404
        return Response(_tracker_out(switch_off_tracker(request, row, d, require_version(d))))

    @action(detail=True, methods=["post"], url_path="trackers/rotate")
    def tracker_rotate(self, request, pk=None):
        d = json_body(request)
        q = scope.unit_scope_q(request.user, "vehicles.view", "vehicle__org_unit__")
        row = T.objects.filter(q).select_related("vehicle__org_unit").filter(pk=_uid(pk)).first() if (q is not None and _uid(pk)) else None
        if row is None or not scope.can(request.user, "vehicles.edit", unit=row.vehicle.org_unit):
            raise Http404
        t, full = rotate_tracker(request, row, d, require_version(d))
        return Response({**_tracker_out(t), "key": full})  # shown once

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        d = json_body(request)
        row = self._scoped().select_related("vehicle__org_unit").filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None or not scope.can(request.user, "vehicles.position", unit=row.vehicle.org_unit):
            raise Http404
        p = void_position(request, row, d, require_version(d))
        return Response(_out(P.objects.select_related("vehicle").get(pk=p.pk)))


# ---- hardware trackers (automatic feed) -------------------------------------------------------------------------------------
T = VehicleTracker
MAX_AGE = timedelta(days=7)
FAIL_LIMIT, FAIL_WINDOW = 30, 600  # wrong keys per address per 10 minutes before the feed answers "slow down"


def _hash(full):
    return hashlib.sha256(full.encode()).hexdigest()


def _new_key():
    prefix = secrets.token_hex(4)
    return prefix, f"trk_{prefix}_{secrets.token_urlsafe(32)}"


def _parse(raw):
    parts = str(raw or "").split("_", 2)
    return (parts[1], raw) if len(parts) == 3 and parts[0] == "trk" and len(parts[1]) == 8 else None


def _tracker_out(t):
    return {"id": str(t.pk), "vehicle": {"id": str(t.vehicle.pk), "vehicle_id": t.vehicle.vehicle_id, "plate": t.vehicle.plate},
            "device_ref": t.device_ref, "active": t.active, "last_seen_at": t.last_seen_at, "version": t.version}


@transaction.atomic
def link_tracker(request, vehicle, d):
    v = Vehicle.objects.select_for_update().get(pk=vehicle.pk)
    if v.status == "decommissioned":
        raise field_error("vehicle", "decommissioned", "A decommissioned vehicle is read-only.")
    ref = svc._text(d, "device_ref", 60, required=True)
    prefix, full = _new_key()
    try:
        with transaction.atomic():
            t = T.objects.create(vehicle=v, device_ref=ref, key_prefix=prefix, key_hash=_hash(full), created_by_username=_actor(request))
    except IntegrityError:
        raise field_error("device_ref", "in_use", "This device is already linked to a vehicle. Switch that link off first.")
    record("vehicle.tracker_link", request=request, entity_type="vehicle_tracker", entity_id=t.pk, metadata={"vehicle_id": v.vehicle_id})
    return t, full


@transaction.atomic
def switch_off_tracker(request, row, d, version):
    t = T.objects.select_for_update().select_related("vehicle").get(pk=row.pk)
    if t.version != version:
        raise VersionConflict()
    if not t.active:
        raise field_error("state", "already_off", "This tracker is already switched off.")
    t.active, t.switched_off_at, t.switched_off_by_username = False, timezone.now(), _actor(request)
    t.version += 1
    t.save()
    record("vehicle.tracker_off", request=request, entity_type="vehicle_tracker", entity_id=t.pk, metadata={"vehicle_id": t.vehicle.vehicle_id})
    return t


def _fence_out(f):
    return {"id": str(f.pk), "name": f.name, "shape": f.shape, "points": f.points or [], "latitude": str(f.latitude), "longitude": str(f.longitude),
            "radius_m": f.radius_m, "alert_on": f.alert_on, "active": f.active, "version": f.version, "created_by_username": f.created_by_username, "created_at": f.created_at}


def _fence_radius(d, required=True):
    v = d.get("radius_m")
    if v in (None, ""):
        if required:
            raise field_error("radius_m", "required", "This field is required.")
        return None
    try:
        n = int(str(v).strip())
    except ValueError:
        raise field_error("radius_m", "invalid_number", "Enter a whole number of metres.")
    if not 50 <= n <= 100_000:
        raise field_error("radius_m", "out_of_range", "Radius must be between 50 m and 100 km.")
    return n

POLY_MIN, POLY_MAX = 3, 50


def _segments_cross(a, b, c, d):
    """True when segment a-b properly crosses segment c-d (shared end points do not count; neighbours share one)."""
    def orient(p, q, r):
        v = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
        return 0 if v == 0 else (1 if v > 0 else 2)
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def _fence_points(d):
    """Validate polygon corners [[lat, lon], ...] and return (points, centre_lat, centre_lon, radius_m)."""
    raw = d.get("points")
    if not isinstance(raw, list):
        raise field_error("points", "required", "Place at least three corners on the map.")
    pts = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise field_error("points", "invalid", "Each corner needs a latitude and a longitude.")
        lat = _coord({"points": item[0]}, "points", Decimal("-90"), Decimal("90"))
        lon = _coord({"points": item[1]}, "points", Decimal("-180"), Decimal("180"))
        pts.append([float(lat), float(lon)])
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()  # a closing corner that repeats the first is not needed
    if not POLY_MIN <= len(pts) <= POLY_MAX:
        raise field_error("points", "count", f"A zone needs between {POLY_MIN} and {POLY_MAX} corners.")
    if any(pts[i] == pts[(i + 1) % len(pts)] for i in range(len(pts))):
        raise field_error("points", "duplicate", "Two neighbouring corners are in the same place.")
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _segments_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                raise field_error("points", "self_intersect", "The zone's edges cross each other. Move a corner so the outline does not cross itself.")
    area2 = sum(pts[i][1] * pts[(i + 1) % n][0] - pts[(i + 1) % n][1] * pts[i][0] for i in range(n))
    if abs(area2) < 1e-10:
        raise field_error("points", "flat", "The corners are in a line. Place them around an area.")
    clat, clon = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    radius = int(math.ceil(max(_haversine_km(clat, clon, p[0], p[1]) for p in pts) * 1000))
    if radius > 100_000:
        raise field_error("points", "too_large", "The zone is larger than 100 km across.")
    return pts, round(clat, 6), round(clon, 6), max(radius, 50)


def _fence_alert(d):
    v = d.get("alert_on", Geofence.AlertOn.BOTH)
    if v not in Geofence.AlertOn.values:
        raise field_error("alert_on", "invalid_choice", "Choose entering, leaving or both.")
    return v


def _fence_name_free(name, exclude=None):
    qs = Geofence.objects.filter(name__iexact=name)
    if exclude is not None:
        qs = qs.exclude(pk=exclude)
    if qs.exists():
        raise field_error("name", "duplicate", "A zone with this name already exists.")


@transaction.atomic
def create_fence(request, d):
    name = svc._text(d, "name", 100, required=True)
    _fence_name_free(name)
    shape = d.get("shape") or Geofence.Shape.CIRCLE
    if shape not in Geofence.Shape.values:
        raise field_error("shape", "invalid_choice", "Choose circle or polygon.")
    if shape == Geofence.Shape.POLYGON:
        pts, clat, clon, radius = _fence_points(d)
        f = Geofence.objects.create(name=name, shape=shape, points=pts, latitude=Decimal(str(clat)).quantize(Decimal("0.000001")),
                                    longitude=Decimal(str(clon)).quantize(Decimal("0.000001")), radius_m=radius,
                                    alert_on=_fence_alert(d), created_by_username=_actor(request))
    else:
        f = Geofence.objects.create(name=name, latitude=_coord(d, "latitude", Decimal("-90"), Decimal("90")),
                                    longitude=_coord(d, "longitude", Decimal("-180"), Decimal("180")), radius_m=_fence_radius(d),
                                    alert_on=_fence_alert(d), created_by_username=_actor(request))
    record("vehicle.geofence_create", request=request, entity_type="vehicle_geofence", entity_id=f.pk,
           metadata={"name": f.name, "shape": f.shape, "radius_m": f.radius_m, "corners": len(f.points or [])})
    return f


@transaction.atomic
def update_fence(request, row, d, version):
    f = Geofence.objects.select_for_update().get(pk=row.pk)
    if f.version != version:
        raise VersionConflict()
    changed, reset = [], False
    poly = f.shape == Geofence.Shape.POLYGON
    if poly and any(k in d for k in ("latitude", "longitude", "radius_m")):
        raise field_error("points", "polygon_fields", "A polygon zone is changed through its corners, not a centre and radius.")
    if not poly and "points" in d:
        raise field_error("points", "circle_fields", "A circular zone has no corners. Add a new polygon zone instead.")
    if "points" in d:
        pts, clat, clon, radius = _fence_points(d)
        f.points, f.latitude, f.longitude, f.radius_m = pts, Decimal(str(clat)).quantize(Decimal("0.000001")), Decimal(str(clon)).quantize(Decimal("0.000001")), radius
        changed.append("points")
        reset = True
    if "name" in d:
        name = svc._text(d, "name", 100, required=True)
        _fence_name_free(name, exclude=f.pk)
        f.name = name
        changed.append("name")
    if "latitude" in d:
        f.latitude = _coord(d, "latitude", Decimal("-90"), Decimal("90"))
        changed.append("latitude")
        reset = True
    if "longitude" in d:
        f.longitude = _coord(d, "longitude", Decimal("-180"), Decimal("180"))
        changed.append("longitude")
        reset = True
    if "radius_m" in d:
        f.radius_m = _fence_radius(d)
        changed.append("radius_m")
        reset = True
    if "alert_on" in d:
        f.alert_on = _fence_alert(d)
        changed.append("alert_on")
    if "active" in d:
        if not isinstance(d["active"], bool):
            raise field_error("active", "invalid", "Must be true or false.")
        if d["active"] != f.active:
            f.active = d["active"]
            changed.append("active")
            reset = True  # vehicles may have moved while it was off
    if not changed:
        raise field_error("state", "nothing_to_change", "Nothing to change.")
    if reset:
        f.states.all().delete()  # starting points are stale: the next fix of each vehicle sets a new one (no event)
    f.version += 1
    f.save()
    record("vehicle.geofence_update", request=request, entity_type="vehicle_geofence", entity_id=f.pk, metadata={"changed": changed})
    return f


@transaction.atomic
def rotate_tracker(request, row, d, version):
    """Issue a new key for a tracker (the old one stops working at once). Use it when a key may have leaked or a Traccar server is
    replaced. The device link, its history and last-seen time are kept; the new key is shown once, like the first."""
    t = T.objects.select_for_update().select_related("vehicle").get(pk=row.pk)
    if t.version != version:
        raise VersionConflict()
    if not t.active:
        raise field_error("state", "already_off", "This tracker is switched off. Link it again to get a key.")
    for _ in range(5):
        prefix, full = _new_key()
        if not T.objects.filter(key_prefix=prefix).exists():
            break
    else:
        raise field_error("key", "retry", "Could not make a new key. Try again.")
    t.key_prefix, t.key_hash = prefix, _hash(full)
    t.version += 1
    t.save()
    record("vehicle.tracker_rotate", request=request, entity_type="vehicle_tracker", entity_id=t.pk, metadata={"vehicle_id": t.vehicle.vehicle_id})
    return t, full


def _stamp(value):
    """Traccar / OsmAnd send epoch seconds (or milliseconds); other feeds send ISO text. Missing means now."""
    if value in (None, ""):
        return timezone.now()
    raw = str(value).strip()
    try:
        n = float(raw)
        return datetime.fromtimestamp(n / 1000 if n > 10_000_000_000 else n, tz=dt_timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    dt = parse_datetime(raw)
    if dt is None:
        raise ValueError("timestamp")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


class TrackerFeedView(APIView):
    """Receives positions from a linked tracker, for example a Traccar server forwarding to
    /api/v1/tracker/feed/?key=trk_...&id=<device>&lat=..&lon=..&timestamp=..&accuracy=..  (GET or POST, form or JSON).
    The key is the only credential and is tied to one device and one vehicle; it can only add positions. Answers carry no detail."""

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "tracker"

    def _deny(self, request, ip, code=401):
        key = f"trk-fail:{ip or 'unknown'}"
        cache.add(key, 0, FAIL_WINDOW)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, FAIL_WINDOW)
        record("vehicle.tracker_auth_failed", request=request, outcome="denied", entity_type="vehicle_tracker")
        return Response({"detail": "Not accepted."}, status=code)

    def _handle(self, request):
        http = request._request
        ip = client_ip(http)
        if cache.get(f"trk-fail:{ip or 'unknown'}", 0) >= FAIL_LIMIT:
            return Response({"detail": "Slow down."}, status=429)
        data = {**request.query_params.dict(), **(request.data if hasattr(request.data, "get") else {})}
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        raw = auth[7:].strip() if auth.lower().startswith("bearer ") else data.get("key")
        parsed = _parse(raw)
        tracker = T.objects.select_related("vehicle").filter(key_prefix=parsed[0]).first() if parsed else None
        ok = hmac.compare_digest(_hash(raw) if parsed else "0" * 64, tracker.key_hash if tracker else "0" * 64)
        if not (parsed and tracker and ok and tracker.active) or str(data.get("id", tracker.device_ref if tracker else "")) != (tracker.device_ref if tracker else None):
            return self._deny(http, ip)
        v = tracker.vehicle
        if v.status == "decommissioned":
            return Response({"detail": "Not accepted."}, status=409)
        try:
            lat = _coord({"latitude": data.get("lat", data.get("latitude"))}, "latitude", Decimal("-90"), Decimal("90"))
            lon = _coord({"longitude": data.get("lon", data.get("longitude"))}, "longitude", Decimal("-180"), Decimal("180"))
            at = _stamp(data.get("timestamp"))
        except (ValueError, ValidationError):  # a bad reading is refused, never stored
            return Response({"detail": "Bad reading."}, status=400)
        now = timezone.now()
        if at > now + timedelta(minutes=5) or at < now - MAX_AGE:
            return Response({"detail": "Bad reading."}, status=400)
        acc = None
        try:
            if data.get("accuracy") not in (None, ""):
                acc = max(0, min(int(round(float(data["accuracy"]))), 1_000_000))
        except (TypeError, ValueError):
            acc = None
        with transaction.atomic():
            if P.objects.filter(vehicle=v, source="tracker", recorded_at=at, latitude=lat, longitude=lon).exists():
                return Response({"status": "duplicate"})  # trackers resend; the same fix is stored once
            trip = VehicleTrip.objects.filter(vehicle=v, state="open").first()
            fix = P.objects.create(vehicle=v, trip=trip, latitude=lat, longitude=lon, accuracy_m=acc, source="tracker", recorded_at=at,
                                   created_by_username=f"tracker:{tracker.key_prefix}")
            geofences.evaluate_position(fix)
            T.objects.filter(pk=tracker.pk).update(last_seen_at=now)
        return Response({"status": "ok"}, status=201)

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)
