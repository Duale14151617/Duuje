"""Geofences (entry and exit events) and the daily movement report. Synthetic data only."""
import hashlib
from datetime import datetime, timedelta, timezone as tz
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.vehicles import geofences
from apps.vehicles.models import Geofence, GeofenceEvent, GeofenceState, VehiclePosition
from apps.vehicles.tests.test_vehicles import VehicleBase
from apps.vehicles.tracking import trail_distance_km

URL = "/api/v1/vehicle-tracking/"
FEED = "/api/v1/tracker/feed/"
IN, OUT = ("8.4000", "48.4000"), ("8.4300", "48.4000")  # 3.3 km apart; the fence centre is IN


class FenceBase(VehicleBase):
    def setUp(self):
        super().setUp()
        self.v = self.veh()
        self.base = timezone.now() - timedelta(hours=6)

    def fence(self, name="Main base", radius=1000, alert_on="both", c=None):
        r = (c or self.officer).post(URL + "geofences/add/", {"name": name, "latitude": IN[0], "longitude": IN[1], "radius_m": radius, "alert_on": alert_on}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def report(self, where, minutes, acc=None, vehicle=None):
        """A phone report `minutes` after self.base, made through the API (so events are created the normal way)."""
        v = vehicle or self.v
        body = {"vehicle": str(v.pk), "latitude": where[0], "longitude": where[1], "source": "phone", "recorded_at": (self.base + timedelta(minutes=minutes)).isoformat()}
        if acc is not None:
            body["accuracy_m"] = acc
        r = self.officer.post(URL + "report/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        VehiclePosition.objects.filter(pk=r.data["id"]).update(created_at=timezone.now() - timedelta(minutes=10))  # step past the 20 s flood guard
        return r

    def events(self, **q):
        r = self.officer.get(URL + "geofence-events/", q)
        self.assertEqual(r.status_code, 200, r.data)
        return list(reversed(r.data["results"]))  # oldest first

    def kinds(self, **q):
        return [e["kind"] for e in self.events(**q)]


class FenceCrudTests(FenceBase):
    def test_create_list_and_validate(self):
        f = self.fence()
        self.assertEqual((f["name"], f["radius_m"], f["alert_on"], f["active"]), ("Main base", 1000, "both", True))
        self.assertEqual([x["name"] for x in self.officer.get(URL + "geofences/").data["results"]], ["Main base"])
        bad = [{"name": "main BASE"}, {"name": ""}, {"name": "A", "radius_m": 10}, {"name": "A", "radius_m": "abc"}, {"name": "A", "radius_m": 100001},
               {"name": "A", "latitude": "95"}, {"name": "A", "alert_on": "sometimes"}]
        for extra in bad:
            body = {"name": "Other", "latitude": IN[0], "longitude": IN[1], "radius_m": 500, **extra}
            self.assertEqual(self.officer.post(URL + "geofences/add/", body, format="json").status_code, 400, extra)
        self.assertEqual(Geofence.objects.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.geofence_create").exists())

    def test_permissions(self):
        self.assertEqual(self.member.get(URL + "geofences/").status_code, 403)
        body = {"name": "X", "latitude": IN[0], "longitude": IN[1], "radius_m": 500}
        self.assertEqual(self.member.post(URL + "geofences/add/", body, format="json").status_code, 403)

    def test_update_needs_current_version_and_something_to_change(self):
        f = self.fence()
        url = f"{URL}{f['id']}/geofences/update/"
        self.assertEqual(self.officer.post(url, {"version": f["version"] + 3, "radius_m": 800}, format="json").status_code, 409)
        self.assertEqual(self.officer.post(url, {"version": f["version"]}, format="json").status_code, 400)
        self.fence(name="Second")
        self.assertEqual(self.officer.post(url, {"version": f["version"], "name": "second"}, format="json").status_code, 400)
        r = self.officer.post(url, {"version": f["version"], "radius_m": 800, "name": "HQ base"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["radius_m"], r.data["name"], r.data["version"]), (800, "HQ base", f["version"] + 1))
        self.assertEqual(self.member.post(url, {"version": r.data["version"], "radius_m": 900}, format="json").status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.geofence_update").exists())

    def test_fences_cannot_be_deleted(self):
        from apps.core.appendonly import AppendOnlyError
        self.fence()
        with self.assertRaises(AppendOnlyError):
            Geofence.objects.get().delete()


class CrossingTests(FenceBase):
    def test_first_fix_is_only_a_starting_point(self):
        self.fence()
        self.report(OUT, 0)
        self.assertEqual(self.events(), [])
        self.assertEqual(GeofenceState.objects.count(), 1)

    def test_enter_then_exit_in_time_order(self):
        self.fence()
        for where, m in [(OUT, 0), (IN, 10), (IN, 20), (OUT, 30)]:
            self.report(where, m)
        ev = self.events()
        self.assertEqual([e["kind"] for e in ev], ["enter", "exit"])
        self.assertEqual(ev[0]["geofence"]["name"], "Main base")
        self.assertEqual(ev[0]["vehicle"]["vehicle_id"], self.v.vehicle_id)
        self.assertEqual(ev[0]["latitude"], "8.400000")

    def test_fence_set_to_one_direction_still_tracks_both(self):
        self.fence(alert_on="enter")
        for where, m in [(OUT, 0), (IN, 10), (OUT, 20), (IN, 30)]:
            self.report(where, m)
        self.assertEqual(self.kinds(), ["enter", "enter"])
        self.assertEqual(GeofenceEvent.objects.count(), 2)

    def test_exit_only_fence(self):
        self.fence(alert_on="exit")
        for where, m in [(IN, 0), (OUT, 10), (IN, 20)]:
            self.report(where, m)
        self.assertEqual(self.kinds(), ["exit"])

    def test_late_resent_fix_is_ignored(self):
        self.fence()
        self.report(OUT, 0)
        self.report(IN, 60)
        self.report(OUT, 30)   # older than the 60-minute fix already used: no event, no state change
        self.assertEqual(self.kinds(), ["enter"])
        self.report(OUT, 90)
        self.assertEqual(self.kinds(), ["enter", "exit"])

    def test_fix_less_accurate_than_the_radius_is_skipped(self):
        self.fence(radius=1000)
        self.report(OUT, 0)
        self.report(IN, 10, acc=5000)
        self.assertEqual(self.events(), [])
        self.report(IN, 20, acc=15)
        self.assertEqual(self.kinds(), ["enter"])

    def test_inactive_fence_is_ignored_and_reactivation_starts_fresh(self):
        f = self.fence()
        self.report(OUT, 0)
        off = self.officer.post(f"{URL}{f['id']}/geofences/update/", {"version": f["version"], "active": False}, format="json")
        self.assertFalse(off.data["active"])
        self.report(IN, 10)
        self.assertEqual(self.events(), [])
        on = self.officer.post(f"{URL}{f['id']}/geofences/update/", {"version": off.data["version"], "active": True}, format="json")
        self.assertTrue(on.data["active"])
        self.report(IN, 20)    # first fix after switching on: a new starting point, not an enter
        self.assertEqual(self.events(), [])
        self.report(OUT, 30)
        self.assertEqual(self.kinds(), ["exit"])

    def test_moving_a_fence_clears_starting_points(self):
        f = self.fence()
        self.report(OUT, 0)
        self.officer.post(f"{URL}{f['id']}/geofences/update/", {"version": f["version"], "radius_m": 5000}, format="json")  # now OUT is inside
        self.assertEqual(GeofenceState.objects.count(), 0)
        self.report(OUT, 10)
        self.assertEqual(self.events(), [])

    def test_voided_position_makes_no_event(self):
        self.fence()
        self.report(OUT, 0)
        p = VehiclePosition.objects.create(vehicle=self.v, latitude=IN[0], longitude=IN[1], source="phone", recorded_at=self.base + timedelta(minutes=5),
                                           voided_at=timezone.now(), voided_reason="x")
        self.assertEqual(geofences.evaluate_position(p), [])

    def test_tracker_feed_makes_events_too(self):
        self.fence()
        key = self.officer.post(URL + "trackers/link/", {"vehicle": str(self.v.pk), "device_ref": "355001"}, format="json").data["key"]
        ts = lambda m: int((self.base + timedelta(minutes=m)).timestamp())  # noqa: E731
        for where, m, code in [(OUT, 0, 201), (IN, 10, 201), (IN, 10, None)]:
            r = self.client.get(FEED, {"key": key, "id": "355001", "lat": where[0], "lon": where[1], "timestamp": ts(m)})
            if code:
                self.assertEqual(r.status_code, code)
        self.assertEqual(self.kinds(), ["enter"])    # the resent fix (duplicate) made no second event

    def test_events_are_scoped_filterable_and_audited(self):
        f = self.fence()
        for where, m in [(OUT, 0), (IN, 10), (OUT, 20)]:
            self.report(where, m)
        self.assertEqual(self.nugaal.get(URL + "geofence-events/").data["results"], [])
        self.assertEqual(self.member.get(URL + "geofence-events/").status_code, 403)
        self.assertEqual(len(self.events(vehicle=self.v.vehicle_id)), 2)
        self.assertEqual(len(self.events(geofence=f["id"])), 2)
        self.assertEqual(len(self.events(geofence="00000000-0000-0000-0000-000000000000")), 0)
        self.assertEqual(len(self.events(limit=1)), 1)
        far = (timezone.now() + timedelta(days=2)).date().isoformat()
        self.assertEqual(self.events(**{"from": far}), [])
        for bad in ({"limit": "0"}, {"limit": "501"}, {"limit": "x"}, {"from": "nope"}):
            self.assertEqual(self.officer.get(URL + "geofence-events/", bad).status_code, 400, bad)
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.read_geofence_events").exists())


class DailyReportTests(FenceBase):
    def setUp(self):
        super().setUp()
        self.day = (timezone.now() - timedelta(days=1)).date()
        self.v2 = self.veh(plate="GD-002")

    def at(self, hh, mm=0, day=None):
        return datetime.combine(day or self.day, datetime.min.time(), tzinfo=tz.utc) + timedelta(hours=hh, minutes=mm)

    def mk(self, where, hh, mm=0, place="", acc=None, vehicle=None, day=None):
        p = VehiclePosition.objects.create(vehicle=vehicle or self.v, latitude=where[0], longitude=where[1], source="phone", recorded_at=self.at(hh, mm, day),
                                           place=place, accuracy_m=acc, created_by_username="officer")
        geofences.evaluate_position(p)
        return p

    def scenario(self):
        self.fence()
        self.mk(OUT, 6, 0, place="=cmd()")
        self.mk(IN, 6, 10)
        self.mk(IN, 6, 20)
        self.mk(OUT, 6, 30)
        self.mk(OUT, 7, 30)
        self.mk(IN, 10, 0)    # enters again
        self.mk(IN, 11, 0)    # 60 minutes of silence inside: not counted

    def report(self, **q):
        r = self.officer.get(URL + "daily-report/", {"date": self.day.isoformat(), **q})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_totals_zones_and_not_reporting(self):
        self.scenario()
        rep = self.report()
        s = rep["summary"]
        self.assertEqual((s["vehicles_in_scope"], s["vehicles_reporting"], s["vehicles_not_reporting"], s["positions"], s["zone_events"]), (2, 1, 1, 7, 3))
        row = rep["vehicles"][0]
        self.assertEqual((row["vehicle"]["vehicle_id"], row["positions"]), (self.v.vehicle_id, 7))
        self.assertAlmostEqual(row["distance_km"], 10.01, delta=0.1)
        self.assertEqual(row["first_at"][:16], f"{self.day.isoformat()}T06:00")
        self.assertEqual(row["last_at"][:16], f"{self.day.isoformat()}T11:00")
        self.assertEqual(row["zones"], [{"geofence_id": row["zones"][0]["geofence_id"], "name": "Main base", "minutes_inside": 20, "entered": 2, "left": 1}])
        self.assertEqual([x["vehicle_id"] for x in rep["not_reporting"]], [self.v2.vehicle_id])
        self.assertAlmostEqual(s["distance_km"], row["distance_km"])

    def test_distance_matches_the_route_trail(self):
        self.scenario()
        rows = list(VehiclePosition.objects.filter(vehicle=self.v).order_by("recorded_at"))
        self.assertEqual(self.report()["vehicles"][0]["distance_km"], trail_distance_km(rows))

    def test_voided_positions_and_other_days_are_left_out(self):
        self.scenario()
        VehiclePosition.objects.filter(vehicle=self.v, recorded_at=self.at(11)).update(voided_at=timezone.now(), voided_reason="x")
        self.mk(IN, 12, 0, day=self.day - timedelta(days=1))
        self.assertEqual(self.report()["vehicles"][0]["positions"], 6)

    def test_scope_validation_and_permission(self):
        self.scenario()
        n = self.nugaal.get(URL + "daily-report/", {"date": self.day.isoformat()})
        self.assertEqual((n.data["summary"]["vehicles_in_scope"], n.data["vehicles"]), (0, []))
        self.assertEqual(self.member.get(URL + "daily-report/").status_code, 403)
        for bad in ("nope", (timezone.now() + timedelta(days=3)).date().isoformat()):
            self.assertEqual(self.officer.get(URL + "daily-report/", {"date": bad}).status_code, 400, bad)
        today = self.officer.get(URL + "daily-report/")
        self.assertEqual(today.status_code, 200)
        self.assertEqual(today.data["date"], timezone.now().date().isoformat())
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.read_daily_report").exists())

    def test_day_follows_the_report_time_zone(self):
        try:
            ZoneInfo("Africa/Mogadishu")
        except ZoneInfoNotFoundError:
            self.skipTest("tz database not installed")
        self.mk(OUT, 22, 30, day=self.day - timedelta(days=1))   # 22:30 UTC the day before = 01:30 the next day in Mogadishu (UTC+3)
        self.assertEqual(self.report()["summary"]["positions"], 0)
        with override_settings(REPORT_TIME_ZONE="Africa/Mogadishu"):
            rep = self.report()
            self.assertEqual((rep["timezone"], rep["summary"]["positions"]), ("Africa/Mogadishu", 1))
            self.assertTrue(rep["vehicles"][0]["first_at"].endswith("+03:00"))

    def test_csv_export_is_checksummed_audited_and_defuses_formulas(self):
        self.scenario()
        r = self.officer.get(URL + "daily-report/export/", {"date": self.day.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Content-SHA256"], hashlib.sha256(r.content).hexdigest())
        self.assertIn(f"daily-movement-{self.day.isoformat()}.csv", r["Content-Disposition"])
        text = r.content.decode("utf-8-sig")
        lines = text.strip().splitlines()
        self.assertTrue(lines[0].startswith("date,timezone,vehicle_id"))
        self.assertEqual(len(lines), 3)                       # header + the vehicle that reported + the one that did not
        self.assertIn("'=cmd()", text)
        self.assertNotIn(",=cmd()", text)
        self.assertIn("Main base: 20 min, in 2, out 1", text)
        self.assertIn(self.v2.vehicle_id + ",", text)
        evt = AuditEvent.objects.filter(action="vehicle.export_daily_report").latest("occurred_at")
        self.assertEqual(evt.metadata["sha256"], r["X-Content-SHA256"])
        self.assertEqual(self.member.get(URL + "daily-report/export/", {"date": self.day.isoformat()}).status_code, 403)
        self.assertEqual(self.officer.get(URL + "daily-report/export/", {"date": "nope"}).status_code, 400)
