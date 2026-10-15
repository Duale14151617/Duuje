import csv
import io
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import ServiceBranch
from apps.personnel import services as svc
from apps.personnel.models import ImportBatch, Personnel
from apps.ranks.models import Rank

URL = "/api/v1/personnel/"


class PersonnelBase(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        army, navy = ServiceBranch.objects.get(code="ARMY"), ServiceBranch.objects.get(code="NAVY")
        # PA-04 stays a draft so the "rank not approved" rules can be exercised; the others are approved officially.
        Rank.objects.filter(branch=army, code="PA-04").update(approval_status="draft")
        Rank.objects.create(branch=navy, category="enlisted", code="N-1", name_en="Seaman", name_so="x",
                            approval_status="approved", sort_order=1)
        for code, parent in (("BARI-ARMY-A", "BARI-ARMY"), ("BARI-ARMY-B", "BARI-ARMY"),
                             ("NUGAAL-ARMY-A", "NUGAAL-ARMY"), ("BARI-NAVY-A", "BARI-NAVY")):
            OU.objects.create(code=code, name_en=code.title(), level="unit", parent=OU.objects.get(code=parent))

    def rank(self, code, branch="ARMY"):
        return Rank.objects.get(branch__code=branch, code=code)

    def person(self, unit, name, rank="PA-03", branch="ARMY", **kw):
        return svc.create_personnel(
            None, full_name=name, phone=kw.get("phone", ""), service_number=kw.get("service_number"),
            org_unit=self.unit(unit), rank=self.rank(rank, branch), status="active", effective_date=None)

    def body(self, unit="BARI-ARMY-A", **kw):
        base = {"full_name": "Test Person", "org_unit": str(self.unit(unit).pk), "rank": str(self.rank("PA-03").pk)}
        base.update(kw)
        return base

    def _cached(self, name, role, unit, branch=None):
        cache = self.__dict__.setdefault("_clients", {})
        if name not in cache:
            cache[name] = self.client_for(self.make_user(name, role, unit=unit, branch=branch))
        return cache[name]

    def manager(self):  # branch administrator, Bari / Army
        return self._cached("mgr", "branch_admin", "BARI", "ARMY")

    def chief(self, region="BARI"):
        return self._cached(f"chief-{region}", "regional_chief", region)


class AccessTests(PersonnelBase):
    def test_hq_admin_has_no_personnel_access_by_default(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        self.assertEqual(c.get(URL).status_code, 403)
        self.assertEqual(c.post(URL, self.body(), format="json").status_code, 403)

    def test_lists_are_limited_to_scope(self):
        self.person("BARI-ARMY-A", "Bari Army Person")
        self.person("BARI-NAVY-A", "Bari Navy Person", rank="N-1", branch="NAVY")
        self.person("NUGAAL-ARMY-A", "Nugaal Army Person")
        names = lambda r: {p["full_name"] for p in r.data["results"]}
        self.assertEqual(names(self.chief("BARI").get(URL)), {"Bari Army Person", "Bari Navy Person"})
        self.assertEqual(names(self.manager().get(URL)), {"Bari Army Person"})
        self.assertEqual(names(self.chief("NUGAAL").get(URL)), {"Nugaal Army Person"})

    def test_direct_urls_outside_scope_are_not_found(self):
        other = self.person("NUGAAL-ARMY-A", "Nugaal Person")
        c = self.chief("BARI")
        self.assertEqual(c.get(f"{URL}{other.pk}/").status_code, 404)
        self.assertEqual(c.get(f"{URL}{other.pk}/history/").status_code, 404)
        self.assertEqual(c.patch(f"{URL}{other.pk}/", {"full_name": "X", "version": 1}, format="json").status_code, 404)
        self.assertEqual(c.post(f"{URL}{other.pk}/change-status/", {"status": "retired", "version": 1}, format="json").status_code, 404)
        self.assertEqual(c.post(f"{URL}{other.pk}/transfer/", {"org_unit": str(self.unit("BARI-ARMY-A").pk), "version": 1}, format="json").status_code, 404)

    def test_search_and_filters_cannot_widen_scope(self):
        self.person("NUGAAL-ARMY-A", "Searchable Nugaal", phone="+252611111111")
        c = self.chief("BARI")
        for q in ("?q=Searchable", "?q=611111111", f"?org_unit={self.unit('NUGAAL').pk}",
                  f"?branch={ServiceBranch.objects.get(code='ARMY').pk}"):
            self.assertEqual(c.get(URL + q).data["count"], 0, q)

    def test_read_only_user_can_view_but_not_change(self):
        p = self.person("BARI-ARMY-A", "Visible Person")
        c = self.client_for(self.make_user("ro", "read_only", unit="BARI"))
        self.assertEqual(c.get(f"{URL}{p.pk}/").status_code, 200)
        self.assertEqual(c.post(URL, self.body(), format="json").status_code, 403)
        self.assertEqual(c.patch(f"{URL}{p.pk}/", {"full_name": "Y", "version": 1}, format="json").status_code, 403)

    def test_malformed_filter_ids_are_400_not_500(self):
        self.assertEqual(self.chief().get(URL + "?branch=abc").status_code, 400)
        self.assertEqual(self.chief().get(URL + "?org_unit=abc").status_code, 400)

    def test_lists_paginate(self):
        for i in range(30):
            self.person("BARI-ARMY-A", f"Bulk Person {i:02d}")
        r = self.chief().get(URL)
        self.assertEqual((len(r.data["results"]), r.data["count"]), (25, 30))

    def test_unauthenticated_denied(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(URL).data["code"], "not_authenticated")


class CreateAndRuleTests(PersonnelBase):
    def test_create_in_scope_writes_history_and_audit(self):
        r = self.manager().post(URL, self.body(service_number="SN-1001", phone="+252 61 000 0001"), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["branch"]["code"], "ARMY")
        h = self.manager().get(f"{URL}{r.data['id']}/history/").data
        self.assertEqual({e["field"] for e in h}, {"rank", "org_unit", "status"})
        self.assertTrue(AuditEvent.objects.filter(action="personnel.create", outcome="success").exists())

    def test_create_outside_scope_rejected(self):
        r = self.manager().post(URL, self.body(unit="NUGAAL-ARMY-A"), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("out_of_scope", self.codes(r, "org_unit"))
        r = self.manager().post(URL, self.body(unit="BARI-NAVY-A"), format="json")  # other branch, same region
        self.assertIn("out_of_scope", self.codes(r, "org_unit"))

    def test_invalid_rank_branch_combinations(self):
        c = self.manager()
        navy_rank = str(self.rank("N-1", "NAVY").pk)
        self.assertIn("rank_branch_mismatch", self.codes(c.post(URL, self.body(rank=navy_rank), format="json"), "rank"))
        draft = str(self.rank("PA-04").pk)
        self.assertIn("rank_not_approved", self.codes(c.post(URL, self.body(rank=draft), format="json"), "rank"))
        self.assertIn("unit_level_invalid", self.codes(
            self.chief().post(URL, self.body(unit="BARI"), format="json"), "org_unit"))

    def test_service_number_must_be_unique_across_records(self):
        self.person("NUGAAL-ARMY-A", "Elsewhere", service_number="SN-2000")
        r = self.manager().post(URL, self.body(service_number="sn-2000"), format="json")
        self.assertIn("service_number_taken", self.codes(r, "service_number"))
        self.assertNotIn("Elsewhere", str(r.data))  # never reveals the other record

    def test_possible_duplicates_need_confirmation(self):
        self.person("BARI-ARMY-A", "Amina  Yusuf", phone="+252 61 555 0100")
        c = self.manager()
        body = self.body(full_name="amina yusuf", phone="0025261-555-0100")
        r = c.post(URL, {**body, "phone": "+252615550100"}, format="json")
        self.assertIn("possible_duplicate", self.codes(r, "full_name"))
        r = c.post(URL, {**body, "phone": "+252615550100", "confirm_duplicate": True}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_validation_of_phone_and_service_number_format(self):
        c = self.manager()
        self.assertIn("phone_invalid", self.codes(c.post(URL, self.body(phone="abc"), format="json"), "phone"))
        self.assertIn("service_number_invalid", self.codes(
            c.post(URL, self.body(service_number="bad number!"), format="json"), "service_number"))


class UpdateAndHistoryTests(PersonnelBase):
    def test_edit_with_optimistic_concurrency(self):
        p = self.person("BARI-ARMY-A", "Editable Person")
        c = self.manager()
        url = f"{URL}{p.pk}/"
        self.assertEqual(c.patch(url, {"phone": "+252610000000"}, format="json").status_code, 400)  # no version
        ok = c.patch(url, {"phone": "+252610000000", "version": 1}, format="json")
        self.assertEqual((ok.status_code, ok.data["version"]), (200, 2))
        stale = c.patch(url, {"phone": "+252610000001", "version": 1}, format="json")
        self.assertEqual((stale.status_code, stale.data["code"]), (409, "version_conflict"))

    def test_transfer_rank_status_create_effective_dated_history(self):
        p = self.person("BARI-ARMY-A", "Moving Person")
        c, url = self.manager(), f"{URL}{p.pk}/"
        past = (date.today() - timedelta(days=30)).isoformat()
        r = c.post(f"{url}transfer/", {"org_unit": str(self.unit("BARI-ARMY-B").pk), "effective_date": past,
                                       "reason": "Posting", "version": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["org_unit"]["code"], "BARI-ARMY-B")
        r = c.post(f"{url}change-rank/", {"rank": str(self.rank("PA-05").pk), "version": 2}, format="json")
        self.assertEqual(r.data["rank"]["code"], "PA-05")
        r = c.post(f"{url}change-status/", {"status": "on_leave", "version": 3}, format="json")
        self.assertEqual((r.data["status"], r.data["version"]), ("on_leave", 4))
        h = c.get(f"{url}history/").data
        moves = [e for e in h if e["field"] == "org_unit" and e["old_label"]]
        self.assertEqual((len(moves), moves[0]["effective_date"], moves[0]["reason"]), (1, past, "Posting"))
        self.assertEqual(len([e for e in h if e["field"] == "rank" and e["old_label"]]), 1)
        self.assertEqual(len([e for e in h if e["field"] == "status" and e["old_label"]]), 1)

    def test_invalid_changes_are_rejected(self):
        p = self.person("BARI-ARMY-A", "Rule Person")
        c, url = self.manager(), f"{URL}{p.pk}/"
        future = (date.today() + timedelta(days=2)).isoformat()
        r = c.post(f"{url}change-status/", {"status": "retired", "effective_date": future, "version": 1}, format="json")
        self.assertIn("future_date", self.codes(r, "effective_date"))
        r = c.post(f"{url}transfer/", {"org_unit": str(self.unit("NUGAAL-ARMY-A").pk), "version": 1}, format="json")
        self.assertIn("out_of_scope", self.codes(r, "org_unit"))
        r = self.chief().post(f"{url}transfer/", {"org_unit": str(self.unit("BARI-NAVY-A").pk), "version": 1}, format="json")
        self.assertIn("branch_change_not_supported", self.codes(r, "org_unit"))
        r = c.post(f"{url}change-rank/", {"rank": str(self.rank("PA-04").pk), "version": 1}, format="json")
        self.assertIn("rank_not_approved", self.codes(r, "rank"))
        r = c.post(f"{url}change-status/", {"status": "active", "version": 1}, format="json")
        self.assertIn("no_change", self.codes(r, "status"))
        self.assertEqual(c.post(f"{url}change-status/", {"status": "retired"}, format="json").status_code, 400)

    def test_stale_workflow_version_conflicts_and_changes_nothing(self):
        p = self.person("BARI-ARMY-A", "Race Person")
        c, url = self.manager(), f"{URL}{p.pk}/"
        c.post(f"{url}change-status/", {"status": "on_leave", "version": 1}, format="json")
        r = c.post(f"{url}change-status/", {"status": "retired", "version": 1}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (409, "version_conflict"))
        self.assertEqual(Personnel.objects.get(pk=p.pk).status, "on_leave")
        self.assertEqual(p.history.filter(field="status").count(), 2)


def csv_upload(text, name="people.csv"):
    return SimpleUploadedFile(name, text.encode(), content_type="text/csv")


class ImportTests(PersonnelBase):
    HEAD = "service_number,full_name,phone,unit_code,rank_code,status\n"

    def preview(self, client, text, name="people.csv"):
        return client.post(URL + "import/preview/", {"file": csv_upload(text, name)}, format="multipart")

    def test_preview_then_commit_creates_records_and_history(self):
        c = self.manager()
        r = self.preview(c, self.HEAD + "IM-0001,Import One,,BARI-ARMY-A,PA-03,active\nIM-0002,Import Two,+252610001,BARI-ARMY-B,PA-05,\n")
        self.assertEqual((r.status_code, r.data["valid"], r.data["can_commit"]), (200, 2, True), r.data)
        self.assertNotIn("Import One", str(r.data))  # preview never echoes personal data
        self.assertEqual(Personnel.objects.count(), 0)  # nothing written by preview
        done = c.post(URL + "import/commit/", {"batch_id": r.data["batch_id"]}, format="json")
        self.assertEqual((done.status_code, done.data["created"]), (200, 2))
        self.assertEqual(Personnel.objects.count(), 2)
        self.assertEqual(Personnel.objects.get(service_number="IM-0001").history.count(), 3)
        self.assertEqual(ImportBatch.objects.get(pk=r.data["batch_id"]).rows, [])  # PII wiped after commit
        again = c.post(URL + "import/commit/", {"batch_id": r.data["batch_id"]}, format="json")
        self.assertEqual(again.status_code, 404)

    def test_rows_outside_scope_or_invalid_block_the_whole_import(self):
        c = self.manager()
        text = (self.HEAD + "IM-1,Fine Person,,BARI-ARMY-A,PA-03,\n"
                "IM-2,Out Of Scope,,NUGAAL-ARMY-A,PA-03,\n"
                "IM-3,Draft Rank,,BARI-ARMY-A,PA-04,\n"
                "IM-3,Repeated Number,,BARI-ARMY-A,PA-03,\n"
                "IM-5,Bad Status,,BARI-ARMY-A,PA-03,gone\n")
        r = self.preview(c, text)
        self.assertFalse(r.data["can_commit"])
        errs = {row["row"]: row["errors"] for row in r.data["rows"]}
        self.assertEqual(errs[2], [])
        self.assertIn("unit_unknown", errs[3])
        self.assertIn("rank_not_approved", errs[4])
        self.assertIn("service_number_taken", errs[5])
        self.assertIn("status_invalid", errs[6])
        done = c.post(URL + "import/commit/", {"batch_id": r.data["batch_id"]}, format="json")
        self.assertEqual((done.status_code, done.data["code"]), (409, "import_has_errors"))
        self.assertEqual(Personnel.objects.count(), 0)

    def test_batches_are_private_to_the_uploader_and_expire(self):
        r = self.preview(self.manager(), self.HEAD + ",Solo Person,,BARI-ARMY-A,PA-03,\n")
        other = self.client_for(self.make_user("mgr2", "branch_admin", unit="BARI", branch="ARMY"))
        self.assertEqual(other.post(URL + "import/commit/", {"batch_id": r.data["batch_id"]}, format="json").status_code, 404)
        from django.utils import timezone
        ImportBatch.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.manager().post(URL + "import/commit/", {"batch_id": r.data["batch_id"]}, format="json").status_code, 404)

    def test_unsafe_or_malformed_files_are_rejected(self):
        c = self.manager()
        self.assertIn("file_type_invalid", self.codes(self.preview(c, self.HEAD, name="x.exe"), "file"))
        self.assertIn("file_columns_invalid", self.codes(self.preview(c, "name,unit\nA,B\n"), "file"))
        self.assertIn("file_empty", self.codes(self.preview(c, self.HEAD), "file"))
        big = self.HEAD + ",Big,,BARI-ARMY-A,PA-03,\n" * 1001
        self.assertIn("file_too_many_rows", self.codes(self.preview(c, big), "file"))
        r = c.post(URL + "import/preview/", {}, format="multipart")
        self.assertIn("file_required", self.codes(r, "file"))

    def test_only_import_permission_holders_may_import(self):
        r = self.chief().post(URL + "import/preview/", {"file": csv_upload(self.HEAD)}, format="multipart")
        self.assertEqual(r.status_code, 403)  # regional chief has no personnel.import


class ExportTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.person("BARI-ARMY-A", "Bari Exportable", service_number="EX-1")
        self.person("BARI-ARMY-A", "=HYPERLINK(1)", service_number="EX-2")
        self.person("NUGAAL-ARMY-A", "Nugaal Hidden", service_number="EX-3")

    def test_export_is_off_until_approved(self):
        r = self.chief().get(URL + "export/")
        self.assertEqual((r.status_code, r.data["code"]), (403, "export_disabled"))
        self.assertTrue(AuditEvent.objects.filter(action="personnel.export", outcome="denied").exists())

    @override_settings(PERSONNEL_EXPORT_ENABLED=True)
    def test_export_is_scoped_audited_and_formula_safe(self):
        r = self.chief("BARI").get(URL + "export/", HTTP_ACCEPT="text/csv")
        self.assertEqual(r.status_code, 200)
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        flat = str(rows)
        self.assertIn("EX-1", flat)
        self.assertNotIn("EX-3", flat)
        self.assertIn("'=HYPERLINK(1)", flat)
        ev = AuditEvent.objects.get(action="personnel.export", outcome="success")
        self.assertEqual(ev.metadata["rows"], 2)

    @override_settings(PERSONNEL_EXPORT_ENABLED=True)
    def test_export_requires_its_own_permission(self):
        self.assertEqual(self.manager().get(URL + "export/").status_code, 403)  # branch admin can view, not export
        self.assertEqual(self.client_for(self.make_user("ro", "read_only", unit="BARI")).get(URL + "export/").status_code, 403)
