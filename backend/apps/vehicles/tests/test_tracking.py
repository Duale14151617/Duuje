"""Vehicle position reports (manual / phone): acceptance tests."""
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.vehicles.models import VehiclePosition, VehicleTracker
from apps.vehicles.tracking import trail_distance_km
from apps.vehicles.tests.test_vehicles import VehicleBase

URL = "/api/v1/vehicle-tracking/"


class TrackingTests(VehicleBase):
    def setUp(self):
        super().setUp()
        self.v = self.veh()
        VehiclePosition.objects.all()  # table exists

    def report(self, c=None, **kw):
        body = {"vehicle": str(self.v.pk), "latitude": "8.405500", "longitude": "48.483700", "source": "phone", **kw}
        return (c or self.officer).post(URL + "report/", body, format="json")

    def test_report_and_latest(self):
        r = self.report(accuracy_m="12")
        self.assertEqual(r.status_code, 201, r.data)
        latest = self.officer.get(URL + "latest/").data["results"]
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["latitude"], "8.405500")
        self.assertFalse(latest[0]["stale"])
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.position_report").exists())

    def test_validation(self):
        self.assertEqual(self.report(latitude="91").status_code, 400)
        self.assertEqual(self.report(longitude="-181").status_code, 400)
        self.assertEqual(self.report(latitude="abc").status_code, 400)
        self.assertEqual(self.report(source="satellite").status_code, 400)
        self.assertEqual(self.report(recorded_at=(timezone.now() + timedelta(hours=2)).isoformat()).status_code, 400)

    def test_flood_guard(self):
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(self.report().status_code, 400)

    def test_newest_wins_and_void_falls_back(self):
        old = self.report(recorded_at=(timezone.now() - timedelta(hours=3)).isoformat(), place="Old")
        VehiclePosition.objects.filter(pk=old.data["id"]).update(created_at=timezone.now() - timedelta(minutes=5))
        new = self.report(place="New")
        self.assertEqual(new.status_code, 201, new.data)
        self.assertEqual(self.officer.get(URL + "latest/").data["results"][0]["place"], "New")
        v = self.officer.post(f"{URL}{new.data['id']}/void/", {"version": 1, "reason": "Wrong spot"}, format="json")
        self.assertEqual(v.status_code, 200, v.data)
        self.assertEqual(self.officer.get(URL + "latest/").data["results"][0]["place"], "Old")
        self.assertEqual(len(self.officer.get(f"{URL}history/?vehicle={self.v.pk}").data["results"]), 1)

    def test_position_joins_open_trip(self):
        t = self.officer.post("/api/v1/vehicle-log/trips/start/", {"vehicle": str(self.v.pk), "purpose": "Patrol", "start_odometer": 100}, format="json")
        self.assertEqual(t.status_code, 201, t.data)
        self.assertEqual(self.report().data["trip_id"], t.data["id"])

    def test_scope_and_permissions(self):
        self.report()
        self.assertEqual(len(self.nugaal.get(URL + "latest/").data["results"]), 0)
        self.assertEqual(self.report(c=self.nugaal).status_code, 400)  # unknown to that region
        self.assertEqual(self.report(c=self.member).status_code, 403)
        self.assertEqual(self.member.get(URL + "latest/").status_code, 403)


class TrackerFeedTests(VehicleBase):
    FEED = "/api/v1/tracker/feed/"

    def setUp(self):
        super().setUp()
        self.v = self.veh()

    def link(self, ref="355001", c=None):
        return (c or self.officer).post(URL + "trackers/link/", {"vehicle": str(self.v.pk), "device_ref": ref}, format="json")

    def test_link_shows_key_once_and_feed_stores_position(self):
        r = self.link()
        self.assertEqual(r.status_code, 201, r.data)
        key = r.data["key"]
        self.assertTrue(key.startswith("trk_"))
        self.assertNotIn("key", self.officer.get(URL + "trackers/").data["results"][0])
        ts = int(timezone.now().timestamp())
        f = self.client.get(self.FEED, {"key": key, "id": "355001", "lat": "8.4055", "lon": "48.4837", "timestamp": ts, "accuracy": "9"})
        self.assertEqual(f.status_code, 201, f.data)
        again = self.client.get(self.FEED, {"key": key, "id": "355001", "lat": "8.4055", "lon": "48.4837", "timestamp": ts})
        self.assertEqual(again.data["status"], "duplicate")
        latest = self.officer.get(URL + "latest/").data["results"][0]
        self.assertEqual((latest["source"], latest["latitude"]), ("tracker", "8.405500"))
        self.assertIsNotNone(self.officer.get(URL + "trackers/").data["results"][0]["last_seen_at"])

    def test_wrong_key_wrong_device_and_off_are_refused(self):
        key = self.link().data["key"]
        q = {"id": "355001", "lat": "8.4", "lon": "48.4"}
        self.assertEqual(self.client.get(self.FEED, {**q, "key": "trk_deadbeef_x"}).status_code, 401)
        self.assertEqual(self.client.get(self.FEED, {**q, "key": key, "id": "other"}).status_code, 401)
        self.assertEqual(self.client.get(self.FEED, q).status_code, 401)
        self.assertEqual(self.client.get(self.FEED, {**q, "key": key, "lat": "95"}).status_code, 400)
        t = self.officer.get(URL + "trackers/").data["results"][0]
        off = self.officer.post(f"{URL}{t['id']}/trackers/off/", {"version": t["version"]}, format="json")
        self.assertEqual(off.status_code, 200, off.data)
        self.assertEqual(self.client.get(self.FEED, {**q, "key": key}).status_code, 401)
        self.assertEqual(VehiclePosition.objects.count(), 0)

    def test_device_can_only_be_linked_once_and_scope_applies(self):
        self.assertEqual(self.link().status_code, 201)
        self.assertEqual(self.link().status_code, 400)
        self.assertEqual(self.link(ref="2", c=self.nugaal).status_code, 400)
        self.assertEqual(len(self.nugaal.get(URL + "trackers/").data["results"]), 0)
        self.assertEqual(self.link(ref="3", c=self.member).status_code, 403)


class SilentTrailRotateTests(VehicleBase):
    """Silent-vehicle alert, route trail with distance, and tracker key rotation."""
    FEED = "/api/v1/tracker/feed/"

    def setUp(self):
        super().setUp()
        self.v = self.veh()

    def report(self, lat, lon, hours_ago=0, c=None):
        r = (c or self.officer).post(URL + "report/", {"vehicle": str(self.v.pk), "latitude": lat, "longitude": lon, "source": "phone",
                                                        "recorded_at": (timezone.now() - timedelta(hours=hours_ago)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        VehiclePosition.objects.filter(pk=r.data["id"]).update(created_at=timezone.now() - timedelta(minutes=30 + int(hours_ago * 60)))
        return r

    def link(self, ref="355001"):
        return self.officer.post(URL + "trackers/link/", {"vehicle": str(self.v.pk), "device_ref": ref}, format="json")

    # ---- silent -------------------------------------------------------------------------------------------------------------
    def test_never_reported_vehicle_is_silent(self):
        r = self.officer.get(URL + "silent/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([x["id"] for x in r.data["vehicles"]], [str(self.v.pk)])
        self.assertTrue(r.data["vehicles"][0]["never"])

    def test_recent_report_clears_it_and_old_one_does_not(self):
        self.report("8.4055", "48.4837")
        self.assertEqual(self.officer.get(URL + "silent/").data["vehicles"], [])
        VehiclePosition.objects.update(recorded_at=timezone.now() - timedelta(hours=30))
        r = self.officer.get(URL + "silent/")
        self.assertEqual(len(r.data["vehicles"]), 1)
        self.assertFalse(r.data["vehicles"][0]["never"])
        self.assertGreaterEqual(r.data["vehicles"][0]["age_minutes"], 30 * 60 - 1)
        self.assertEqual(self.officer.get(URL + "silent/?hours=48").data["vehicles"], [])

    def test_silent_validates_hours_scope_and_permission(self):
        self.assertEqual(self.officer.get(URL + "silent/?hours=abc").status_code, 400)
        self.assertEqual(self.officer.get(URL + "silent/?hours=0").status_code, 400)
        self.assertEqual(self.officer.get(URL + "silent/?hours=721").status_code, 400)
        self.assertEqual(len(self.nugaal.get(URL + "silent/").data["vehicles"]), 0)
        self.assertEqual(self.member.get(URL + "silent/").status_code, 403)

    def test_workshop_vehicle_is_not_flagged(self):
        from apps.vehicles.models import Vehicle
        Vehicle.objects.filter(pk=self.v.pk).update(status="under_repair")
        self.assertEqual(self.officer.get(URL + "silent/").data["vehicles"], [])

    def test_quiet_tracker_is_listed(self):
        self.link()
        self.assertEqual(self.officer.get(URL + "silent/").data["trackers"], [])  # just linked: not quiet yet
        VehicleTracker.objects.update(created_at=timezone.now() - timedelta(hours=30))
        self.assertEqual(len(self.officer.get(URL + "silent/").data["trackers"]), 1)
        VehicleTracker.objects.update(last_seen_at=timezone.now())
        self.assertEqual(self.officer.get(URL + "silent/").data["trackers"], [])

    # ---- trail --------------------------------------------------------------------------------------------------------------
    def test_trail_is_oldest_first_with_distance(self):
        self.report("8.4000", "48.4000", hours_ago=3)
        self.report("8.4500", "48.4000", hours_ago=2)  # about 5.56 km north
        self.report("8.5000", "48.4000", hours_ago=1)  # another 5.56 km
        r = self.officer.get(f"{URL}trail/?vehicle={self.v.pk}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([p["latitude"] for p in r.data["points"]], ["8.400000", "8.450000", "8.500000"])
        self.assertFalse(r.data["truncated"])
        self.assertAlmostEqual(r.data["distance_km"], 11.12, delta=0.1)

    def test_trail_ignores_gps_drift_and_voided_rows(self):
        class P:  # noqa: N801 - tiny stand-in for a row
            def __init__(self, lat, lon):
                self.latitude, self.longitude = lat, lon
        drift = [P("8.400000", "48.400000"), P("8.400050", "48.400050"), P("8.400100", "48.399950")]
        self.assertEqual(trail_distance_km(drift), 0.0)
        self.assertEqual(trail_distance_km([]), 0.0)
        a = self.report("8.4000", "48.4000", hours_ago=2)
        self.report("8.5000", "48.4000", hours_ago=1)
        self.officer.post(f"{URL}{a.data['id']}/void/", {"version": 1, "reason": "Wrong spot"}, format="json")
        r = self.officer.get(f"{URL}trail/?vehicle={self.v.pk}")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["distance_km"], 0.0)

    def test_trail_requires_vehicle_and_respects_scope_and_dates(self):
        self.report("8.4000", "48.4000", hours_ago=1)
        self.assertEqual(self.officer.get(URL + "trail/").status_code, 400)
        self.assertEqual(self.officer.get(f"{URL}trail/?vehicle={self.v.pk}&from=not-a-date").status_code, 400)
        self.assertEqual(self.nugaal.get(f"{URL}trail/?vehicle={self.v.pk}").data["count"], 0)
        self.assertEqual(self.member.get(f"{URL}trail/?vehicle={self.v.pk}").status_code, 403)
        future = (timezone.now() + timedelta(days=2)).date().isoformat()
        self.assertEqual(self.officer.get(f"{URL}trail/?vehicle={self.v.pk}&from={future}").data["count"], 0)

    def test_trail_truncates_to_newest_points(self):
        from apps.vehicles import tracking
        old = tracking.TRAIL_MAX
        tracking.TRAIL_MAX = 2
        try:
            for h in (3, 2, 1):
                self.report(f"8.{h}000", "48.4000", hours_ago=h)
            r = self.officer.get(f"{URL}trail/?vehicle={self.v.pk}")
            self.assertTrue(r.data["truncated"])
            self.assertEqual(r.data["count"], 2)
            self.assertEqual(r.data["points"][0]["latitude"], "8.200000")
        finally:
            tracking.TRAIL_MAX = old

    # ---- rotate -------------------------------------------------------------------------------------------------------------
    def test_rotate_replaces_key_and_old_one_stops_working(self):
        old = self.link().data["key"]
        t = self.officer.get(URL + "trackers/").data["results"][0]
        r = self.officer.post(f"{URL}{t['id']}/trackers/rotate/", {"version": t["version"]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        new = r.data["key"]
        self.assertNotEqual(old, new)
        self.assertTrue(new.startswith("trk_"))
        self.assertEqual(r.data["version"], t["version"] + 1)
        self.assertNotIn("key", self.officer.get(URL + "trackers/").data["results"][0])
        q = {"id": "355001", "lat": "8.4055", "lon": "48.4837"}
        self.assertEqual(self.client.get(self.FEED, {**q, "key": old}).status_code, 401)
        self.assertEqual(self.client.get(self.FEED, {**q, "key": new}).status_code, 201)
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.tracker_rotate").exists())

    def test_rotate_needs_current_version_active_tracker_and_permission(self):
        self.link()
        t = self.officer.get(URL + "trackers/").data["results"][0]
        stale = self.officer.post(f"{URL}{t['id']}/trackers/rotate/", {"version": t["version"] + 5}, format="json")
        self.assertEqual(stale.status_code, 409, stale.data)
        self.assertEqual(self.member.post(f"{URL}{t['id']}/trackers/rotate/", {"version": t["version"]}, format="json").status_code, 403)
        self.assertEqual(self.nugaal.post(f"{URL}{t['id']}/trackers/rotate/", {"version": t["version"]}, format="json").status_code, 404)
        off = self.officer.post(f"{URL}{t['id']}/trackers/off/", {"version": t["version"]}, format="json")
        again = self.officer.post(f"{URL}{t['id']}/trackers/rotate/", {"version": off.data["version"]}, format="json")
        self.assertEqual(again.status_code, 400, again.data)
