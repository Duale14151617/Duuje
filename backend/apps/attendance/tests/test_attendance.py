"""Attendance, absence reporting and the unit situation report. Synthetic data only."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.attendance import situation
from apps.attendance.models import AbsenceReason, AttendanceRecord
from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.logistics.models import InventoryCategory, Reconciliation, ReconciliationLine, StockLine, StockTransaction
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase
from apps.workflows.models import Submission

A = "/api/v1/attendance/"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class AttendanceBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.today = date.today()
        self.unit_a = self.unit("BARI-ARMY-A")
        self.cmdr_user = self.make_user("taliye.urur", "unit_commander", unit="BARI-ARMY-A")
        self.cmdr = self.client_for(self.cmdr_user)
        self.p1 = self.person("BARI-ARMY-A", "Soldier One", rank="PA-03")
        self.p2 = self.person("BARI-ARMY-A", "Soldier Two", rank="PA-03")
        self.p3 = self.person("BARI-ARMY-A", "Soldier Three", rank="PA-03")
        self.other = self.person("BARI-ARMY-B", "Other Unit Soldier", rank="PA-03")

    def entry(self, p, status="present", **kw):
        return {"personnel": str(p.pk), "status": status, **kw}

    def record(self, entries, day=None, c=None, unit=None):
        return (c or self.cmdr).post(A + "record/", {"org_unit": str((unit or self.unit_a).pk),
                                                      "date": (day or self.today).isoformat(), "entries": entries}, format="json")

    def ammo(self, qty_in=1000, qty_out=300):
        cat = InventoryCategory.objects.get(code="ammunition")
        InventoryCategory.objects.filter(pk=cat.pk).update(approval_status="approved")
        line = StockLine.objects.create(category=cat, org_unit=self.unit_a, uom="rounds", quantity=qty_in - qty_out)
        StockTransaction.objects.create(stock_line=line, kind="receive", delta=qty_in, balance_after=qty_in, reason="Delivery")
        StockTransaction.objects.create(stock_line=line, kind="issue", delta=-qty_out, balance_after=qty_in - qty_out, reason="Range")
        return line


class RecordingTests(AttendanceBase):
    def test_commander_role_exists_with_the_right_scope(self):
        from apps.accounts.models import Role
        role = Role.objects.get(code="unit_commander")
        codes = set(role.permissions.values_list("code", flat=True))
        self.assertEqual({"attendance.view", "attendance.record", "reports.submit"} - codes, set())
        self.assertNotIn("personnel.manage", codes)
        self.assertNotIn("logistics.manage", codes)

    def test_roll_lists_serving_people_with_their_status_and_todays_record(self):
        Personnel.objects.filter(pk=self.p2.pk).update(status="jailed")
        Personnel.objects.filter(pk=self.p3.pk).update(status="retired")
        self.record([self.entry(self.p1)])
        r = self.cmdr.get(A + "roll/", {"org_unit": str(self.unit_a.pk)}).json()["results"]
        by = {x["full_name"]: x for x in r}
        self.assertEqual(set(by), {"Soldier One", "Soldier Two"})            # retired person is not on the roll
        self.assertEqual(by["Soldier Two"]["status"], "jailed")              # personnel status shown, separately
        self.assertEqual(by["Soldier One"]["attendance"]["status"], "present")
        self.assertIsNone(by["Soldier Two"]["attendance"])

    def test_record_a_day_and_audit_it(self):
        r = self.record([self.entry(self.p1), self.entry(self.p2, "absent", reason="illness", note="Clinic"),
                         self.entry(self.p3, "on_leave")])
        self.assertEqual((r.status_code, r.json()["saved"]), (201, 3))
        self.assertEqual(AttendanceRecord.objects.filter(report_date=self.today).count(), 3)
        self.assertTrue(AuditEvent.objects.filter(action="attendance.recorded").exists())
        rec = AttendanceRecord.objects.get(personnel=self.p2)
        self.assertEqual((rec.reported_by_username, rec.reason.code), ("taliye.urur", "illness"))

    def test_absence_never_changes_personnel_status(self):
        self.record([self.entry(self.p1, "absent", reason="unexplained")])
        self.assertEqual(Personnel.objects.get(pk=self.p1.pk).status, "active")

    def test_all_or_nothing_with_row_codes(self):
        r = self.record([self.entry(self.p1), self.entry(self.p2, "absent"), self.entry(self.other),
                         self.entry(self.p1), {"personnel": "nope", "status": "present"}, self.entry(self.p3, "flying")])
        self.assertEqual(r.status_code, 400)
        codes = {x["index"]: x["code"] for x in r.json()["rows"]}
        self.assertEqual(codes, {1: "reason_required", 2: "person_unknown", 3: "duplicate_entry", 4: "person_unknown", 5: "invalid_status"})
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_cannot_record_twice_for_a_day_or_for_the_future(self):
        self.assertEqual(self.record([self.entry(self.p1)]).status_code, 201)
        again = self.record([self.entry(self.p1, "absent", reason="illness")])
        self.assertEqual(again.json()["rows"], [{"index": 0, "code": "already_recorded"}])
        future = self.record([self.entry(self.p2)], day=self.today + timedelta(days=1))
        self.assertEqual(self.codes(future, "date"), ["future_date"])

    def test_serving_people_only_and_scope_enforced(self):
        Personnel.objects.filter(pk=self.p3.pk).update(status="died")
        self.assertEqual(self.record([self.entry(self.p3)]).json()["rows"][0]["code"], "person_not_serving")
        self.assertEqual(self.codes(self.record([self.entry(self.other)], unit=self.unit("BARI-ARMY-B")), "org_unit"), ["out_of_scope"])

    def test_only_authorized_users_can_record_or_view(self):
        for user in (self.make_user("mem", "member", unit="BARI-ARMY"), self.make_user("uadm", "unit_admin", unit="BARI-ARMY-A")):
            c = self.client_for(user)
            self.assertEqual(self.record([self.entry(self.p1)], c=c).status_code, 403, user.username)
            self.assertEqual(c.get(A + "roll/", {"org_unit": str(self.unit_a.pk)}).status_code, 403, user.username)

    def test_absence_reason_that_requires_a_document(self):
        AbsenceReason.objects.filter(code="illness").update(requires_document=True)
        self.assertEqual(self.record([self.entry(self.p1, "absent", reason="illness")]).json()["rows"][0]["code"], "document_required")
        form = {"title": "Medical note", "category": "attendance_support", "file": SimpleUploadedFile("m.pdf", PDF)}
        up = self.cmdr.post(f"/api/v1/personnel/{self.p1.pk}/documents/upload/", form, format="multipart")
        self.assertEqual(up.status_code, 201, up.content)
        ok = self.record([self.entry(self.p1, "absent", reason="illness", document=up.json()["id"])])
        self.assertEqual(ok.status_code, 201, ok.content)

    def test_commander_may_attach_attendance_support_only(self):
        form = {"title": "ID", "category": "identity", "file": SimpleUploadedFile("i.pdf", PDF)}
        self.assertEqual(self.cmdr.post(f"/api/v1/personnel/{self.p1.pk}/documents/upload/", form, format="multipart").status_code, 403)

    def test_rows_cannot_be_deleted(self):
        self.record([self.entry(self.p1)])
        with self.assertRaises(AppendOnlyError):
            AttendanceRecord.objects.get().delete()


class AmendmentTests(AttendanceBase):
    def setUp(self):
        super().setUp()
        self.record([self.entry(self.p1)])
        self.rec = AttendanceRecord.objects.get(personnel=self.p1)

    def amend(self, **kw):
        return self.cmdr.post(A + "amend/", {"record": str(self.rec.pk), "status": "absent", "reason": "illness",
                                             "amend_reason": "Recorded wrongly", **kw}, format="json")

    def test_amendment_supersedes_but_keeps_history(self):
        r = self.amend()
        self.assertEqual((r.status_code, r.json()["status"], r.json()["amended"]), (200, "absent", True))
        old = AttendanceRecord.objects.get(pk=self.rec.pk)
        self.assertIsNotNone(old.superseded_at)
        self.assertEqual(old.status, "present")                                  # the original value is preserved
        self.assertEqual(AttendanceRecord.objects.filter(personnel=self.p1).count(), 2)
        self.assertTrue(AuditEvent.objects.filter(action="attendance.amended").exists())
        cur = self.cmdr.get(A + "records/", {"org_unit": str(self.unit_a.pk)}).json()["results"]
        self.assertEqual([x["status"] for x in cur], ["absent"])
        allv = self.cmdr.get(A + "records/", {"org_unit": str(self.unit_a.pk), "include_superseded": "1"}).json()["results"]
        self.assertEqual(len(allv), 2)

    def test_reason_for_the_amendment_is_required(self):
        r = self.cmdr.post(A + "amend/", {"record": str(self.rec.pk), "status": "on_leave"}, format="json")
        self.assertEqual(self.codes(r, "amend_reason"), ["reason_required"])

    def test_an_old_version_cannot_be_amended_again(self):
        self.amend()
        self.assertEqual(self.amend(status="present").status_code, 404)

    def test_out_of_scope_officer_cannot_amend(self):
        far = self.client_for(self.make_user("far", "unit_commander", unit="BARI-ARMY-B"))
        self.assertEqual(far.post(A + "amend/", {"record": str(self.rec.pk), "status": "on_leave", "amend_reason": "x"}, format="json").status_code, 404)


class SummaryTests(AttendanceBase):
    def test_period_bounds(self):
        d = date(2026, 5, 17)
        self.assertEqual(situation.period_bounds("day", d), (d, d))
        self.assertEqual(situation.period_bounds("month", d), (date(2026, 5, 1), date(2026, 5, 31)))
        self.assertEqual(situation.period_bounds("half", d), (date(2026, 1, 1), date(2026, 6, 30)))
        self.assertEqual(situation.period_bounds("half", date(2026, 9, 1)), (date(2026, 7, 1), date(2026, 12, 31)))
        self.assertEqual(situation.period_bounds("year", d), (date(2026, 1, 1), date(2026, 12, 31)))

    def test_totals_come_from_saved_records_and_reconcile_across_periods(self):
        d1 = date(self.today.year - 1, 6, 15)  # a fixed past day, so both days fall in one month, half and year
        d2 = d1 - timedelta(days=1)
        self.record([self.entry(self.p1), self.entry(self.p2, "absent", reason="illness"), self.entry(self.p3, "on_leave")], day=d1)
        self.record([self.entry(self.p1), self.entry(self.p2)], day=d2)
        day = self.cmdr.get(A + "summary/", {"org_unit": str(self.unit_a.pk), "period": "day", "date": d1.isoformat()}).json()
        self.assertEqual((day["present"], day["absent"], day["on_leave"], day["recorded"], day["not_recorded"]), (1, 1, 1, 3, 0))
        year = self.cmdr.get(A + "summary/", {"org_unit": str(self.unit_a.pk), "period": "year", "date": d1.isoformat()}).json()
        self.assertEqual(year["recorded"], 5)
        self.assertEqual(year["present"] + year["absent"] + year["on_leave"], year["recorded"])


class SituationReportTests(AttendanceBase):
    def preview(self):
        r = self.cmdr.get(A + "situation-preview/", {"org_unit": str(self.unit_a.pk), "from": self.today.isoformat(), "to": self.today.isoformat()})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["figures"]

    def test_figures_cover_status_attendance_and_ammunition(self):
        Personnel.objects.filter(pk=self.p3.pk).update(status="jailed")
        self.record([self.entry(self.p1), self.entry(self.p2, "absent", reason="illness")])
        self.ammo(1000, 300)
        f = self.preview()
        self.assertEqual((f["personnel_total"], f["personnel_active"], f["personnel_jailed"]), (3, 2, 1))
        self.assertEqual((f["attendance_present"], f["attendance_absent"], f["attendance_on_leave"], f["attendance_not_recorded"]), (1, 1, 0, 1))
        self.assertEqual((f["ammo_received"], f["ammo_issued"], f["ammo_remaining"]), (1000, 300, 700))
        self.assertEqual(set(f), set(situation.FIGURE_KEYS))

    def test_remaining_ammunition_is_calculated_from_the_ledger_at_period_end(self):
        line = self.ammo(1000, 300)
        StockTransaction.objects.create(stock_line=line, kind="issue", delta=-200, balance_after=500, reason="Patrol")
        self.assertEqual(self.preview()["ammo_issued"], 500)
        self.assertEqual(self.preview()["ammo_remaining"], 500)

    def test_a_subordinate_unit_rolls_up_into_its_commander(self):
        guuto = self.make_user("taliye.guuto", "unit_commander", unit="BARI-ARMY-A")
        self.record([self.entry(self.p1)])
        r = self.client_for(guuto).get(A + "situation-preview/", {"org_unit": str(self.unit_a.pk),
                                       "from": self.today.isoformat(), "to": self.today.isoformat()})
        self.assertEqual(r.json()["figures"]["attendance_present"], 1)

    def test_preview_is_scoped(self):
        r = self.cmdr.get(A + "situation-preview/", {"org_unit": str(self.unit("BARI-ARMY-B").pk),
                          "from": self.today.isoformat(), "to": self.today.isoformat()})
        self.assertEqual(self.codes(r, "org_unit"), ["out_of_scope"])

    def create(self, **kw):
        body = {"org_unit": str(self.unit_a.pk), "period_start": self.today.isoformat(), "period_end": self.today.isoformat(), **kw}
        return self.cmdr.post(A + "situation-report/", body, format="json")

    def test_creating_the_report_makes_a_draft_with_computed_figures(self):
        self.record([self.entry(self.p1)])
        r = self.create()
        self.assertEqual(r.status_code, 201, r.content)
        sub = Submission.objects.get(pk=r.json()["id"])
        self.assertEqual((sub.status, sub.report_type.code, sub.submitter_username), ("draft", "unit_situation_report", "taliye.urur"))
        self.assertEqual(sub.figures["attendance_present"], 1)

    def test_figures_cannot_be_typed_in(self):
        body = {"report_type": str(Submission._meta.get_field("report_type").related_model.objects.get(code="unit_situation_report").pk),
                "org_unit": str(self.unit_a.pk), "title": "x", "period_start": self.today.isoformat(),
                "period_end": self.today.isoformat(), "figures": {"personnel_total": 99}}
        r = self.cmdr.post("/api/v1/reports/submissions/", body, format="json")
        self.assertEqual(self.codes(r, "figures"), ["figures_computed"])

    def test_submitting_recomputes_and_freezes_the_figures_and_approval_preserves_them(self):
        self.record([self.entry(self.p1)])
        sid = self.create().json()["id"]
        self.record([self.entry(self.p2, "absent", reason="illness")])                 # recorded after the draft was made
        sub = Submission.objects.get(pk=sid)
        r = self.cmdr.post(f"/api/v1/reports/submissions/{sid}/submit/", {"version": sub.version}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        sub.refresh_from_db()
        self.assertEqual(sub.figures["attendance_absent"], 1)                          # picked up at submission
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        chief.post(f"/api/v1/reports/submissions/{sid}/start-review/", {"version": sub.version}, format="json")
        sub.refresh_from_db()
        rev = chief.post(f"/api/v1/reports/submissions/{sid}/approve/", {"version": sub.version}, format="json")
        self.assertEqual(rev.status_code, 200, rev.content)
        rec = AttendanceRecord.objects.get(personnel=self.p2)
        self.cmdr.post(A + "amend/", {"record": str(rec.pk), "status": "present", "amend_reason": "Corrected"}, format="json")
        sub.refresh_from_db()
        self.assertEqual(sub.approved_revision.figures["attendance_absent"], 1)        # the approved report did not change

    def test_situation_reports_are_not_added_into_consolidated_totals(self):
        from apps.workflows.services import build_summary
        self.assertEqual(build_summary(self.make_user("hq.rep", "hq_reporting"), {})["consolidated"]["totals"], {})


class PeriodicReportTests(AttendanceBase):
    """Daily / monthly / six-monthly / yearly reports, posted by the head of a Guuto or Urur and seen by the regional command."""

    def preview(self, start, end, c=None):
        return (c or self.cmdr).get(A + "situation-preview/", {"org_unit": str(self.unit_a.pk), "from": start.isoformat(), "to": end.isoformat()})

    def test_only_whole_days_months_half_years_and_years_are_accepted(self):
        y = self.today.year - 1
        for start, end in ((date(y, 3, 5), date(y, 3, 5)), (date(y, 3, 1), date(y, 3, 31)), (date(y, 1, 1), date(y, 6, 30)),
                           (date(y, 7, 1), date(y, 12, 31)), (date(y, 1, 1), date(y, 12, 31))):
            self.assertEqual(self.preview(start, end).status_code, 200, (start, end))
        for start, end in ((date(y, 3, 1), date(y, 3, 30)), (date(y, 3, 2), date(y, 3, 31)), (date(y, 2, 1), date(y, 7, 31)), (date(y, 3, 5), date(y, 3, 6))):
            self.assertEqual(self.codes(self.preview(start, end), "period_end"), ["period_not_standard"], (start, end))

    def test_a_longer_period_reconciles_with_the_daily_records(self):
        y, days = self.today.year - 1, [date(self.today.year - 1, 3, d) for d in (1, 2, 3)]
        self.record([self.entry(self.p1), self.entry(self.p2, "absent", reason="illness")], day=days[0])
        self.record([self.entry(self.p1, "on_leave"), self.entry(self.p2)], day=days[1])
        self.record([self.entry(self.p1), self.entry(self.p2), self.entry(self.p3, "absent", reason="unexplained")], day=days[2])
        daily = [self.preview(d, d).json()["figures"] for d in days]
        month = self.preview(date(y, 3, 1), date(y, 3, 31)).json()["figures"]
        year = self.preview(date(y, 1, 1), date(y, 12, 31)).json()["figures"]
        for key in ("attendance_present", "attendance_absent", "attendance_on_leave"):
            self.assertEqual(month[key], sum(f[key] for f in daily), key)
            self.assertEqual(year[key], month[key], key)
        self.assertEqual((month["attendance_present"], month["attendance_absent"], month["attendance_on_leave"]), (4, 2, 1))

    def test_weapon_accountability_changes_appear_in_the_report(self):
        InventoryCategory.objects.filter(code="weapons").update(approval_status="approved")
        cat = InventoryCategory.objects.get(code="weapons")
        armourer = self.client_for(self.make_user("armourer", "weapons_custodian", unit="BARI-ARMY-A"))
        ids = []
        for serial in ("AK-1", "AK-2", "AK-3"):
            r = armourer.post("/api/v1/weapons/", {"category": str(cat.pk), "org_unit": str(self.unit_a.pk), "serial": serial, "weapon_type": "Rifle"}, format="json")
            self.assertEqual(r.status_code, 201, r.content)
            ids.append(r.json()["id"])

        def issue(wid, person):
            v = armourer.get(f"/api/v1/weapons/{wid}/").json()["version"]
            return armourer.post(f"/api/v1/weapons/{wid}/issue/", {"personnel": str(person.pk), "condition": "serviceable", "authority_ref": "O-1", "version": v}, format="json")
        self.assertEqual(issue(ids[0], self.p1).status_code, 200)
        self.assertEqual(issue(ids[1], self.p2).status_code, 200)
        v = armourer.get(f"/api/v1/weapons/{ids[1]}/").json()["version"]
        self.assertEqual(armourer.post(f"/api/v1/weapons/{ids[1]}/return/", {"condition": "serviceable", "version": v}, format="json").status_code, 200)
        v = armourer.get(f"/api/v1/weapons/{ids[2]}/").json()["version"]
        self.assertEqual(armourer.post(f"/api/v1/logistics/assets/{ids[2]}/change/", {"action": "lost", "note": "Lost", "version": v}, format="json").status_code, 200)
        Personnel.objects.filter(pk=self.p1.pk).update(status="retired")
        f = self.preview(self.today, self.today).json()["figures"]
        self.assertEqual((f["weapons_total"], f["weapons_registered"], f["weapons_issued"], f["weapons_returned"]), (3, 3, 2, 1))
        self.assertEqual((f["weapons_in_custody"], f["weapons_lost_missing"], f["weapons_held_by_non_serving"]), (1, 1, 1))

    def test_reconciliation_differences_and_open_discrepancies_are_reported(self):
        line = self.ammo(1000, 300)
        done = Reconciliation.objects.create(org_unit=self.unit_a, status="completed", completed_at=timezone.now(), includes_restricted=True)
        ReconciliationLine.objects.create(reconciliation=done, stock_line=line, label="Ammo", expected_quantity=700, counted_quantity=690)
        opened = Reconciliation.objects.create(org_unit=self.unit_a, includes_restricted=True)
        ReconciliationLine.objects.create(reconciliation=opened, stock_line=line, label="Ammo3", expected_quantity=690, counted_quantity=680)
        f = self.preview(self.today, self.today).json()["figures"]
        self.assertEqual((f["recon_completed"], f["recon_variance_lines"], f["recon_open_discrepancies"]), (1, 1, 1))

    def test_a_commander_without_weapons_authority_cannot_make_the_report(self):
        far = self.client_for(self.make_user("o", "unit_admin", unit="BARI-ARMY-A"))
        self.assertEqual(far.get(A + "situation-preview/", {"org_unit": str(self.unit_a.pk), "from": self.today.isoformat(), "to": self.today.isoformat()}).status_code, 403)


class RegionalVisibilityTests(AttendanceBase):
    def setUp(self):
        super().setUp()
        self.regional = self.client_for(self.make_user("taliye.qaybeed", "regional_commander", unit="BARI-ARMY"))
        self.other_region = self.client_for(self.make_user("nugaal.qaybeed", "regional_commander", unit="NUGAAL-ARMY"))
        self.record([self.entry(self.p1)])

    def ids(self, c):
        return {x["id"] for x in c.get("/api/v1/reports/submissions/").json()["results"]}

    def make(self):
        r = self.cmdr.post(A + "situation-report/", {"org_unit": str(self.unit_a.pk), "period_start": self.today.isoformat(),
                                                      "period_end": self.today.isoformat()}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def post_it(self, sid):
        v = Submission.objects.get(pk=sid).version
        r = self.cmdr.post(f"/api/v1/reports/submissions/{sid}/submit/", {"version": v}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_the_regional_command_sees_a_report_only_once_it_is_posted(self):
        sid = self.make()
        self.assertNotIn(sid, self.ids(self.regional))            # still the commander's draft
        self.assertEqual(self.regional.get(f"/api/v1/reports/submissions/{sid}/").status_code, 404)
        self.assertIn(sid, self.ids(self.cmdr))                   # the author always sees their own draft
        self.post_it(sid)
        self.assertIn(sid, self.ids(self.regional))
        self.assertEqual(self.regional.get(f"/api/v1/reports/submissions/{sid}/").status_code, 200)

    def test_another_region_never_sees_it(self):
        sid = self.make(); self.post_it(sid)
        self.assertNotIn(sid, self.ids(self.other_region))
        self.assertEqual(self.other_region.get(f"/api/v1/reports/submissions/{sid}/").status_code, 404)

    def test_the_regional_command_can_see_but_not_post_or_approve(self):
        sid = self.make(); self.post_it(sid)
        body = {"org_unit": str(self.unit_a.pk), "period_start": self.today.isoformat(), "period_end": self.today.isoformat()}
        self.assertEqual(self.regional.post(A + "situation-report/", body, format="json").status_code, 403)
        self.assertEqual(self.regional.post(f"/api/v1/reports/submissions/{sid}/start-review/", {"version": 1}, format="json").status_code, 403)

    def test_the_head_posts_and_the_submitter_is_recorded(self):
        sid = self.make(); self.post_it(sid)
        sub = Submission.objects.get(pk=sid)
        self.assertEqual((sub.status, sub.submitter_username, sub.org_unit_id), ("submitted", "taliye.urur", self.unit_a.pk))

    def test_a_regional_commander_reads_personnel_and_attendance_of_the_region_but_not_other_regions(self):
        r = self.regional.get(A + "roll/", {"org_unit": str(self.unit_a.pk)})
        self.assertEqual(r.status_code, 200)
        far = self.regional.get(A + "roll/", {"org_unit": str(self.unit("NUGAAL-ARMY-A").pk)})
        self.assertEqual(self.codes(far, "org_unit"), ["out_of_scope"])
        self.assertEqual(self.regional.post(A + "record/", {"org_unit": str(self.unit_a.pk), "date": self.today.isoformat(),
                                                           "entries": [self.entry(self.p2)]}, format="json").status_code, 403)
