"""Geofences: circular or polygon zones, and the events made when a vehicle's reported position crosses a zone's edge.

How a crossing is decided (kept simple on purpose, so it can be explained and checked):
  * Each new, non-void position is compared with every active fence. Inside a circle means within radius_m of the centre (great-circle
    distance); inside a polygon means inside its corners (straight edges between corners, even-odd rule).
  * A fix whose accuracy is worse than the fence's radius says nothing reliable about the edge, so it is skipped for that fence.
  * The first usable fix of a vehicle for a fence only sets a starting point: no event. After that, a change from outside to inside is an
    ENTER and inside to outside an EXIT. A fence set to alert on one direction still tracks both, so it never misses the next one.
  * A fix older than the latest one already used (a tracker resending late) is ignored, so events always follow time order.
Events are written in the same transaction as the position. Voiding a position afterwards does not remove an event it caused;
the event keeps its own copy of the place and time and the position's id.
"""
import math

from .models import Geofence, GeofenceEvent, GeofenceState

MIN_STEP_KM = 0.025  # moves shorter than this are GPS drift, not travel (shared with the route trail and the daily report)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def usable(fence, accuracy_m):
    return accuracy_m is None or accuracy_m <= fence.radius_m


def point_in_polygon(points, lat, lon):
    """Even-odd ray test on [[lat, lon], ...]. Edges are straight lines in latitude/longitude, which at the size of a base or a town
    is indistinguishable from true geodesics. A point exactly on an edge may count either way (GPS cannot tell either)."""
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        yi, xi = float(points[i][0]), float(points[i][1])
        yj, xj = float(points[j][0]), float(points[j][1])
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def contains(fence, lat, lon):
    if fence.shape == Geofence.Shape.POLYGON and fence.points:
        return point_in_polygon(fence.points, lat, lon)
    return haversine_km(float(fence.latitude), float(fence.longitude), lat, lon) * 1000 <= fence.radius_m


def evaluate_position(position):
    """Compare one new position with the active fences and record any crossings. Call inside the transaction that created it."""
    if position.voided_at:
        return []
    lat, lon = float(position.latitude), float(position.longitude)
    made = []
    for fence in Geofence.objects.filter(active=True):
        if not usable(fence, position.accuracy_m):
            continue
        now_in = contains(fence, lat, lon)
        state, created = GeofenceState.objects.select_for_update().get_or_create(
            geofence=fence, vehicle_id=position.vehicle_id, defaults={"inside": now_in, "as_of": position.recorded_at})
        if created or position.recorded_at <= state.as_of:
            continue
        if state.inside != now_in:
            kind = GeofenceEvent.Kind.ENTER if now_in else GeofenceEvent.Kind.EXIT
            if fence.alert_on in (Geofence.AlertOn.BOTH, kind.value):
                made.append(GeofenceEvent.objects.create(
                    geofence=fence, vehicle_id=position.vehicle_id, kind=kind, occurred_at=position.recorded_at,
                    latitude=position.latitude, longitude=position.longitude, position_id=position.pk))
                from apps.schedules import alerts  # email to people who switched this alert on; never raises, sent after commit
                alerts.zone_event(made[-1], fence, position.vehicle)
            state.inside = now_in
        state.as_of = position.recorded_at
        state.save(update_fields=["inside", "as_of"])
    return made
