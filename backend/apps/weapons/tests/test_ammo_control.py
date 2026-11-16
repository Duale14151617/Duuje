"""Ammunition control: events that must balance, warning flags, lot and weapon trace. Synthetic data only."""
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.weapons.models import AmmoEvent, SoldierRounds
from apps.weapons.tests.test_rounds import RoundsBase
from apps.weapons.tests.test_weapons import W

C = "/api/v1/ammo-control/"


class AmmoControlBase(RoundsBase):
    def new_event(self, name="Range practice", day=None, unit=None):
        r = self.armourer.post(f"{C}create-event/", {"name": name, "org_unit": str((unit or self.unit_a).pk),
                                                      "event_date": (day or timezone.localdate()).isoformat()}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def summary(self, event_id):
        r = self.armourer.get(f"{C}event/", {"id": event_id})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def close(self, event_id):
        return self.armourer.post(f"{C}close-event/", {"id": event_id}, format="json")


class EventTests(AmmoControlBase):
    def test_an_event_must_balance_before_it_can_close(self):
        ev = self.new_event()
        self.assertEqual(self.give(90, "V1", event=ev).status_code, 201)
        self.assertEqual(self.summary(ev)["totals"]["outstanding"], 90)
        refused = self.close(ev)
        self.assertEqual((refused.status_code, self.codes(refused, "event")), (400, ["event_not_reconciled"]))
        self.assertEqual(self.rounds("expended", 60, note="Range practice", event=ev).status_code, 201)
        self.assertEqual(self.rounds("return", 30, reference="R1", event=ev).status_code, 201)
        s = self.summary(ev)
        self.assertTrue(s["balanced"])
        self.assertEqual((s["totals"]["issued"], s["totals"]["expended"], s["totals"]["returned"]), (90, 60, 30))
        self.assertEqual(self.close(ev).status_code, 200)
        self.assertEqual(AmmoEvent.objects.get(pk=ev).status, "closed")
        self.assertTrue(AuditEvent.objects.filter(action="weapon.ammo_event_close").exists())

    def test_cannot_use_a_closed_event_or_write_off_more_than_was_drawn_under_it(self):
        ev = self.new_event()
        self.give(90, "V1")  # drawn with no event
        self.give(10, "V2", event=ev)
        over = self.rounds("expended", 50, note="x", event=ev)  # holds 100 in total but only 10 under this event
        self.assertEqual(self.codes(over, "quantity"), ["rounds_exceed_event"])
        self.rounds("expended", 10, note="x", event=ev)
        self.assertEqual(self.close(ev).status_code, 200)
        late = self.give(5, "V3", event=ev)
        self.assertEqual(self.codes(late, "event"), ["event_closed"])

    def test_event_for_a_soldier_outside_the_events_unit_is_refused(self):
        ev = self.new_event(unit=self.unit_a)
        r = self.give(10, "V1", person=self.away, event=ev)
        self.assertIn(r.status_code, (400, 404))
        self.assertFalse(SoldierRounds.objects.filter(personnel=self.away).exists())

    def test_rounds_without_an_event_still_work_as_before(self):
        self.assertEqual(self.give(90, "V1").status_code, 201)
        self.assertEqual(self.rounds("expended", 30, note="Range practice").status_code, 201)


class FlagTests(AmmoControlBase):
    def flags(self):
        r = self.armourer.get(f"{C}flags/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_expended_with_no_event_is_flagged_but_with_an_event_is_not(self):
        self.give(100, "V1")
        self.rounds("expended", 20, note="Range")
        f = self.flags()
        self.assertEqual([(x["personnel"]["service_number"], x["rounds"]) for x in f["expended_without_event"]], [("S-1", 20)])
        ev = self.new_event()
        self.give(50, "V2", person=self.s2, event=ev)
        self.rounds("expended", 50, person=self.s2, note="Range", event=ev)
        self.assertEqual(len(self.flags()["expended_without_event"]), 1)

    def test_repeated_losses_are_flagged(self):
        self.give(100, "V1")
        for i in range(2):
            self.assertEqual(self.rounds("lost", 5, note="Lost in the field", authority_ref=f"Board {i}").status_code, 201)
        self.assertEqual([x["entries"] for x in self.flags()["repeated_loss"]], [2])

    def test_a_heavy_draw_is_flagged_only_against_peers(self):
        peers = [self.person("BARI-ARMY-A", f"Peer {i}", service_number=f"P-{i}") for i in range(3)]
        for i, p in enumerate(peers):
            self.give(100, f"VP{i}", person=p)
        self.give(500, "VBIG", person=self.s1)
        f = self.flags()["heavy_draw"]
        self.assertEqual([(x["personnel"]["service_number"], x["rounds"]) for x in f], [("S-1", 500)])

    def test_an_event_left_open_is_flagged(self):
        self.new_event(day=timezone.localdate() - timedelta(days=5))
        self.new_event(name="Today")
        self.assertEqual([e["name"] for e in self.flags()["events_overdue"]], ["Range practice"])


class TraceTests(AmmoControlBase):
    def test_lot_trace_shows_who_drew_the_lot(self):
        self.give(90, "V1", lot="LOT-77")
        self.give(40, "V2", person=self.s2, lot="lot-77")
        r = self.armourer.get(f"{C}trace/", {"lot": "LOT-77"})
        self.assertEqual(r.status_code, 200, r.content)
        who = sorted(i["personnel"]["service_number"] for i in r.json()["lot"]["issues"])
        self.assertEqual(who, ["S-1", "S-2"])
        self.assertEqual(self.armourer.get(f"{C}trace/", {"lot": "NO-SUCH"}).json()["lot"]["issues"], [])

    def test_weapon_trace_names_the_holder_at_the_time_and_the_rounds_they_held(self):
        asset = self.weapon("AK-0001")
        self.assertEqual(self.issue(asset, person=self.s1).status_code, 201)
        self.give(90, "V1", lot="LOT-9")
        later = (timezone.now() + timedelta(minutes=5)).isoformat()
        r = self.armourer.get(f"{C}trace/", {"serial": "ak-0001", "at": later})
        self.assertEqual(r.status_code, 200, r.content)
        w = r.json()["weapon"]
        self.assertEqual(w["holder_at_time"]["personnel"]["service_number"], "S-1")
        self.assertEqual([x["rounds"] for x in w["rounds_held_at_time"]], [90])
        self.assertEqual(w["rounds_drawn_in_previous_7_days"][0]["lot"], "LOT-9")
        before = (timezone.now() - timedelta(days=1)).isoformat()
        self.assertIsNone(self.armourer.get(f"{C}trace/", {"serial": "AK-0001", "at": before}).json()["weapon"]["holder_at_time"])

    def test_trace_needs_a_serial_or_lot_and_is_audited(self):
        self.assertEqual(self.armourer.get(f"{C}trace/").status_code, 400)
        self.armourer.get(f"{C}trace/", {"lot": "X"})
        self.assertTrue(AuditEvent.objects.filter(action="weapon.read_ammo_trace").exists())

    def test_people_outside_scope_see_nothing(self):
        self.give(90, "V1", lot="LOT-5")
        outsider = self.client_for(self.make_user("outsider", "weapons_custodian", unit="BARI-ARMY-B"))
        r = outsider.get(f"{C}trace/", {"lot": "LOT-5"})
        self.assertEqual(r.json()["lot"]["issues"], [])
        self.assertEqual(outsider.get(f"{C}events/").json()["results"], [])


from django.test import override_settings  # noqa: E402


class LotTests(AmmoControlBase):
    def receive(self, qty, ref, lot):
        return self.armourer.post(f"/api/v1/logistics/ammunition/{self.line.pk}/movement/",
                                  {"kind": "receive", "quantity": qty, "external_ref": ref, "lot": lot}, format="json")

    def test_a_lot_can_be_traced_back_to_its_delivery(self):
        self.assertEqual(self.receive(500, "DN-1", "LOT-A").status_code, 201)
        self.give(90, "V1", lot="LOT-A")
        r = self.armourer.get(f"{C}trace/", {"lot": "lot-a"}).json()["lot"]
        self.assertEqual([(x["rounds"], x["reference"]) for x in r["received"]], [(500, "DN-1")])
        self.assertEqual([x["rounds"] for x in r["in_store"]], [410])
        self.assertEqual([x["personnel"]["service_number"] for x in r["issues"]], ["S-1"])

    def test_once_receipts_carry_lots_only_a_lot_with_stock_can_be_issued(self):
        self.receive(100, "DN-1", "LOT-A")
        unknown = self.give(10, "V1", lot="LOT-NOPE")
        self.assertEqual(self.codes(unknown, "lot"), ["lot_unknown"])
        too_many = self.give(150, "V2", lot="LOT-A")
        self.assertEqual(self.codes(too_many, "lot"), ["lot_insufficient"])
        self.assertEqual(self.give(60, "V3", lot="LOT-A").status_code, 201)
        self.assertEqual(self.codes(self.give(60, "V4", lot="LOT-A"), "lot"), ["lot_insufficient"])

    def test_the_issue_form_is_offered_the_lots_in_store(self):
        self.receive(100, "DN-1", "LOT-A")
        self.receive(40, "DN-2", "LOT-B")
        r = self.armourer.get(f"{W}ammo_lines/", {"org_unit": str(self.unit_a.pk)}).json()["results"][0]
        self.assertEqual({x["lot"]: x["quantity"] for x in r["lots"]}, {"LOT-A": 100, "LOT-B": 40})

    @override_settings(AMMO_REQUIRE_LOT=True)
    def test_when_required_receipts_and_issues_must_name_a_lot(self):
        no_lot = self.armourer.post(f"/api/v1/logistics/ammunition/{self.line.pk}/movement/",
                                    {"kind": "receive", "quantity": 10, "external_ref": "DN-9"}, format="json")
        self.assertEqual(self.codes(no_lot, "lot"), ["lot_required"])
        self.assertEqual(self.codes(self.give(10, "V1"), "lot"), ["lot_required"])

    def test_without_the_switch_lots_stay_optional(self):
        self.assertEqual(self.give(10, "V1").status_code, 201)

    def test_draws_without_a_lot_or_event_are_flagged(self):
        self.give(10, "V1")
        f = self.armourer.get(f"{C}flags/").json()
        self.assertEqual([(x["personnel"]["service_number"], x["rounds"]) for x in f["issued_without_lot"]], [("S-1", 10)])
        self.assertEqual(len(f["issued_without_event"]), 1)
        ev = self.new_event()
        self.give(10, "V2", person=self.s2, lot="L", event=ev)
        f = self.armourer.get(f"{C}flags/").json()
        self.assertEqual(len(f["issued_without_lot"]), 1)
        self.assertEqual(len(f["issued_without_event"]), 1)
