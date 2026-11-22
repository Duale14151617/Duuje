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
from django.http import Http404
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
from apps.audit.services import client_ip, record, record_read
from apps.core.concurrency import VersionConflict, require_version
from apps.core.errors import field_error
from apps.core.params import json_body

from . import services as svc
from .models import Vehicle, VehiclePosition, VehicleTracker, VehicleTrip
from .views import _Page, _uid

P = VehiclePosition
STALE_HOURS = 24
MIN_GAP_SECONDS = 20  # one phone cannot flood a vehicle's history
TRAIL_MAX = 500  # points in one route
TRAIL_MIN_STEP_KM = 0.025  # moves shorter than this are GPS drift, not travel


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


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


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
                      "silent": ("vehicles.view", "any"), "trail": ("vehicles.view", "any")}

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
            P.objects.create(vehicle=v, trip=trip, latitude=lat, longitude=lon, accuracy_m=acc, source="tracker", recorded_at=at,
                             created_by_username=f"tracker:{tracker.key_prefix}")
            T.objects.filter(pk=tracker.pk).update(last_seen_at=now)
        return Response({"status": "ok"}, status=201)

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)
