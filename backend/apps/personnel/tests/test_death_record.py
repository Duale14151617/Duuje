"""Statuses (Jailed, Died) and the death workflow: report -> evidence -> confirm. Synthetic data only."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.personnel.models import DeathRecord, Personnel, PersonnelDocument, PersonnelHistory

from .test_personnel import URL, PersonnelBase

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class DeathBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.reporter = self._cached("rep", "unit_admin", "BARI-ARMY-A")        # may report, may not confirm
        self.confirmer = self.manager()                                         # branch_admin: may confirm
        self.p = self.person("BARI-ARMY-A", "Late Soldier One", rank="PA-05")

    def d(self, person=None, tail=""):
        return f"{URL}{(person or self.p).pk}/death/{tail}"

    def report(self, c=None, day=None, **kw):
        return (c or self.reporter).post(self.d(tail="report/"),
                                         {"date_of_death": (day or date.today() - timedelta(days=2)).isoformat(), **kw},
                                         format="json")

    def evidence(self, c=None, category="death_evidence"):
        form = {"title": "Death certificate", "category": category, "file": SimpleUploadedFile("c.pdf", PDF)}
        return (c or self.reporter).post(f"{URL}{self.p.pk}/documents/upload/", form, format="multipart")

    def confirm(self, c=None):
        self.p.refresh_from_db()
        return (c or self.confirmer).post(self.d(tail="confirm/"), {"version": self.p.version}, format="json")


class StatusTests(DeathBase):
    def patch_status(self, status, c=None):
        self.p.refresh_from_db()
        return (c or self.confirmer).post(f"{URL}{self.p.pk}/change-status/", {"status": status, "version": self.p.version}, format="json")

    def test_five_working_statuses_can_be_set_including_jailed(self):
        for s in ("on_leave", "suspended", "jailed", "active"):
            self.assertEqual(self.patch_status(s).status_code, 200, s)
            self.assertEqual(Personnel.objects.get(pk=self.p.pk).status, s)

    def test_died_cannot_be_typed_in_as_a_status_or_created_or_imported(self):
        self.assertEqual(self.codes(self.patch_status("died"), "status"), ["use_death_workflow"])
        r = self.confirmer.post(URL, self.body(status="died"), format="json")
        self.assertEqual((r.status_code, self.codes(r, "status")), (400, ["use_death_workflow"]))

    def test_retired_and_discharged_still_exist(self):
        self.assertEqual(self.patch_status("retired").status_code, 200)


class DeathWorkflowTests(DeathBase):
    def test_report_does_not_change_status_and_is_audited(self):
        r = self.report(note="Reported by unit")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["state"], "reported")
        self.assertEqual(Personnel.objects.get(pk=self.p.pk).status, "active")
        self.assertTrue(AuditEvent.objects.filter(action="personnel.death_reported").exists())

    def test_cannot_report_a_future_date_or_a_second_open_report(self):
        self.assertEqual(self.codes(self.report(day=date.today() + timedelta(days=1)), "date_of_death"), ["future_date"])
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(self.codes(self.report(), "date_of_death"), ["death_already_reported"])

    def test_confirmation_needs_evidence(self):
        self.report()
        self.assertEqual(self.codes(self.confirm(), "state"), ["death_evidence_required"])
        self.assertEqual(Personnel.objects.get(pk=self.p.pk).status, "active")

    def test_reporter_cannot_confirm_their_own_report(self):
        boss = self.client_for(self.make_user("solo", "branch_admin", unit="BARI", branch="ARMY"))
        self.report(c=boss)
        self.evidence(c=boss)
        self.assertEqual(self.codes(self.confirm(c=boss), "state"), ["confirmer_must_differ"])

    def test_unit_admin_cannot_confirm(self):
        self.report()
        self.evidence()
        self.assertEqual(self.confirm(c=self.reporter).status_code, 403)

    def test_full_flow_sets_died_and_keeps_everything(self):
        acct = self.make_user("late.user", "member", unit="BARI-ARMY")
        Personnel.objects.filter(pk=self.p.pk).update(account=acct)
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(self.evidence().status_code, 201)
        day = date.today() - timedelta(days=2)
        r = self.confirm()
        self.assertEqual(r.status_code, 200)
        p = Personnel.objects.get(pk=self.p.pk)
        self.assertEqual(p.status, "died")
        rec = DeathRecord.objects.get(personnel=p)
        self.assertEqual((rec.state, rec.date_of_death, rec.confirmed_by_username), ("confirmed", day, "mgr"))
        h = PersonnelHistory.objects.get(personnel=p, field="status", new_ref="died")
        self.assertEqual((h.new_ref, h.effective_date), ("died", day))
        self.assertTrue(PersonnelHistory.objects.filter(personnel=p).count() >= 4)   # rank, unit, status (created) + death
        self.assertEqual(PersonnelDocument.objects.filter(personnel=p).count(), 1)  # documents stay
        self.assertFalse(User.objects.get(pk=acct.pk).is_active)                    # the login is closed, the link kept
        self.assertEqual(Personnel.objects.get(pk=p.pk).account_id, acct.pk)
        self.assertTrue(AuditEvent.objects.filter(action="personnel.death_confirmed").exists())

    def test_deceased_person_stays_listed_and_readable(self):
        self.report(); self.evidence(); self.confirm()
        self.assertEqual(self.confirmer.get(f"{URL}{self.p.pk}/").json()["status"], "died")
        self.assertIn(str(self.p.pk), {x["id"] for x in self.confirmer.get(URL, {"status": "died"}).json()["results"]})
        self.assertEqual(self.confirmer.get(f"{URL}{self.p.pk}/history/").status_code, 200)

    def test_deceased_file_is_closed_to_changes(self):
        self.report(); self.evidence(); self.confirm()
        self.p.refresh_from_db()
        v = self.p.version
        c = self.confirmer
        self.assertEqual(self.codes(c.post(f"{URL}{self.p.pk}/change-status/", {"status": "active", "version": v}, format="json"), "status"), ["person_deceased"])
        self.assertEqual(c.post(f"{URL}{self.p.pk}/transfer/", {"org_unit": str(self.unit("BARI-ARMY-B").pk), "version": v}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{URL}{self.p.pk}/change-rank/", {"rank": str(self.rank("PA-08").pk), "version": v}, format="json").status_code, 400)
        self.assertEqual(c.patch(f"{URL}{self.p.pk}/", {"full_name": "Changed", "version": v}, format="json").status_code, 400)
        self.assertEqual(Personnel.objects.get(pk=self.p.pk).full_name, "Late Soldier One")

    def test_deceased_cannot_be_a_supervisor_and_no_second_death_report(self):
        self.report(); self.evidence(); self.confirm()
        junior = self.person("BARI-ARMY-A", "Junior One", rank="PA-02")
        r = self.confirmer.patch(f"{URL}{junior.pk}/", {"version": junior.version, "supervisor": str(self.p.pk)}, format="json")
        self.assertEqual(self.codes(r, "supervisor"), ["supervisor_invalid"])
        self.assertEqual(self.codes(self.report(), "status"), ["person_deceased"])

    def test_withdraw_a_mistaken_report_then_report_again(self):
        self.report()
        r = self.reporter.post(self.d(tail="withdraw/"), {"reason": "Wrong person"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DeathRecord.objects.get(personnel=self.p).state, "withdrawn")
        self.assertEqual(self.report().status_code, 201)             # allowed again, history keeps both rows
        self.assertEqual(DeathRecord.objects.filter(personnel=self.p).count(), 2)

    def test_confirmed_death_cannot_be_withdrawn_and_evidence_is_locked(self):
        self.report(); doc = self.evidence().json(); self.confirm()
        r = self.confirmer.post(self.d(tail="withdraw/"), {"reason": "x"}, format="json")
        self.assertEqual(self.codes(r, "state"), ["death_not_pending"])
        w = self.confirmer.post(f"{URL}{self.p.pk}/documents/{doc['id']}/withdraw/", {"reason": "x"}, format="json")
        self.assertEqual(self.codes(w, "document"), ["death_evidence_locked"])

    def test_death_records_cannot_be_deleted(self):
        self.report()
        from apps.core.appendonly import AppendOnlyError
        with self.assertRaises(AppendOnlyError):
            DeathRecord.objects.get(personnel=self.p).delete()


class DeathAccessTests(DeathBase):
    def test_reporter_may_attach_death_evidence_only(self):
        self.assertEqual(self.evidence().status_code, 201)
        self.assertEqual(self.evidence(category="identity").status_code, 403)

    def test_out_of_scope_officer_cannot_report_or_see(self):
        far = self._cached("far", "unit_admin", "NUGAAL-ARMY-A")
        self.assertEqual(far.post(self.d(tail="report/"), {"date_of_death": date.today().isoformat()}, format="json").status_code, 404)
        self.assertEqual(far.get(self.d()).status_code, 404)

    def test_member_cannot_report_confirm_or_see_evidence(self):
        m = self.client_for(self.make_user("mem", "member", unit="BARI-ARMY"))
        self.assertEqual(m.post(self.d(tail="report/"), {"date_of_death": date.today().isoformat()}, format="json").status_code, 403)
        self.assertEqual(m.post(self.d(tail="confirm/"), {"version": 1}, format="json").status_code, 403)

    def test_reader_without_death_permissions_sees_state_but_no_evidence_list(self):
        self.report(); self.evidence()
        reader = self._cached("reader", "reporting_officer", "BARI-ARMY-A")
        r = self.confirmer.get(self.d()).json()["results"][0]
        self.assertEqual(len(r["evidence"]), 1)
        self.assertNotIn("evidence", reader.get(self.d()).json()["results"][0])

    def test_dashboard_strength_excludes_the_deceased(self):
        from apps.organization.structure import SERVING
        self.report(); self.evidence(); self.confirm()
        self.assertFalse(Personnel.objects.filter(SERVING, pk=self.p.pk).exists())


class AllServicesTests(DeathBase):
    """Statuses and the death record apply to every service's personnel (a Navy person stands in for the non-Army path)."""

    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("sa", "super_admin"))
        self.sailor = self.person("BARI-NAVY-A", "Sailor One", rank="N-1", branch="NAVY")

    def test_jailed_works_in_other_services(self):
        r = self.admin.post(f"{URL}{self.sailor.pk}/change-status/", {"status": "jailed", "version": self.sailor.version}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Personnel.objects.get(pk=self.sailor.pk).status, "jailed")

    def test_death_can_be_reported_in_other_services(self):
        r = self.admin.post(f"{URL}{self.sailor.pk}/death/report/", {"date_of_death": date.today().isoformat()}, format="json")
        self.assertEqual(r.status_code, 201)
