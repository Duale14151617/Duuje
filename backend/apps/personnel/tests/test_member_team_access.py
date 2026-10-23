"""Member role: own record + direct subordinates only. Synthetic data only."""
from apps.audit.models import AuditEvent
from apps.personnel import services as svc
from apps.personnel.models import Personnel
from apps.ranks.models import Rank

from .test_personnel import URL, PersonnelBase


class MemberTeamAccessTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        # Chain: major (PA-12) -> sergeant (PA-08) -> private (PA-03); a peer private and an outsider in another unit.
        self.major = self.person("BARI-ARMY-A", "Major One", rank="PA-12")
        self.sgt = self.person("BARI-ARMY-A", "Sergeant One", rank="PA-08")
        self.pvt = self.person("BARI-ARMY-A", "Private One", rank="PA-03")
        self.peer = self.person("BARI-ARMY-A", "Private Two", rank="PA-03")
        self.other = self.person("BARI-ARMY-B", "Private Three", rank="PA-03")
        Personnel.objects.filter(pk=self.sgt.pk).update(supervisor=self.major)
        Personnel.objects.filter(pk=self.pvt.pk).update(supervisor=self.sgt)
        self.sgt_user = self.make_user("sgt", "member", unit="BARI-ARMY")
        Personnel.objects.filter(pk=self.sgt.pk).update(account=self.sgt_user)
        self.client_sgt = self.client_for(self.sgt_user)

    def ids(self, resp):
        return {r["id"] for r in resp.json()["results"]}

    def test_member_lists_only_own_record_and_direct_subordinates(self):
        r = self.client_sgt.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ids(r), {str(self.sgt.pk), str(self.pvt.pk)})

    def test_member_cannot_open_superior_peer_or_other_unit_records(self):
        for p in (self.major, self.peer, self.other):
            self.assertEqual(self.client_sgt.get(f"{URL}{p.pk}/").status_code, 404, p.full_name)

    def test_member_can_open_subordinate_and_it_is_audited(self):
        self.assertEqual(self.client_sgt.get(f"{URL}{self.pvt.pk}/").status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action="personnel.view_subordinate", entity_id=str(self.pvt.pk)).exists())

    def test_opening_own_record_is_not_flagged_as_subordinate_access(self):
        self.assertEqual(self.client_sgt.get(f"{URL}{self.sgt.pk}/").status_code, 200)
        self.assertFalse(AuditEvent.objects.filter(action="personnel.view_subordinate").exists())

    def test_member_is_read_only_and_has_no_export_import_or_search(self):
        c = self.client_sgt
        self.assertEqual(c.patch(f"{URL}{self.pvt.pk}/", {"full_name": "X", "version": 1}, format="json").status_code, 403)
        self.assertEqual(c.post(URL, self.body(), format="json").status_code, 403)
        self.assertEqual(c.get(f"{URL}export/").status_code, 403)
        self.assertEqual(c.get(f"{URL}search/?q=Private").status_code, 403)
        self.assertEqual(c.get(f"{URL}{self.pvt.pk}/profile/").status_code, 403)
        self.assertEqual(c.get(f"{URL}{self.pvt.pk}/disciplinary/").status_code, 403)

    def test_unlinked_member_sees_nothing(self):
        c = self.client_for(self.make_user("unlinked", "member", unit="BARI-ARMY"))
        self.assertEqual(self.ids(c.get(URL)), set())

    def test_member_assignment_scope_still_limits_subordinates(self):
        # Subordinate moved to a unit outside the member's assignment: no longer visible.
        Personnel.objects.filter(pk=self.pvt.pk).update(org_unit=self.unit("NUGAAL-ARMY-A"))
        self.assertEqual(self.ids(self.client_sgt.get(URL)), {str(self.sgt.pk)})

    def test_a_unit_admin_still_sees_the_whole_unit(self):
        c = self._cached("uadmin", "unit_admin", "BARI-ARMY-A")
        self.assertEqual(len(self.ids(c.get(URL))), 4)


class SupervisorRulesTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.admin = self._cached("uadmin", "unit_admin", "BARI-ARMY-A")
        self.major = self.person("BARI-ARMY-A", "Major One", rank="PA-12")
        self.sgt = self.person("BARI-ARMY-A", "Sergeant One", rank="PA-08")
        self.pvt = self.person("BARI-ARMY-A", "Private One", rank="PA-03")

    def patch(self, person, **data):
        person.refresh_from_db()
        return self.admin.patch(f"{URL}{person.pk}/", {"version": person.version, **data}, format="json")

    def test_set_and_clear_supervisor(self):
        self.assertEqual(self.patch(self.pvt, supervisor=str(self.sgt.pk)).status_code, 200)
        self.assertEqual(Personnel.objects.get(pk=self.pvt.pk).supervisor_id, self.sgt.pk)
        self.assertEqual(self.patch(self.pvt, supervisor=None).status_code, 200)
        self.assertIsNone(Personnel.objects.get(pk=self.pvt.pk).supervisor_id)

    def test_supervisor_must_outrank(self):
        r = self.patch(self.sgt, supervisor=str(self.pvt.pk))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.codes(r, "supervisor"), ["supervisor_not_senior"])

    def test_cannot_supervise_self(self):
        self.assertEqual(self.codes(self.patch(self.sgt, supervisor=str(self.sgt.pk)), "supervisor"), ["supervisor_invalid"])

    def test_supervisor_outside_editors_scope_is_indistinguishable_from_invalid(self):
        far = self.person("NUGAAL-ARMY-A", "Far Colonel", rank="PA-14")
        self.assertEqual(self.codes(self.patch(self.pvt, supervisor=str(far.pk)), "supervisor"), ["supervisor_invalid"])

    def test_link_account_and_reject_duplicate_link(self):
        u = self.make_user("linkme", "member", unit="BARI-ARMY")
        self.assertEqual(self.patch(self.sgt, account_username="linkme").status_code, 200)
        self.assertEqual(Personnel.objects.get(pk=self.sgt.pk).account_id, u.pk)
        r = self.patch(self.pvt, account_username="linkme")
        self.assertEqual(self.codes(r, "account_username"), ["account_taken"])

    def test_rank_change_cannot_break_the_reporting_line(self):
        Personnel.objects.filter(pk=self.pvt.pk).update(supervisor=self.sgt)
        self.sgt.refresh_from_db()
        r = self.admin.post(f"{URL}{self.sgt.pk}/change-rank/",
                            {"rank": str(self.rank("PA-02").pk), "version": self.sgt.version}, format="json")
        self.assertEqual(self.codes(r, "rank"), ["outranks_subordinate"])


class SeniorityTests(PersonnelBase):
    def test_inactive_ranks_are_never_comparable(self):
        high = self.rank("PA-12")
        legacy = self.rank("PA-03")
        legacy.active, legacy.sort_order = False, 1003  # how a retired provisional rank is stored
        self.assertIsNone(svc.outranks(legacy, high))
        self.assertIsNone(svc.outranks(high, legacy))
        self.assertTrue(svc.outranks(high, self.rank("PA-03")))
        self.assertFalse(svc.outranks(self.rank("PA-03"), self.rank("PA-03")))

    def test_legacy_rank_holder_cannot_be_given_a_supervisor(self):
        admin = self._cached("uadmin", "unit_admin", "BARI-ARMY-A")
        major, pvt = self.person("BARI-ARMY-A", "Major One", rank="PA-12"), self.person("BARI-ARMY-A", "Private One")
        Rank.objects.filter(pk=pvt.rank_id).update(active=False, sort_order=1003)
        r = admin.patch(f"{URL}{pvt.pk}/", {"version": pvt.version, "supervisor": str(major.pk)}, format="json")
        self.assertEqual(self.codes(r, "supervisor"), ["rank_not_comparable"])

    def test_rank_order_cannot_be_edited_into_a_broken_reporting_line(self):
        major, sgt = self.person("BARI-ARMY-A", "Major One", rank="PA-12"), self.person("BARI-ARMY-A", "Sergeant One", rank="PA-08")
        Personnel.objects.filter(pk=sgt.pk).update(supervisor=major)
        boss = self.client_for(self.make_user("ranker", "super_admin"))
        rank = self.rank("PA-12")
        r = boss.patch(f"/api/v1/ranks/{rank.pk}/", {"sort_order": 5, "version": rank.version}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.codes(r, "sort_order"), ["breaks_reporting_lines"])
        ok = boss.patch(f"/api/v1/ranks/{rank.pk}/", {"sort_order": 30, "version": rank.version}, format="json")
        self.assertEqual(ok.status_code, 200)


class ReportingScreenApiTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.admin = self._cached("uadmin", "unit_admin", "BARI-ARMY-A")
        self.major = self.person("BARI-ARMY-A", "Major One", rank="PA-12", service_number="A-0001")
        self.sgt = self.person("BARI-ARMY-A", "Sergeant One", rank="PA-08", service_number="A-0002")
        self.pvt = self.person("BARI-ARMY-A", "Private One", rank="PA-03", service_number="A-0003")
        self.cpl = self.person("BARI-ARMY-A", "Corporal One", rank="PA-05", service_number="A-0004")

    def csv(self, *lines, header="service_number,supervisor_service_number,account_username"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile("lines.csv", ("\n".join((header,) + lines) + "\n").encode(), content_type="text/csv")

    def post(self, file, dry_run="true"):
        return self.admin.post(f"{URL}reporting-lines/", {"file": file, "dry_run": dry_run}, format="multipart")

    def test_candidates_are_only_senior_active_same_service_people_in_scope(self):
        far = self.person("NUGAAL-ARMY-A", "Far Colonel", rank="PA-14")
        r = self.admin.get(f"{URL}{self.pvt.pk}/supervisor-candidates/")
        self.assertEqual(r.status_code, 200)
        names = [x["full_name"] for x in r.json()]
        self.assertEqual(names, ["Major One", "Sergeant One", "Corporal One"])  # most senior first
        self.assertNotIn(far.full_name, names)
        self.assertNotIn("Private One", names)

    def test_candidates_need_manage_permission(self):
        member = self.client_for(self.make_user("mem", "member", unit="BARI-ARMY"))
        self.assertEqual(member.get(f"{URL}{self.pvt.pk}/supervisor-candidates/").status_code, 403)

    def test_detail_shows_reporting_line_to_unit_readers_only(self):
        Personnel.objects.filter(pk=self.pvt.pk).update(supervisor=self.sgt)
        d = self.admin.get(f"{URL}{self.sgt.pk}/").json()
        self.assertEqual([x["full_name"] for x in d["subordinates"]], ["Private One"])
        self.assertEqual(self.admin.get(f"{URL}{self.pvt.pk}/").json()["supervisor"]["full_name"], "Sergeant One")
        # A member sees their own record but gets no reporting-line block (so never a superior's name).
        user = self.make_user("sgtm", "member", unit="BARI-ARMY")
        Personnel.objects.filter(pk=self.pvt.pk).update(account=user)
        mine = self.client_for(user).get(f"{URL}{self.pvt.pk}/").json()
        self.assertNotIn("supervisor", mine)
        self.assertNotIn("account_username", mine)

    def test_no_supervisor_filter(self):
        Personnel.objects.filter(pk=self.pvt.pk).update(supervisor=self.sgt)
        r = self.admin.get(URL, {"no_supervisor": "1"})
        names = {x["full_name"] for x in r.json()["results"]}
        self.assertNotIn("Private One", names)
        self.assertIn("Major One", names)

    def test_bulk_preview_writes_nothing_and_apply_writes_all(self):
        lines = ("A-0002,A-0001,", "A-0003,A-0002,", "A-0004,A-0001,")
        r = self.post(self.csv(*lines))
        self.assertEqual((r.status_code, r.json()["can_commit"], r.json()["valid"]), (200, True, 3))
        self.assertEqual(Personnel.objects.filter(supervisor__isnull=False).count(), 0)
        r = self.post(self.csv(*lines), dry_run="false")
        self.assertEqual((r.status_code, r.json()["updated"]), (200, 3))
        self.assertEqual(Personnel.objects.get(pk=self.pvt.pk).supervisor_id, self.sgt.pk)
        self.assertTrue(AuditEvent.objects.filter(action="personnel.reporting_lines").exists())

    def test_bulk_is_all_or_nothing_and_reports_row_codes(self):
        r = self.post(self.csv("A-0002,A-0001,", "A-0003,A-0004,", "A-0001,A-0003,", "NOPE-1,A-0001,", "A-0002,A-0001,"),
                      dry_run="false")
        self.assertEqual(r.status_code, 409)
        codes = {row["row"]: row["errors"] for row in r.json()["rows"]}
        self.assertEqual(codes[2], [])
        self.assertEqual(codes[3], [])               # corporal (PA-05) is senior to the private (PA-03): fine
        self.assertEqual(codes[4], ["supervisor_not_senior"])
        self.assertEqual(codes[5], ["person_unknown"])
        self.assertEqual(codes[6], ["duplicate_row"])
        self.assertEqual(Personnel.objects.filter(supervisor__isnull=False).count(), 0)

    def test_bulk_clear_and_blank_semantics(self):
        Personnel.objects.filter(pk=self.pvt.pk).update(supervisor=self.sgt)
        Personnel.objects.filter(pk=self.cpl.pk).update(supervisor=self.sgt)
        r = self.post(self.csv("A-0003,clear,", "A-0004,,"), dry_run="false")  # clear one, leave the other untouched
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(Personnel.objects.get(pk=self.pvt.pk).supervisor_id)
        self.assertEqual(Personnel.objects.get(pk=self.cpl.pk).supervisor_id, self.sgt.pk)

    def test_bulk_cannot_touch_people_outside_the_uploaders_scope(self):
        far = self.person("NUGAAL-ARMY-A", "Far Private", service_number="Z-0001")
        r = self.post(self.csv("Z-0001,A-0001,"))
        self.assertEqual(r.json()["rows"][0]["errors"], ["person_unknown"])
        self.assertIsNone(Personnel.objects.get(pk=far.pk).supervisor_id)

    def test_bulk_links_accounts_once(self):
        self.make_user("login1", "member", unit="BARI-ARMY")
        r = self.post(self.csv("A-0002,,login1", "A-0003,,login1"))
        self.assertEqual(r.json()["rows"][1]["errors"], ["account_taken"])

    def test_bulk_rejects_bad_files_and_members(self):
        self.assertEqual(self.post(self.csv("A-0002,A-0001", header="service_number,boss")).status_code, 400)
        member = self.client_for(self.make_user("mem2", "member", unit="BARI-ARMY"))
        self.assertEqual(member.post(f"{URL}reporting-lines/", {"file": self.csv("A-0002,A-0001,")}, format="multipart").status_code, 403)
