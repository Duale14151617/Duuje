import unittest

from django.conf import settings

if not settings.CUSTODY_ENABLED:  # custody is switched off for now; set CUSTODY_ENABLED=1 to run these tests
    raise unittest.SkipTest("custody is switched off (CUSTODY_ENABLED=0)")

"""Station detention units: verification, cells and capacity, duplicate custody, station-to-station transfer, custody reviews,
oversight dashboards, hierarchy check and the full booking-to-release/transfer workflows. Synthetic data only."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.detention import hierarchy
from apps.detention.facilities import ensure_jail_center
from apps.detention.models import CustodyCell, CustodyFacility, DetentionRecord, id_key
from apps.detention.tests.test_detention import URL, DetentionBase

FAC = "/api/v1/custody-facilities/"
OVR = "/api/v1/detention-oversight/"


class UnitBase(DetentionBase):
    def setUp(self):
        super().setUp()
        self.jail_a = CustodyFacility.objects.create(code="A-JAIL", kind="jail_center", org_unit=self.unit_a, name_en="Jail A", status="operational")
        self.jail_b = CustodyFacility.objects.create(code="B-JAIL", kind="jail_center", org_unit=self.unit_b, name_en="Jail B", status="operational")
        self.regional = self.client_for(self.make_user("reg_cmd", "regional_commander", unit="BARI-ARMY"))
        self.regional_n = self.client_for(self.make_user("reg_cmd_n", "regional_commander", unit="NUGAAL-ARMY"))

    def cell(self, code="C1", capacity=2, fac=None, c=None):
        r = (c or self.officer).post(f"{FAC}{(fac or self.jail_a).pk}/add_cell/", {"code": code, "capacity": capacity}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def audit(self, action):
        return AuditEvent.objects.filter(action=action).exists()


class FacilityStatusTests(UnitBase):
    def test_an_unverified_facility_cannot_hold_people(self):
        self.jail_a.status = "unverified"
        self.jail_a.save()
        self.assertEqual(self.book(facility=str(self.jail_a.pk)).status_code, 400)
        r = self.make()  # the arrest is still recorded, with no verified holding place
        self.assertIsNone(r["facility"])

    @override_settings(DETENTION_REQUIRE_OPERATIONAL_FACILITY=True)
    def test_strict_setting_refuses_booking_without_an_operational_jail(self):
        self.jail_a.status = "unverified"
        self.jail_a.save()
        self.assertEqual(self.book().status_code, 400)

    def test_only_an_authorised_person_verifies_and_it_is_audited(self):
        self.jail_a.status = "unverified"
        self.jail_a.save()
        body = {"status": "operational", "note": "Inspected on site", "version": 1}
        self.assertEqual(self.cmdr.post(f"{FAC}{self.jail_a.pk}/set_status/", body, format="json").status_code, 403)
        self.assertEqual(self.officer.post(f"{FAC}{self.jail_a.pk}/set_status/", body, format="json").status_code, 403)
        self.assertEqual(self.regional_n.post(f"{FAC}{self.jail_a.pk}/set_status/", body, format="json").status_code, 404)  # other region
        self.assertEqual(self.regional.post(f"{FAC}{self.jail_a.pk}/set_status/", {**body, "note": ""}, format="json").status_code, 400)
        ok = self.regional.post(f"{FAC}{self.jail_a.pk}/set_status/", body, format="json")
        self.assertEqual((ok.status_code, ok.data["status"], ok.data["usable"], ok.data["status_by"]), (200, "operational", True, "reg_cmd"))
        self.assertTrue(self.audit("detention.facility_status"))
        self.assertEqual(self.make()["facility"]["code"], "A-JAIL")

    def test_whoever_created_or_changed_a_facility_cannot_verify_it_except_the_super_administrator(self):
        admin = self.client_for(self.make_user("fac_maker", "hq_admin"))
        made = admin.post(FAC, {"kind": "jail_center", "org_unit": str(self.unit_a.pk), "code": "A-JAIL-2", "name_en": "Second"}, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        body = {"status": "operational", "note": "Inspected", "version": made.data["version"]}
        self.assertEqual(admin.post(f"{FAC}{made.data['id']}/set_status/", body, format="json").status_code, 400)  # own work
        self.assertEqual(self.regional.post(f"{FAC}{made.data['id']}/set_status/", body, format="json").status_code, 200)  # someone else
        boss = self.client_for(self.make_user("fac_boss", "super_admin"))
        mine = boss.post(FAC, {"kind": "jail_center", "org_unit": str(self.unit_b.pk), "code": "B-JAIL-2", "name_en": "Boss"}, format="json")
        self.assertEqual(boss.post(f"{FAC}{mine.data['id']}/set_status/", {"status": "operational", "note": "Checked", "version": mine.data["version"]}, format="json").status_code, 200)
        self.assertTrue(self.audit("self_approval.used"))

    def test_a_facility_with_people_in_it_cannot_be_closed(self):
        self.make()
        r = self.regional.post(f"{FAC}{self.jail_a.pk}/set_status/", {"status": "closed", "note": "x", "version": 1}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_unverified_is_not_a_status_one_can_set_and_a_prison_needs_a_global_grant(self):
        prison = CustodyFacility.objects.create(code="P-X", kind="prison", name_en="P")
        self.assertEqual(self.regional.post(f"{FAC}{prison.pk}/set_status/", {"status": "operational", "note": "x", "version": 1}, format="json").status_code, 404)
        admin = self.client_for(self.make_user("fac_adm2", "hq_admin"))
        self.assertEqual(admin.post(f"{FAC}{prison.pk}/set_status/", {"status": "unverified", "note": "x", "version": 1}, format="json").status_code, 400)
        self.assertEqual(admin.post(f"{FAC}{prison.pk}/set_status/", {"status": "operational", "note": "Confirmed", "version": 1}, format="json").status_code, 200)

    def test_handover_to_an_unverified_prison_is_refused_but_free_text_is_allowed(self):
        prison = CustodyFacility.objects.create(code="P-Y", kind="prison", name_en="Y Prison")
        r = self.make()
        self.assertEqual(self.act(r, "close", {"outcome": "transfer_prison", "destination_facility": str(prison.pk)}).status_code, 400)
        self.assertEqual(self.act(r, "close", {"outcome": "transfer_prison", "destination": "Named prison", "outcome_ref": "CO-1"}).status_code, 200)


class CellTests(UnitBase):
    def test_cell_allocation_capacity_and_occupancy(self):
        c = self.cell(capacity=1)
        a = self.make(cell_ref=c["id"])
        self.assertEqual((a["cell"], a["cell_ref"]["code"]), ("C1", "C1"))
        self.assertEqual(self.book(cell_ref=c["id"]).status_code, 400)  # full
        cells = self.officer.get(f"{FAC}{self.jail_a.pk}/cells/").data["results"]
        self.assertEqual((cells[0]["occupied"], cells[0]["available"]), (1, 0))
        fac = [f for f in self.officer.get(FAC).data["results"] if f["code"] == "A-JAIL"][0]
        self.assertEqual((fac["capacity_effective"], fac["held_now"], fac["available"]), (1, 1, 0))
        self.act(a, "close", {"outcome": "no_charge"})  # a release frees the place
        self.assertEqual(self.book(cell_ref=c["id"]).status_code, 201)

    def test_a_cell_of_another_facility_or_a_switched_off_cell_is_refused(self):
        other = self.cell("X1", fac=self.jail_b, c=self.nugaal)
        self.assertEqual(self.book(cell_ref=other["id"]).status_code, 400)
        mine = self.cell("C9")
        self.officer.post(f"{FAC}{self.jail_a.pk}/edit_cell/", {"cell": mine["id"], "active": False, "version": 1}, format="json")
        self.assertEqual(self.book(cell_ref=mine["id"]).status_code, 400)

    def test_moving_between_cells_checks_room_and_logs(self):
        c1, c2 = self.cell("C1", 1), self.cell("C2", 1)
        a, b = self.make(cell_ref=c1["id"]), self.make(cell_ref=c2["id"], detainee_name="B")
        self.assertEqual(self.act(a, "event", {"kind": "cell_move", "cell_ref": c2["id"]}).status_code, 400)  # C2 full
        self.assertEqual(self.act(a, "event", {"kind": "cell_move", "cell_ref": c1["id"]}).status_code, 400)  # already there
        self.act(b, "close", {"outcome": "no_charge"})
        moved = self.act(a, "event", {"kind": "cell_move", "cell_ref": c2["id"]})
        self.assertEqual((moved.status_code, moved.data["cell"]), (201, "C2"))

    def test_cell_rules_on_edit(self):
        c = self.cell(capacity=2)
        self.make(cell_ref=c["id"])
        self.make(cell_ref=c["id"], detainee_name="B")
        e = lambda **kw: self.officer.post(f"{FAC}{self.jail_a.pk}/edit_cell/", {"cell": c["id"], "version": 1, **kw}, format="json")
        self.assertEqual(e(capacity=1).status_code, 400)
        self.assertEqual(e(active=False).status_code, 400)
        self.assertEqual(self.officer.post(f"{FAC}{self.jail_a.pk}/add_cell/", {"code": "c1", "capacity": 3}, format="json").status_code, 400)  # duplicate code
        self.assertEqual(self.officer.post(f"{FAC}{self.jail_a.pk}/add_cell/", {"code": "Z", "capacity": 0}, format="json").status_code, 400)
        self.assertEqual(self.nugaal.post(f"{FAC}{self.jail_a.pk}/add_cell/", {"code": "Q", "capacity": 3}, format="json").status_code, 404)

    def test_over_capacity_is_reported_not_enforced_at_facility_level(self):
        self.jail_a.capacity = 1
        self.jail_a.save()
        self.make()
        self.make(detainee_name="Second")
        fac = [f for f in self.officer.get(FAC).data["results"] if f["code"] == "A-JAIL"][0]
        self.assertTrue(fac["over_capacity"])
        self.assertEqual(fac["available"], 0)

    def test_cells_cannot_be_deleted(self):
        c = CustodyCell.objects.create(facility=self.jail_a, code="D", capacity=1)
        with self.assertRaises(AppendOnlyError):
            c.delete()
        with self.assertRaises(AppendOnlyError):
            self.jail_a.delete()


class DuplicateCustodyTests(UnitBase):
    def test_the_same_person_cannot_be_held_twice_anywhere(self):
        self.make(id_ref="ID-123 45")
        r = self.book(id_ref="id12345")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.book(c=self.nugaal, unit=self.unit_b, id_ref="ID 123-45").status_code, 400)  # at another station too
        self.assertEqual(self.book(id_ref="OTHER-1").status_code, 201)
        self.assertEqual(self.book().status_code, 201)  # no ID given: nothing to compare

    def test_the_id_is_free_again_after_release_transfer_or_void(self):
        a = self.make(id_ref="R-1")
        self.act(a, "close", {"outcome": "no_charge"})
        b = self.make(id_ref="R-1")
        self.act(b, "void", {"reason": "entered by mistake"})
        self.assertEqual(self.book(id_ref="R-1").status_code, 201)

    def test_editing_an_id_into_a_duplicate_is_refused(self):
        self.make(id_ref="E-1")
        b = self.make(id_ref="E-2")
        self.assertEqual(self.act(b, "edit", {"id_ref": "e 1"}).status_code, 400)
        self.assertEqual(self.act(b, "edit", {"id_ref": "E-3"}).status_code, 200)
        self.assertEqual(self.book(id_ref="E-2").status_code, 201)

    def test_the_database_enforces_it_too(self):
        self.make(id_ref="DB-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetentionRecord.objects.create(register_no="DET-X", org_unit=self.unit_a, detainee_name="x", reason="y", booked_at=timezone.now(), id_ref="db1", id_ref_key=id_key("db1"))

    def test_id_key_normalisation(self):
        self.assertEqual(id_key(" so-12 3/4 "), "SO1234")


class TransferTests(UnitBase):
    def test_invalid_transfers_are_refused(self):
        r = self.make()
        close = lambda **kw: self.act(r, "close", {"outcome": "transfer_station", **kw})
        self.assertEqual(close().status_code, 400)  # no destination station
        self.assertEqual(close(destination="Somewhere").status_code, 400)  # free text is not enough
        self.assertEqual(close(destination_unit=str(self.unit_a.pk)).status_code, 400)  # same station
        self.jail_b.status = "unverified"
        self.jail_b.save()
        self.assertEqual(close(destination_unit=str(self.unit_b.pk)).status_code, 400)  # receiving station has no operational jail
        self.assertEqual(self.act(r, "close", {"outcome": "no_charge", "destination_unit": str(self.unit_b.pk)}).status_code, 400)
        self.assertEqual(DetentionRecord.objects.get(pk=r["id"]).status, "in_custody")

    def test_two_step_transfer_to_another_station(self):
        r = self.make(id_ref="T-1", detainee_name="Moved Person", booked_at=(timezone.now() - timedelta(hours=5)).isoformat())
        out = self.act(r, "close", {"outcome": "transfer_station", "destination_unit": str(self.unit_b.pk), "outcome_ref": "TR-9"})
        self.assertEqual((out.status_code, out.data["status"], out.data["awaiting_receipt"], out.data["destination"]), (200, "transferred", True, self.unit_b.name_en))
        self.assertEqual(DetentionRecord.objects.get(pk=r["id"]).id_ref_key, "")  # the ID is released on leaving custody
        inc = self.nugaal.get(URL + "incoming/").data["results"]
        self.assertEqual([x["register_no"] for x in inc], [r["register_no"]])
        self.assertEqual(self.officer.get(URL + "incoming/").data["results"], [])  # the sender is not the receiver
        # only the receiving station can receive
        body = {"version": inc[0]["version"], "facility": str(self.jail_b.pk)}
        self.assertEqual(self.officer.post(f"{URL}{r['id']}/receive/", body, format="json").status_code, 404)
        got = self.nugaal.post(f"{URL}{r['id']}/receive/", body, format="json")
        self.assertEqual(got.status_code, 201, got.data)
        self.assertEqual((got.data["org_unit"]["id"], got.data["received_from"], got.data["status"], got.data["facility"]["code"]),
                         (str(self.unit_b.pk), r["register_no"], "in_custody", "B-JAIL"))
        self.assertNotEqual(got.data["register_no"], r["register_no"])
        self.assertTrue(got.data["held_hours"] >= 5)  # the custody clock carries over
        ev = self.nugaal.get(f"{URL}{got.data['id']}/").data["events"]
        self.assertEqual(ev[0]["kind"], "received")
        # once only
        again = self.nugaal.post(f"{URL}{r['id']}/receive/", body, format="json")
        self.assertEqual(again.status_code, 404)  # no longer incoming
        self.assertEqual(self.nugaal.get(URL + "incoming/").data["results"], [])
        self.assertEqual(self.act(r, "void", {"reason": "wrong"}).status_code, 400)  # cannot void a record already received
        self.assertTrue(self.audit("detention.transfer") and self.audit("detention.receive"))
        # the sending record shows the link
        self.assertEqual(self.officer.get(f"{URL}{r['id']}/").data["received_as"], got.data["register_no"])

    def test_receiving_needs_an_operational_jail_and_a_real_person_in_transit(self):
        r = self.make()
        self.act(r, "close", {"outcome": "transfer_station", "destination_unit": str(self.unit_b.pk)})
        cur = self.nugaal.get(URL + "incoming/").data["results"][0]
        self.jail_b.status = "suspended"
        self.jail_b.save()
        self.assertEqual(self.nugaal.post(f"{URL}{r['id']}/receive/", {"version": cur["version"]}, format="json").status_code, 400)
        rel = self.make(detainee_name="Released")
        self.act(rel, "close", {"outcome": "no_charge"})
        self.assertEqual(self.nugaal.post(f"{URL}{rel['id']}/receive/", {"version": 2}, format="json").status_code, 404)

    def test_stations_endpoint_lists_only_operational_receivers(self):
        ids = {s["id"] for s in self.officer.get(URL + "stations/").data["results"]}
        self.assertEqual(ids, {str(self.unit_a.pk), str(self.unit_b.pk)})
        self.jail_b.status = "unverified"
        self.jail_b.save()
        self.assertEqual({s["id"] for s in self.officer.get(URL + "stations/").data["results"]}, {str(self.unit_a.pk)})


class WorkflowTests(UnitBase):
    def test_booking_to_release_on_bail_is_fully_logged_and_audited(self):
        c = self.cell()
        r = self.make(id_ref="W-1", arrest_place="Market", authority_ref="WARRANT-77", cell_ref=c["id"], property_held="Phone", log_in_ob=False)
        self.assertEqual((r["facility"]["code"], r["authority_ref"], r["recorded_by"]), ("A-JAIL", "WARRANT-77", "custody"))
        for kind, text in (("welfare", "Fed"), ("medical", "Seen by medic"), ("visit", "Family"), ("property", "Phone logged"), ("statement", "Interview 1"), ("review", "")):
            self.assertEqual(self.act(r, "event", {"kind": kind, "text": text}).status_code, 201, kind)
        self.assertEqual(self.act(r, "close", {"outcome": "bail"}).status_code, 400)  # a note is required for bail
        done = self.act(r, "close", {"outcome": "bail", "outcome_note": "Guarantor present", "outcome_ref": "BAIL-5"})
        self.assertEqual((done.status_code, done.data["status"], done.data["outcome_ref"]), (200, "released", "BAIL-5"))
        kinds = [e["kind"] for e in self.officer.get(f"{URL}{r['id']}/").data["events"]]
        self.assertEqual(kinds[0], "booked")
        self.assertEqual(kinds[-1], "released")
        self.assertEqual(set(kinds), {"booked", "welfare", "medical", "visit", "property", "statement", "review", "released"})
        for a in ("detention.book", "detention.event", "detention.release"):
            self.assertTrue(self.audit(a), a)
        self.assertEqual(self.act(r, "event", {"kind": "note", "text": "late"}).status_code, 400)  # nothing more once released

    def test_court_and_prison_handover(self):
        court = self.make()
        self.assertEqual(self.act(court, "close", {"outcome": "transfer_court"}).status_code, 400)  # destination needed
        self.assertEqual(self.act(court, "close", {"outcome": "transfer_court", "destination": "Garowe court", "outcome_ref": "CT-1"}).data["status"], "transferred")
        prison = CustodyFacility.objects.create(code="P-OK", kind="prison", name_en="Ok Prison", status="operational")
        p = self.make(detainee_name="Sentenced")
        done = self.act(p, "close", {"outcome": "transfer_prison", "destination_facility": str(prison.pk)})
        self.assertEqual((done.data["status"], done.data["destination_facility"]["code"]), ("transferred", "P-OK"))

    def test_history_is_never_deleted(self):
        r = self.make()
        with self.assertRaises(AppendOnlyError):
            DetentionRecord.objects.get(pk=r["id"]).delete()
        with self.assertRaises(AppendOnlyError):
            DetentionRecord.objects.get(pk=r["id"]).events.first().delete()

    def test_review_resets_the_overdue_clock(self):
        old = (timezone.now() - timedelta(hours=100)).isoformat()
        r = self.make(booked_at=old)
        self.assertTrue(self.officer.get(f"{URL}{r['id']}/").data["overdue"])
        self.assertEqual(self.officer.get(URL + "?overdue=1").data["count"], 1)
        self.assertEqual(self.officer.get(URL + "summary/").data["overdue"], 1)
        self.act(r, "event", {"kind": "review", "text": "Reviewed by duty officer"})
        got = self.officer.get(f"{URL}{r['id']}/").data
        self.assertFalse(got["overdue"])
        self.assertEqual(got["hours_since_review"], 0)
        self.assertEqual(self.officer.get(URL + "?overdue=1").data["count"], 0)
        self.assertEqual(self.officer.get(URL + "summary/").data["overdue"], 0)

    def test_booking_at_an_inactive_station_is_refused(self):
        self.unit_a.active = False
        self.unit_a.save()
        self.assertEqual(self.book().status_code, 400)


class OversightTests(UnitBase):
    def test_dashboard_is_scoped_and_shows_real_status(self):
        c = self.cell(capacity=3)
        self.make(cell_ref=c["id"])
        self.make(detainee_name="Old", booked_at=(timezone.now() - timedelta(hours=90)).isoformat())
        rel = self.make(detainee_name="Gone")
        self.act(rel, "close", {"outcome": "no_charge"})
        self.jail_b.status = "unverified"
        self.jail_b.save()
        d = self.regional.get(OVR).data
        self.assertEqual([s["unit"]["id"] for s in d["stations"]], [str(self.unit_a.pk)])  # Bari region only
        row = d["stations"][0]
        self.assertEqual((row["facility_state"], row["in_custody"], row["capacity"], row["available"], row["overdue_reviews"], row["admitted"], row["released"]),
                         ("operational", 2, 3, 1, 1, 3, 1))
        self.assertEqual((d["totals"]["in_custody"], d["totals"]["operational"], d["totals"]["unverified"]), (2, 1, 0))
        n = self.regional_n.get(OVR).data
        self.assertEqual((n["stations"][0]["facility_state"], n["totals"]["unverified"]), ("unverified", 1))
        self.assertEqual(self.regional_n.get(f"{OVR}?unit={self.unit_a.pk}").status_code, 404)
        self.assertEqual(self.member.get(OVR).status_code, 403)
        self.assertTrue(self.audit("detention.read_oversight"))

    def test_unplaced_incoming_and_inactive_facilities_are_visible(self):
        self.jail_a.status = "unverified"
        self.jail_a.save()
        self.make()  # held with no verified holding place
        r = self.make(detainee_name="Out", booked_at=timezone.now().isoformat())
        self.jail_a.status = "operational"
        self.jail_a.save()
        row = self.regional.get(OVR).data["stations"][0]
        self.assertEqual(row["held_without_verified_facility"], 2)
        self.act(r, "close", {"outcome": "transfer_station", "destination_unit": str(self.unit_b.pk)})
        self.assertEqual(self.regional_n.get(OVR).data["stations"][0]["incoming"], 1)
        self.assertEqual(self.regional.get(OVR).data["stations"][0]["transferred_out"], 1)
        self.jail_a.active = False
        self.jail_a.save()
        self.assertEqual(self.regional.get(OVR).data["stations"][0]["facility_state"], "out_of_use")

    def test_station_commander_sees_only_their_station(self):
        self.make()
        d = self.cmdr.get(OVR).data
        self.assertEqual(len(d["stations"]), 1)
        self.assertEqual(d["totals"]["in_custody"], 1)

    def test_hierarchy_findings_need_a_global_grant(self):
        self.assertEqual(self.regional.get(OVR + "hierarchy/").status_code, 404)
        admin = self.client_for(self.make_user("hier_adm", "hq_admin"))
        self.assertEqual(admin.get(OVR + "hierarchy/").status_code, 200)


class HierarchyAndSetupTests(TestCase):
    """Custody sits on the Urur (battalion) of the Army structure; the structure itself is not changed by the custody module."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference_data", verbosity=0)
        call_command("apply_army_structure", "--apply", stdout=StringIO())

    def ururs(self):
        from apps.organization.models import OrganizationalUnit as OU
        return OU.objects.filter(unit_type__code="URUR", active=True)

    def test_every_active_urur_has_a_correct_parent_region_and_jail_record(self):
        res = hierarchy.check()
        self.assertEqual(res["errors"], 0, [f for f in res["findings"] if f["severity"] == "error"])
        by_id = hierarchy.index()
        self.assertTrue(self.ururs().exists())
        for st in self.ururs():
            region, _guuto, _ = hierarchy.lineage(st, by_id)
            self.assertIsNotNone(region, st.code)
            self.assertTrue(st.path.startswith(st.parent.path))
            self.assertEqual(CustodyFacility.objects.filter(org_unit=st, kind="jail_center").count(), 1, st.code)

    def test_automatic_jail_records_are_unverified_so_nothing_is_assumed_operational(self):
        self.assertFalse(CustodyFacility.objects.filter(kind="jail_center", status="operational").exists())
        res = hierarchy.check()
        self.assertTrue(any(f["code"] == "no_operational_jail" for f in res["findings"]))
        self.assertTrue(all(not f.usable for f in CustodyFacility.objects.all()))

    def test_setup_is_safe_to_rerun(self):
        before = (CustodyFacility.objects.count(), CustodyFacility.objects.filter(kind="prison").count())
        for _ in range(2):
            call_command("apply_custody_facilities", stdout=StringIO())
            call_command("apply_army_structure", "--apply", stdout=StringIO())
        self.assertEqual((CustodyFacility.objects.count(), CustodyFacility.objects.filter(kind="prison").count()), before)

    def test_ensure_jail_center_never_adds_a_second_jail_or_edits_one(self):
        st = self.ururs().first()
        fac = CustodyFacility.objects.get(org_unit=st)
        fac.code, fac.name_en = "CUSTOM-CODE", "Renamed by admin"
        fac.save()
        got, created = ensure_jail_center(st)
        self.assertFalse(created)
        self.assertEqual((got.pk, CustodyFacility.objects.filter(org_unit=st).count(), CustodyFacility.objects.get(pk=fac.pk).name_en), (fac.pk, 1, "Renamed by admin"))

    def test_a_misplaced_urur_is_reported_and_strict_mode_fails(self):
        from apps.organization.models import OrganizationalUnit as OU, UnitType
        office = OU.objects.filter(unit_type__code="URUR_HOWLGELIN").first()
        bad = OU.objects.create(code="BAD-URUR", name_en="Misplaced", level=OU.Level.UNIT, parent=office, branch=office.branch,
                                unit_type=UnitType.objects.get(code="URUR"))
        codes = {(f["code"], f["unit"]) for f in hierarchy.check()["findings"]}
        self.assertIn(("wrong_parent_type", "BAD-URUR"), codes)
        with self.assertRaises(CommandError):
            call_command("verify_station_hierarchy", "--strict", stdout=StringIO())
        call_command("verify_station_hierarchy", stdout=StringIO())  # without --strict it only reports
        self.assertTrue(CustodyFacility.objects.filter(org_unit=bad).exists())  # a new Urur still gets its jail record, unverified
