"""Vehicle trip log and fuel log: business rules and API. Rows are voided with a reason, never deleted. Every write is audited.
Access reuses the vehicle permissions: vehicles.view to read, vehicles.edit to record (both narrowed to the caller's unit scope),
vehicles.cost to see or record fuel cost."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Sum
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.concurrency import VersionConflict, require_version
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from . import services as svc
from .models import FuelEntry, Vehicle, VehicleTrip
from .views import _Page, _person_brief, _uid

T = VehicleTrip


# ---- helpers ---------------------------------------------------------------------------------------------------------------
def _int(d, name, required=True):
    v = d.get(name)
    if v in (None, ""):
        if required:
            raise field_error(name, "required", "This field is required.")
        return None
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise field_error(name, "invalid_number", "Enter a whole number.")
    if n < 0 or n > 9_999_999:
        raise field_error(name, "invalid_number", "Enter a whole number.")
    return n


def _when(value, name, default=None):
    if value in (None, ""):
        return default
    dt = parse_datetime(str(value))
    if dt is None:
        raise field_error(name, "invalid_datetime", "Use a date and time such as 2026-11-16T08:30.")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _driver(d, vehicle):
    raw = d.get("driver")
    if raw in (None, ""):
        return vehicle.driver
    p = Personnel.objects.filter(pk=_uid(raw)).exclude(status__in=NOT_SERVING).select_related("rank").first() if _uid(raw) else None
    if p is None:
        raise field_error("driver", "unknown", "Unknown or non-serving person.")
    return p


def _open_vehicle(pk):
    """Lock the vehicle row: concurrent log entries for one vehicle are serialised, so odometer checks cannot race."""
    v = Vehicle.objects.select_for_update().get(pk=pk)
    if v.status == "decommissioned":
        raise field_error("vehicle", "decommissioned", "A decommissioned vehicle is read-only.")
    return v


def last_odometer(vehicle, before=None):
    """Highest odometer reading on file for a vehicle (voided rows ignored). `before` limits to readings from earlier days."""
    t = T.objects.filter(vehicle=vehicle).exclude(state="void")
    f = FuelEntry.objects.filter(vehicle=vehicle, voided_at__isnull=True)
    if before is not None:
        t, f = t.filter(started_at__date__lt=before), f.filter(filled_on__lt=before)
    vals = [t.aggregate(m=Max("start_odometer"))["m"], t.aggregate(m=Max("end_odometer"))["m"], f.aggregate(m=Max("odometer"))["m"]]
    vals = [x for x in vals if x is not None]
    return max(vals) if vals else None


def _check_odometer(vehicle, value, name, before=None):
    last = last_odometer(vehicle, before)
    if last is not None and value < last:
        raise field_error(name, "odometer_regression", f"The odometer cannot be lower than the last recorded reading ({last}).")


def _actor_name(request):
    return getattr(getattr(request, "user", None), "username", "") or ""


# ---- trips -----------------------------------------------------------------------------------------------------------------
@transaction.atomic
def start_trip(request, vehicle, d):
    v = _open_vehicle(vehicle.pk)
    if not svc.is_available(v.status):
        raise field_error("vehicle", "unavailable", "This vehicle is not available for normal use.")
    purpose = svc._text(d, "purpose", 200, required=True)
    odo = _int(d, "start_odometer")
    started = _when(d.get("started_at"), "started_at", timezone.now())
    if started > timezone.now() + timedelta(minutes=5):
        raise field_error("started_at", "future", "A trip cannot start in the future.")
    _check_odometer(v, odo, "start_odometer", before=started.date())
    try:
        with transaction.atomic():
            t = T.objects.create(vehicle=v, driver=_driver(d, v), purpose=purpose, origin=svc._text(d, "origin", 150),
                                 destination=svc._text(d, "destination", 150), authority_ref=svc._text(d, "authority_ref", 150),
                                 started_at=started, start_odometer=odo, notes=svc._text(d, "notes", 500), created_by_username=_actor_name(request))
    except IntegrityError:
        raise field_error("vehicle", "trip_open", "This vehicle already has an open trip. End it first.")
    record("vehicle.trip_start", request=request, entity_type="vehicle_trip", entity_id=t.pk, metadata={"vehicle_id": v.vehicle_id, "start_odometer": odo})
    return t


@transaction.atomic
def end_trip(request, trip, d, version):
    t = T.objects.select_for_update().select_related("vehicle").get(pk=trip.pk)
    if t.version != version:
        raise VersionConflict()
    if t.state != "open":
        raise field_error("state", "not_open", "Only an open trip can be ended.")
    end_odo = _int(d, "end_odometer")
    if end_odo < t.start_odometer:
        raise field_error("end_odometer", "odometer_regression", "The end reading cannot be lower than the start reading.")
    ended = _when(d.get("ended_at"), "ended_at", timezone.now())
    if ended < t.started_at:
        raise field_error("ended_at", "before_start", "A trip cannot end before it started.")
    t.end_odometer, t.ended_at, t.state, t.ended_by_username = end_odo, ended, "completed", _actor_name(request)
    if d.get("destination"):
        t.destination = svc._text(d, "destination", 150)
    if d.get("notes"):
        t.notes = svc._text(d, "notes", 500)
    t.version += 1
    t.save()
    record("vehicle.trip_end", request=request, entity_type="vehicle_trip", entity_id=t.pk,
           metadata={"vehicle_id": t.vehicle.vehicle_id, "distance_km": end_odo - t.start_odometer})
    return t


@transaction.atomic
def void_trip(request, trip, d, version):
    t = T.objects.select_for_update().select_related("vehicle").get(pk=trip.pk)
    if t.version != version:
        raise VersionConflict()
    if t.state == "void":
        raise field_error("state", "already_void", "This trip is already voided.")
    reason = svc._text(d, "reason", 300, required=True)
    t.state, t.voided_at, t.voided_by_username, t.voided_reason = "void", timezone.now(), _actor_name(request), reason
    t.version += 1
    t.save()
    record("vehicle.trip_void", request=request, entity_type="vehicle_trip", entity_id=t.pk, metadata={"vehicle_id": t.vehicle.vehicle_id, "reason": reason})
    return t


# ---- fuel ------------------------------------------------------------------------------------------------------------------
def _money(value, name):
    try:
        x = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise field_error(name, "invalid_number", "Enter a valid amount.")
    return x


@transaction.atomic
def add_fuel(request, vehicle, d, can_cost):
    v = _open_vehicle(vehicle.pk)
    filled_on = svc._date(d.get("filled_on"), "filled_on", required=True)
    if filled_on > timezone.localdate():
        raise field_error("filled_on", "future", "A refuelling cannot be dated in the future.")
    litres = _money(d.get("litres"), "litres")
    if litres <= 0 or litres > 2000:
        raise field_error("litres", "invalid_litres", "Litres must be more than 0 and at most 2000.")
    odo = _int(d, "odometer")
    _check_odometer(v, odo, "odometer", before=filled_on)
    ftype = d.get("fuel_type") or "diesel"
    if ftype not in {c.value for c in FuelEntry.FuelType}:
        raise field_error("fuel_type", "invalid_type", "Choose diesel, petrol or other.")
    cost, currency = None, ""
    if d.get("cost") not in (None, ""):
        if not can_cost:
            raise field_error("cost", "not_permitted", "You may not record costs.")
        cost = _money(d["cost"], "cost")
        if cost < 0:
            raise field_error("cost", "invalid_cost", "Invalid cost.")
        currency = svc._text(d, "currency", 3).upper()
    f = FuelEntry.objects.create(vehicle=v, driver=_driver(d, v), filled_on=filled_on, fuel_type=ftype, litres=litres, odometer=odo,
                                 full_tank=bool(d.get("full_tank", True)), cost=cost, currency=currency, station=svc._text(d, "station", 150),
                                 receipt_ref=svc._text(d, "receipt_ref", 150), created_by_username=_actor_name(request))
    record("vehicle.fuel_add", request=request, entity_type="vehicle_fuel", entity_id=f.pk, metadata={"vehicle_id": v.vehicle_id, "litres": str(litres), "odometer": odo})
    return f


@transaction.atomic
def void_fuel(request, entry, d, version):
    f = FuelEntry.objects.select_for_update().select_related("vehicle").get(pk=entry.pk)
    if f.version != version:
        raise VersionConflict()
    if f.voided_at:
        raise field_error("state", "already_void", "This entry is already voided.")
    reason = svc._text(d, "reason", 300, required=True)
    f.voided_at, f.voided_by_username, f.voided_reason = timezone.now(), _actor_name(request), reason
    f.version += 1
    f.save()
    record("vehicle.fuel_void", request=request, entity_type="vehicle_fuel", entity_id=f.pk, metadata={"vehicle_id": f.vehicle.vehicle_id, "reason": reason})
    return f


def consumption(vehicle_qs_fuel):
    """Litres per 100 km by the full-tank method: litres bought after the first fill, over the distance since the first fill."""
    rows = list(vehicle_qs_fuel.filter(voided_at__isnull=True, full_tank=True).order_by("odometer", "filled_on"))
    if len(rows) < 2:
        return None
    km = rows[-1].odometer - rows[0].odometer
    if km <= 0:
        return None
    litres = sum((r.litres for r in rows[1:]), Decimal(0))
    return round(float(litres) / km * 100, 1)


# ---- serialisers -----------------------------------------------------------------------------------------------------------
def _veh(v):
    return {"id": str(v.pk), "vehicle_id": v.vehicle_id, "plate": v.plate, "make": v.make, "model": v.model}


def _trip_out(t):
    return {"id": str(t.pk), "vehicle": _veh(t.vehicle), "driver": _person_brief(t.driver), "purpose": t.purpose, "origin": t.origin,
            "destination": t.destination, "authority_ref": t.authority_ref, "started_at": t.started_at, "ended_at": t.ended_at,
            "start_odometer": t.start_odometer, "end_odometer": t.end_odometer,
            "distance_km": (t.end_odometer - t.start_odometer) if t.end_odometer is not None else None, "state": t.state, "notes": t.notes,
            "recorded_by": t.created_by_username, "voided_reason": t.voided_reason if t.state == "void" else "", "version": t.version}


def _fuel_out(f, show_cost):
    d = {"id": str(f.pk), "vehicle": _veh(f.vehicle), "driver": _person_brief(f.driver), "filled_on": f.filled_on, "fuel_type": f.fuel_type,
         "litres": str(f.litres), "odometer": f.odometer, "full_tank": f.full_tank, "station": f.station, "receipt_ref": f.receipt_ref,
         "recorded_by": f.created_by_username, "void": f.voided_at is not None, "voided_reason": f.voided_reason, "version": f.version}
    if show_cost:
        d["cost"] = None if f.cost is None else str(f.cost)
        d["currency"] = f.currency
    return d


# ---- API -------------------------------------------------------------------------------------------------------------------
class VehicleLogViewSet(viewsets.GenericViewSet):
    """Trip log and fuel log. Reads are narrowed to the caller's unit scope (out-of-scope rows answer 404)."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9A-Za-z\-]+"
    permission_map = {"trips": ("vehicles.view", "any"), "trip_start": ("vehicles.edit", "any"), "trip_end": ("vehicles.edit", "any"),
                      "trip_void": ("vehicles.edit", "any"), "fuel": ("vehicles.view", "any"), "fuel_add": ("vehicles.edit", "any"),
                      "fuel_void": ("vehicles.edit", "any"), "summary": ("vehicles.view", "any")}

    def _scoped(self, model):
        q = scope.unit_scope_q(self.request.user, "vehicles.view", "vehicle__org_unit__")
        return model.objects.none() if q is None else model.objects.filter(q)

    def _vehicle_for_write(self, value):
        """Resolve a vehicle by id or VEH- number; it must be visible and editable by the caller, else it reads as unknown."""
        qs = Vehicle.objects.select_related("org_unit", "driver__rank")
        key = str(value or "").strip()
        v = qs.filter(vehicle_id=key.upper()).first() if key.upper().startswith("VEH-") else (qs.filter(pk=_uid(key)).first() if _uid(key) else None)
        if v is None or not scope.can(self.request.user, "vehicles.edit", unit=v.org_unit):
            raise field_error("vehicle", "unknown", "Unknown vehicle.")
        return v

    def _filter_vehicle(self, qs, value):
        key = str(value).strip()
        return qs.filter(vehicle__vehicle_id=key.upper()) if key.upper().startswith("VEH-") else qs.filter(vehicle_id=_uid(key) or None)

    def _row(self, model, pk, write=False):
        row = self._scoped(model).select_related("vehicle__org_unit").filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None or (write and not scope.can(self.request.user, "vehicles.edit", unit=row.vehicle.org_unit)):
            raise Http404
        return row

    # trips
    @action(detail=False, methods=["get"])
    def trips(self, request):
        p = request.query_params
        qs = self._scoped(T).select_related("vehicle", "driver__rank")
        if p.get("vehicle"):
            qs = self._filter_vehicle(qs, p["vehicle"])
        if p.get("state") in {"open", "completed", "void"}:
            qs = qs.filter(state=p["state"])
        elif p.get("include_void") != "1":
            qs = qs.exclude(state="void")
        if p.get("from"):
            qs = qs.filter(started_at__date__gte=svc._date(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(started_at__date__lte=svc._date(p["to"], "to"))
        if p.get("q"):
            s = p["q"].strip()[:60]
            qs = qs.filter(Q(vehicle__vehicle_id__icontains=s) | Q(vehicle__plate_key__icontains=svc.plate_key(s) or s) | Q(purpose__icontains=s) | Q(destination__icontains=s))
        page = self.paginate_queryset(qs.order_by("-started_at"))
        record_read(request, "vehicle.read_trips", entity_type="vehicle_trip_log", count=len(page))
        return self.get_paginated_response([_trip_out(t) for t in page])

    @action(detail=False, methods=["post"], url_path="trips/start")
    def trip_start(self, request):
        d = json_body(request)
        t = start_trip(request, self._vehicle_for_write(d.get("vehicle")), d)
        return Response(_trip_out(T.objects.select_related("vehicle", "driver__rank").get(pk=t.pk)), status=201)

    @action(detail=False, methods=["post"], url_path=r"trips/(?P<tid>[0-9a-f\-]{36})/end")
    def trip_end(self, request, tid=None):
        d = json_body(request)
        t = end_trip(request, self._row(T, tid, write=True), d, require_version(d))
        return Response(_trip_out(T.objects.select_related("vehicle", "driver__rank").get(pk=t.pk)))

    @action(detail=False, methods=["post"], url_path=r"trips/(?P<tid>[0-9a-f\-]{36})/void")
    def trip_void(self, request, tid=None):
        d = json_body(request)
        t = void_trip(request, self._row(T, tid, write=True), d, require_version(d))
        return Response(_trip_out(T.objects.select_related("vehicle", "driver__rank").get(pk=t.pk)))

    # fuel
    def _show_cost(self, f):
        return scope.can(self.request.user, "vehicles.cost", unit=f.vehicle.org_unit)

    @action(detail=False, methods=["get"])
    def fuel(self, request):
        p = request.query_params
        qs = self._scoped(FuelEntry).select_related("vehicle__org_unit", "driver__rank")
        if p.get("vehicle"):
            qs = self._filter_vehicle(qs, p["vehicle"])
        if p.get("include_void") != "1":
            qs = qs.filter(voided_at__isnull=True)
        if p.get("from"):
            qs = qs.filter(filled_on__gte=svc._date(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(filled_on__lte=svc._date(p["to"], "to"))
        page = self.paginate_queryset(qs.order_by("-filled_on", "-created_at"))
        record_read(request, "vehicle.read_fuel", entity_type="vehicle_fuel_log", count=len(page))
        return self.get_paginated_response([_fuel_out(f, self._show_cost(f)) for f in page])

    @action(detail=False, methods=["post"], url_path="fuel/add")
    def fuel_add(self, request):
        d = json_body(request)
        v = self._vehicle_for_write(d.get("vehicle"))
        f = add_fuel(request, v, d, scope.can(request.user, "vehicles.cost", unit=v.org_unit))
        return Response(_fuel_out(FuelEntry.objects.select_related("vehicle__org_unit", "driver__rank").get(pk=f.pk), self._show_cost(f)), status=201)

    @action(detail=False, methods=["post"], url_path=r"fuel/(?P<fid>[0-9a-f\-]{36})/void")
    def fuel_void(self, request, fid=None):
        d = json_body(request)
        f = void_fuel(request, self._row(FuelEntry, fid, write=True), d, require_version(d))
        return Response(_fuel_out(FuelEntry.objects.select_related("vehicle__org_unit", "driver__rank").get(pk=f.pk), self._show_cost(f)))

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Distance, litres and consumption for one vehicle (?vehicle=) over an optional date range."""
        p = request.query_params
        if not p.get("vehicle"):
            raise field_error("vehicle", "required", "Choose a vehicle.")
        trips = self._filter_vehicle(self._scoped(T).filter(state="completed"), p["vehicle"])
        fuel = self._filter_vehicle(self._scoped(FuelEntry).filter(voided_at__isnull=True), p["vehicle"]).select_related("vehicle__org_unit")
        if p.get("from"):
            d0 = svc._date(p["from"], "from")
            trips, fuel = trips.filter(started_at__date__gte=d0), fuel.filter(filled_on__gte=d0)
        if p.get("to"):
            d1 = svc._date(p["to"], "to")
            trips, fuel = trips.filter(started_at__date__lte=d1), fuel.filter(filled_on__lte=d1)
        first = fuel.first()
        if first is None and not trips.exists():
            raise Http404
        km = sum((t.end_odometer - t.start_odometer) for t in trips)
        out = {"trips": trips.count(), "distance_km": km, "fuel_entries": fuel.count(), "litres": str(fuel.aggregate(s=Sum("litres"))["s"] or 0),
               "litres_per_100km": consumption(fuel)}
        if first is not None and self._show_cost(first):
            out["cost"] = str(fuel.aggregate(s=Sum("cost"))["s"] or 0)
        record_read(request, "vehicle.read_log_summary", entity_type="vehicle_log_summary")
        return Response(out)
