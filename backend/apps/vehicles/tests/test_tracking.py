"""Vehicle position reports (manual / phone): acceptance tests. Synthetic data only."""
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.vehicles.models import VehiclePosition
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
