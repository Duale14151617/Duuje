"""Court dates and remand, case link and charge, custody incidents, cell warnings, period reports and printing audit. Synthetic data only."""
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.detention.models import CourtHearing, CustodyCell, CustodyIncident, DetentionRecord
from apps.detention.tests.test_custody_units import FAC, OVR, UnitBase
from apps.detention.tests.test_detention import URL

INC = "/api/v1/custody-incidents/"
iso = lambda **kw: (timezone.now() + timedelta(**kw)).isoformat()


class CourtTests(UnitBase):
    def hearing(self, r, **kw):
        return self.act(r, "hearing", kw)

    def test_a_remand_needs_who_ordered_it_and_a_date(self):
        r = self.make()
        self.assertEqual(self.hearing(r, purpose="remand", remand_until=str((timezone.localdate() + timedelta(days=5)))).status_code, 400)  # no ordering authority
        self.assertEqual(self.hearing(r, purpose="remand", ordered_by="Judge A").status_code, 400)  # no date at all
        ok = self.hearing(r, purpose="remand", ordered_by="Judge A", order_ref="RO-1", court="Garowe court", remand_until=str(timezone.localdate() + timedelta(days=5)))
        self.assertEqual(ok.status_code, 201, ok.data)
        got = self.officer.get(f"{URL}{r['id']}/").data
        self.assertEqual((got["hearings"][0]["ordered_by"], got["hearings"][0]["order_ref"], got["remand_expired"]), ("Judge A", "RO-1", False))
        self.assertIn("court", [e["kind"] for e in got["events"]])
        self.assertTrue(self.audit("detention.court_add"))

    def test_flags_only_show_what_the_court_gave(self):
        a, b, c, d = self.make(), self.make(detainee_name="B"), self.make(detainee_name="C"), self.make(detainee_name="D")
        self.hearing(a, hearing_at=iso(hours=20), court="X")  # within the reminder window
        self.hearing(b, hearing_at=iso(days=10))  # later, no reminder
        self.hearing(c, purpose="remand", ordered_by="Judge", remand_until=str(timezone.localdate() - timedelta(days=1)))  # ran out
        flags = lambda x: self.officer.get(f"{URL}{x['id']}/").data
        self.assertTrue(flags(a)["court_soon"])
        self.assertFalse(flags(b)["court_soon"])
        self.assertTrue(flags(c)["remand_expired"])
        self.assertFalse(flags(d)["remand_expired"] or flags(d)["court_soon"])  # nothing was recorded, nothing is flagged
        cal = self.officer.get(URL + "court/").data["results"]
        self.assertEqual([x["register_no"] for x in cal][0], c["register_no"])  # a passed remand comes first
        self.assertEqual({x["register_no"] for x in cal}, {a["register_no"], b["register_no"], c["register_no"]})
        self.assertEqual(self.nugaal.get(URL + "court/").data["results"], [])  # other region sees nothing
        row = self.regional.get(OVR).data["stations"][0]
        self.assertEqual((row["court_soon"], row["remand_expired"]), (1, 1))

    def test_recording_what_happened_to_a_court_date(self):
        r = self.make()
        self.hearing(r, hearing_at=iso(hours=5), court="X")
        h = self.officer.get(f"{URL}{r['id']}/").data["hearings"][0]
        upd = lambda **kw: self.act(r, "hearing_update", {"hearing": h["id"], "hearing_version": h["version"], **kw})
        self.assertEqual(upd(status="adjourned", note="Judge absent").status_code, 400)  # needs the new date
        self.assertEqual(upd(status="adjourned", note="Judge absent", new_hearing_at=iso(days=7)).status_code, 200)
        got = self.officer.get(f"{URL}{r['id']}/").data
        self.assertEqual(sorted(x["status"] for x in got["hearings"]), ["adjourned", "scheduled"])
        self.assertEqual(upd(status="held").status_code, 409)  # stale version of the old date
        old = [x for x in got["hearings"] if x["status"] == "adjourned"][0]
        self.assertEqual(self.act(r, "hearing_update", {"hearing": old["id"], "hearing_version": old["version"], "status": "held"}).status_code, 400)  # no longer scheduled
        with self.assertRaises(AppendOnlyError):
            CourtHearing.objects.first().delete()

    def test_permissions_and_state(self):
        r = self.make()
        self.assertEqual(self.act(r, "hearing", {"hearing_at": iso(days=1)}, c=self.nugaal).status_code, 404)
        self.assertEqual(self.act(r, "hearing", {"hearing_at": iso(days=1)}, c=self.regional).status_code, 403)  # reads only
        self.assertEqual(self.act(r, "hearing", {"hearing_at": iso(days=1)}, c=self.cmdr).status_code, 201)  # station commander manages
        self.act(r, "close", {"outcome": "no_charge"})
        self.assertEqual(self.act(r, "hearing", {"hearing_at": iso(days=1)}).status_code, 400)


class CaseAndChargeTests(UnitBase):
    def test_case_file_and_charge_are_recorded_and_logged(self):
        r = self.make(case_ref="CID-77")
        self.assertEqual(r["case_ref"], "CID-77")
        self.assertEqual(self.act(r, "charge", {"charge": ""}).status_code, 400)
        out = self.act(r, "charge", {"charge": "Theft", "case_ref": "CID-78"})
        self.assertEqual((out.status_code, out.data["charge"], out.data["case_ref"], out.data["charged_at"] is not None), (200, "Theft", "CID-78", True))
        self.assertIn("charge", [e["kind"] for e in self.officer.get(f"{URL}{r['id']}/").data["events"]])
        self.assertEqual(self.act(r, "edit", {"case_ref": "CID-79"}).data["case_ref"], "CID-79")
        self.assertTrue(self.audit("detention.charge"))
        self.act(r, "close", {"outcome": "no_charge"})
        self.assertEqual(self.act(r, "charge", {"charge": "Late"}).status_code, 400)

    def test_the_detail_lists_the_linked_occurrence_book_entries(self):
        r = self.make(log_in_ob=True)
        got = self.officer.get(f"{URL}{r['id']}/").data
        self.assertEqual(len(got["occurrence_entries"]), 1)
        self.assertTrue(got["occurrence_entries"][0]["ob_number"].startswith("OB "))


class IncidentTests(UnitBase):
    def report(self, rec, c=None, **kw):
        return (c or self.officer).post(INC, {"record": rec["id"], "kind": "injury", "description": "Fell in cell", "medical_attended": True, **kw}, format="json")

    def test_report_visibility_and_review(self):
        r = self.make()
        made = self.report(r)
        self.assertEqual(made.status_code, 201, made.data)
        iid = made.data["id"]
        self.assertEqual(self.member.get(INC).status_code, 403)
        self.assertEqual(self.nugaal.get(INC).data["count"], 0)  # other region
        self.assertEqual(self.regional.get(INC).data["count"], 1)  # straight to the regional commander
        self.assertEqual(self.cmdr.get(INC).data["count"], 1)
        self.assertEqual(self.regional.get(OVR).data["stations"][0]["open_incidents"], 1)
        ev = [e for e in self.officer.get(f"{URL}{r['id']}/").data["events"] if e["kind"] == "incident"]
        self.assertNotIn("Fell", ev[0]["text"])  # no details in the custody log
        self.assertEqual(self.officer.post(f"{INC}{iid}/review/", {"note": "ok", "version": 1}, format="json").status_code, 403)
        self.assertEqual(self.regional_n.post(f"{INC}{iid}/review/", {"note": "ok", "version": 1}, format="json").status_code, 404)
        self.assertEqual(self.regional.post(f"{INC}{iid}/review/", {"note": "", "version": 1}, format="json").status_code, 400)
        done = self.regional.post(f"{INC}{iid}/review/", {"note": "Referred to the inspectorate", "version": 1}, format="json")
        self.assertEqual((done.status_code, done.data["reviewed"], done.data["reviewed_by"]), (200, True, "reg_cmd"))
        self.assertEqual(self.regional.post(f"{INC}{iid}/review/", {"note": "again", "version": 2}, format="json").status_code, 400)
        self.assertEqual(self.regional.get(OVR).data["stations"][0]["open_incidents"], 0)
        for a in ("detention.incident_report", "detention.incident_review"):
            self.assertTrue(self.audit(a), a)

    def test_nobody_reviews_their_own_report(self):
        admin = self.client_for(self.make_user("inc_adm", "hq_admin"))
        r = self.make()
        iid = self.report(r, c=admin).data["id"]
        self.assertEqual(admin.post(f"{INC}{iid}/review/", {"note": "fine", "version": 1}, format="json").status_code, 400)

    def test_a_death_closes_the_register_row_and_nothing_can_be_deleted(self):
        r = self.make()
        out = self.report(r, kind="death", description="Found unresponsive", medical_attended=False)
        self.assertEqual(out.status_code, 201, out.data)
        rec = DetentionRecord.objects.get(pk=r["id"])
        self.assertEqual((rec.status, rec.outcome), ("released", "died_in_custody"))
        self.assertEqual(self.officer.get(URL + "summary/").data["in_custody"], 0)
        with self.assertRaises(AppendOnlyError):
            CustodyIncident.objects.first().delete()

    def test_validation_and_scope_of_reporting(self):
        r = self.make()
        self.assertEqual(self.report(r, kind="other").status_code, 400)
        self.assertEqual(self.report(r, description="").status_code, 400)
        self.assertEqual(self.report(r, occurred_at=iso(days=3)).status_code, 400)
        self.assertEqual(self.report(r, c=self.nugaal).status_code, 400)  # not their station's person
        self.assertEqual(self.report(r, c=self.regional).status_code, 403)  # reading role cannot report


class CellRuleTests(UnitBase):
    def cell_for(self, reserved="any", code="C1", cap=5):
        c = self.officer.post(f"{FAC}{self.jail_a.pk}/add_cell/", {"code": code, "capacity": cap, "reserved_for": reserved}, format="json")
        self.assertEqual(c.status_code, 201, c.data)
        return c.data["id"]

    def codes(self, resp):
        return {w["code"] for w in resp.data["warnings"]}

    def test_a_reserved_cell_warns_but_never_blocks(self):
        women = self.cell_for("women")
        r = self.book(sex="male", cell_ref=women)
        self.assertEqual((r.status_code, self.codes(r)), (201, {"cell_reserved_women"}))
        self.assertEqual(DetentionRecord.objects.get(pk=r.data["id"]).cell_ref_id.hex, women.replace("-", ""))  # the placement stands
        self.assertTrue(self.audit("detention.cell_warning"))
        ok = self.book(sex="female", cell_ref=self.cell_for("women", "C2"), detainee_name="F")
        self.assertEqual(self.codes(ok), set())

    def test_men_and_women_in_one_cell_are_flagged(self):
        c = self.cell_for()
        self.make(sex="male", cell_ref=c)
        r = self.book(sex="female", cell_ref=c, detainee_name="W")
        self.assertEqual(self.codes(r), {"cell_mixed_sex"})
        self.assertEqual(self.regional.get(OVR).data["stations"][0]["cell_flags"], 2)  # both people share a flagged cell
        detail = self.officer.get(f"{URL}{r.data['id']}/").data
        self.assertEqual({w["code"] for w in detail["cell_flags"]}, {"cell_mixed_sex"})

    def test_no_juvenile_rule_runs_until_the_institution_sets_the_age(self):
        c = self.cell_for()
        self.make(sex="male", age_years=30, cell_ref=c)
        self.assertEqual(self.codes(self.book(sex="male", age_years=14, cell_ref=c, detainee_name="Kid")), set())

    @override_settings(DETENTION_JUVENILE_UNDER_AGE="18")
    def test_juvenile_rules_follow_the_configured_age(self):
        c = self.cell_for()
        self.make(sex="male", age_years=30, cell_ref=c)
        self.assertEqual(self.codes(self.book(sex="male", age_years=15, cell_ref=c, detainee_name="Kid")), {"cell_mixed_age"})
        men = self.cell_for("men", "M1")
        self.assertEqual(self.codes(self.book(sex="male", age_years=15, cell_ref=men, detainee_name="Kid2")), {"cell_reserved_men"})
        juv = self.cell_for("juveniles", "J1")
        self.assertEqual(self.codes(self.book(sex="male", age_years=40, cell_ref=juv, detainee_name="Adult")), {"cell_reserved_juveniles"})
        self.assertEqual(self.codes(self.book(sex="male", age_years=16, cell_ref=self.cell_for("juveniles", "J2"), detainee_name="Teen")), set())

    def test_cell_moves_warn_and_the_rule_can_be_edited(self):
        a, b = self.cell_for("any", "A1"), self.cell_for("women", "W1")
        r = self.make(sex="male", cell_ref=a)
        moved = self.act(r, "event", {"kind": "cell_move", "cell_ref": b})
        self.assertEqual((moved.status_code, self.codes(moved)), (201, {"cell_reserved_women"}))
        e = self.officer.post(f"{FAC}{self.jail_a.pk}/edit_cell/", {"cell": b, "reserved_for": "any", "version": 1}, format="json")
        self.assertEqual((e.status_code, e.data["reserved_for"]), (200, "any"))
        self.assertEqual(self.officer.post(f"{FAC}{self.jail_a.pk}/edit_cell/", {"cell": b, "reserved_for": "bogus", "version": 2}, format="json").status_code, 400)


class ReportAndPrintTests(UnitBase):
    def test_period_report_by_station_with_outcomes(self):
        a = self.make()
        b = self.make(detainee_name="B")
        self.act(a, "close", {"outcome": "no_charge"})
        self.act(b, "close", {"outcome": "transfer_court", "destination": "Court"})
        self.make(detainee_name="Still", booked_at=(timezone.now() - timedelta(hours=100)).isoformat())
        today = str(timezone.localdate())
        rep = self.regional.get(f"{OVR}report/?from={today}&to={today}").data
        row = rep["stations"][0]
        self.assertEqual((row["admitted"], row["released"], row["transferred_out"], row["outcomes"]), (2, 1, 1, {"no_charge": 1, "transfer_court": 1}))
        self.assertEqual((row["in_custody"], row["overdue_reviews"]), (1, 1))
        self.assertEqual(self.regional.get(f"{OVR}report/?from=2020-01-01&to=2020-01-31").data["stations"][0]["admitted"], 0)
        self.assertEqual(self.regional.get(f"{OVR}report/?from=2026-02-01&to=2026-01-01").status_code, 400)
        self.assertEqual(self.regional.get(f"{OVR}report/?from=nonsense").status_code, 400)
        self.assertEqual([s["unit"]["id"] for s in self.regional_n.get(f"{OVR}report/").data["stations"]], [str(self.unit_b.pk)])  # own jurisdiction only
        self.assertEqual(self.member.get(f"{OVR}report/").status_code, 403)
        self.assertTrue(self.audit("detention.read_report"))

    def test_printing_is_audited_and_release_note_needs_a_person_who_left(self):
        r = self.make()
        pr = lambda doc, c=None: (c or self.officer).post(f"{URL}{r['id']}/print/", {"doc": doc}, format="json")
        self.assertEqual(pr("custody_record").status_code, 200)
        self.assertEqual(pr("property_receipt").status_code, 200)
        self.assertEqual(pr("release_note").status_code, 400)  # still in custody
        self.assertEqual(pr("bogus").status_code, 400)
        self.assertEqual(pr("custody_record", self.nugaal).status_code, 404)
        self.assertEqual(pr("custody_record", self.member).status_code, 403)
        self.act(r, "close", {"outcome": "no_charge"})
        self.assertEqual(pr("release_note").status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(action="detention.print").count(), 3)
        self.assertFalse(AuditEvent.objects.filter(action="detention.print", metadata__has_key="detainee_name").exists())
