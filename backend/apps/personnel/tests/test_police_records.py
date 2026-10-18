"""Disciplinary history, service documents, cross-service duplicates, combined report, Police stations, Police sample data.

Synthetic data only. Police ranks are approved in setUpTestData (draft ranks cannot be assigned, by design).
"""
from datetime import date, timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import PlacementError, check_placement
from apps.personnel import records, services as svc
from apps.personnel.models import DisciplinaryRecord, Personnel, PersonnelDocument
from apps.ranks.models import Rank

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
SECRET = "Confidential-Narrative-XYZ"


@override_settings(POLICE_MODULE_ENABLED=True)
class PoliceRecordsBase(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Rank.objects.filter(branch__code="POLICE").update(approval_status="approved")
        cls.p_rank = Rank.objects.filter(branch__code="POLICE", name_en="Inspector").first()
        cls.a_rank = Rank.objects.filter(branch__code="ARMY", approval_status="approved").first()

    def police(self, name, unit="BARI-POLICE-PERS", **kw):
        return svc.create_personnel(None, full_name=name, phone=kw.get("phone", ""), service_number=kw.get("number"),
                                    org_unit=self.unit(unit), rank=self.p_rank, status=kw.get("status", "active"),
                                    effective_date=date.today())

    def army(self, name, unit="BARI-ARMY", **kw):
        return svc.create_personnel(None, full_name=name, phone=kw.get("phone", ""), service_number=kw.get("number"),
                                    org_unit=self.unit(unit), rank=self.a_rank, status=kw.get("status", "active"),
                                    effective_date=date.today())

    def polis(self):  # Police branch administrator, Bari
        return self.client_for(self.make_user("polis", "branch_admin", unit="BARI", branch="POLICE"))

    def actions(self, action):
        return AuditEvent.objects.filter(action=action)


class DisciplinaryTests(PoliceRecordsBase):
    def url(self, person, tail=""):
        return f"/api/v1/personnel/{person.pk}/disciplinary/{tail}"

    def body(self, **kw):
        base = {"category": "written_warning", "incident_date": (date.today() - timedelta(days=3)).isoformat(),
                "summary": SECRET, "outcome": "Warned"}
        base.update(kw)
        return base

    def test_add_list_and_every_view_and_change_is_audited_without_the_text(self):
        p, c = self.police("Disc One"), self.polis()
        r = c.post(self.url(p, "add/"), self.body(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        listing = c.get(self.url(p))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["results"][0]["summary"], SECRET)
        self.assertEqual(self.actions("disciplinary.add").count(), 1)
        self.assertEqual(self.actions("disciplinary.view").count(), 1)
        for event in AuditEvent.objects.filter(action__startswith="disciplinary."):
            self.assertNotIn(SECRET, str(event.metadata))

    def test_text_is_encrypted_in_the_database(self):
        p, c = self.police("Disc Two"), self.polis()
        c.post(self.url(p, "add/"), self.body(), format="json")
        row = DisciplinaryRecord.objects.get(personnel=p)
        self.assertNotIn(SECRET, row.data_enc)

    def test_entries_are_append_only_and_a_correction_is_a_new_entry(self):
        from apps.core.appendonly import AppendOnlyError
        p, c = self.police("Disc Three"), self.polis()
        first = c.post(self.url(p, "add/"), self.body(), format="json").data["id"]
        row = DisciplinaryRecord.objects.get(pk=first)
        row.data_enc = "x"
        with self.assertRaises(AppendOnlyError):
            row.save()
        with self.assertRaises(AppendOnlyError):
            row.delete()
        with self.assertRaises(AppendOnlyError):
            DisciplinaryRecord.objects.filter(pk=first).update(data_enc="x")
        fix = c.post(self.url(p, "add/"), self.body(summary="Corrected wording", corrects=first), format="json")
        self.assertEqual(fix.status_code, 201, fix.data)
        items = c.get(self.url(p)).data["results"]
        self.assertEqual(len(items), 2)
        by_id = {i["id"]: i for i in items}
        self.assertTrue(by_id[first]["superseded"])
        self.assertFalse(by_id[fix.data["id"]]["superseded"])
        self.assertEqual(self.actions("disciplinary.correct").count(), 1)

    def test_an_entry_can_be_corrected_only_once_and_only_for_the_same_person(self):
        p, q, c = self.police("Disc Four"), self.police("Disc Five"), self.polis()
        first = c.post(self.url(p, "add/"), self.body(), format="json").data["id"]
        c.post(self.url(p, "add/"), self.body(corrects=first), format="json")
        again = c.post(self.url(p, "add/"), self.body(corrects=first), format="json")
        self.assertIn("already_corrected", self.codes(again, "corrects"))
        other = c.post(self.url(q, "add/"), self.body(corrects=first), format="json")
        self.assertIn("record_not_found", self.codes(other, "corrects"))

    def test_voiding_needs_a_correction_and_validation(self):
        p, c = self.police("Disc Six"), self.polis()
        self.assertEqual(c.post(self.url(p, "add/"), self.body(voided=True), format="json").status_code, 400)
        self.assertEqual(c.post(self.url(p, "add/"), self.body(incident_date="2999-01-01"), format="json").status_code, 400)
        self.assertEqual(c.post(self.url(p, "add/"), self.body(summary="  "), format="json").status_code, 400)

    def test_view_and_manage_permissions_are_separate_and_default_off(self):
        p = self.police("Disc Seven")
        self.polis().post(self.url(p, "add/"), self.body(), format="json")
        reader = self.client_for(self.make_user("rdr", "unit_admin", unit="BARI-POLICE-PERS", branch="POLICE"))
        self.assertEqual(reader.get(self.url(p)).status_code, 403)          # unit_admin holds neither
        hq = self.client_for(self.make_user("hqa", "hq_admin"))
        self.assertEqual(hq.get(self.url(p)).status_code, 403)              # administrators do not get it by default
        self.assertTrue(self.actions("access.denied").exists())

    def test_army_staff_cannot_reach_a_police_file_and_cid_files_need_cid_access(self):
        cid_person = self.police("Disc Cid", unit="BARI-POLICE-CID")
        army_admin = self.client_for(self.make_user("armadm", "branch_admin", unit="BARI", branch="ARMY"))
        self.assertEqual(army_admin.get(self.url(cid_person)).status_code, 404)
        self.assertEqual(self.polis().get(self.url(cid_person)).status_code, 404)  # Police admin: no cid.access
        cid = self.client_for(self.make_user("cidoff", "cid_officer", unit="BARI-POLICE-CID", branch="POLICE"))
        self.assertEqual(cid.get(self.url(cid_person)).status_code, 200)

    @override_settings(POLICE_MODULE_ENABLED=False)
    def test_police_files_are_hidden_while_the_module_is_off(self):
        p = self.police("Disc Off")
        self.assertEqual(self.polis().get(self.url(p)).status_code, 404)

    def test_works_for_army_files_too_with_the_right_role(self):
        p = self.army("Army Disc")
        c = self.client_for(self.make_user("armadm2", "branch_admin", unit="BARI", branch="ARMY"))
        self.assertEqual(c.post(self.url(p, "add/"), self.body(), format="json").status_code, 201)


class DocumentTests(PoliceRecordsBase):
    def url(self, person, tail=""):
        return f"/api/v1/personnel/{person.pk}/documents/{tail}"

    def upload(self, c, person, data=PDF, name="scan.pdf", **kw):
        form = {"title": "Appointment letter", "category": "appointment", "file": SimpleUploadedFile(name, data)}
        form.update(kw)
        return c.post(self.url(person, "upload/"), form, format="multipart")

    def test_upload_list_download_round_trip_with_audit(self):
        p, c = self.police("Doc One"), self.polis()
        r = self.upload(c, p)
        self.assertEqual(r.status_code, 201, r.data)
        doc_id = r.data["id"]
        listing = c.get(self.url(p)).data["results"]
        self.assertEqual([d["title"] for d in listing], ["Appointment letter"])
        dl = c.get(self.url(p, f"{doc_id}/download/"))
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, PDF)
        self.assertEqual(dl["Content-Type"], "application/pdf")
        self.assertIn("attachment", dl["Content-Disposition"])
        self.assertEqual(dl["X-Content-Type-Options"], "nosniff")
        for action in ("document.upload", "document.list", "document.download"):
            self.assertEqual(self.actions(action).count(), 1, action)

    def test_stored_bytes_and_title_are_encrypted(self):
        p, c = self.police("Doc Two"), self.polis()
        self.upload(c, p, title="Secret Title ABC")
        doc = PersonnelDocument.objects.get(personnel=p)
        self.assertNotIn(b"%PDF-", bytes(doc.content_enc))
        self.assertNotIn("Secret Title ABC", doc.meta_enc)

    def test_only_real_pdf_jpeg_png_within_the_size_limit(self):
        p, c = self.police("Doc Three"), self.polis()
        bad = self.upload(c, p, data=b"MZ\x90\x00 not a document", name="evil.pdf")
        self.assertIn("document_type_invalid", self.codes(bad, "file"))
        self.assertIn("document_empty", self.codes(self.upload(c, p, data=b"", name="e.pdf"), "file"))
        big = self.upload(c, p, data=b"%PDF-" + b"0" * (records.DOCUMENT_MAX_BYTES + 1))
        self.assertIn("document_too_large", self.codes(big, "file"))
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        self.assertEqual(self.upload(c, p, data=png, name="x.png").status_code, 201)

    def test_withdrawn_documents_disappear_but_the_row_is_kept(self):
        p, c = self.police("Doc Four"), self.polis()
        doc_id = self.upload(c, p).data["id"]
        self.assertEqual(c.post(self.url(p, f"{doc_id}/withdraw/"), {}, format="json").status_code, 400)  # reason needed
        ok = c.post(self.url(p, f"{doc_id}/withdraw/"), {"reason": "Wrong file"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(c.get(self.url(p)).data["results"], [])
        self.assertEqual(c.get(self.url(p, f"{doc_id}/download/")).status_code, 404)
        self.assertTrue(PersonnelDocument.objects.filter(pk=doc_id).exists())
        self.assertEqual(self.actions("document.withdraw").count(), 1)

    def test_documents_can_never_be_deleted(self):
        from apps.core.appendonly import AppendOnlyError
        p = self.police("Doc Five")
        doc = records.add_document(p, None, {"title": "T", "category": "other"}, PDF, "application/pdf")
        with self.assertRaises(AppendOnlyError):
            doc.delete()

    def test_scope_and_permissions_apply_to_documents(self):
        cid_person = self.police("Doc Cid", unit="BARI-POLICE-CID")
        cid = self.client_for(self.make_user("cidoff", "cid_officer", unit="BARI-POLICE-CID", branch="POLICE"))
        self.assertEqual(self.upload(cid, cid_person).status_code, 201)
        self.assertEqual(self.upload(self.polis(), cid_person).status_code, 404)
        army_admin = self.client_for(self.make_user("armadm", "branch_admin", unit="BARI", branch="ARMY"))
        p = self.police("Doc Six")
        self.assertEqual(army_admin.get(self.url(p)).status_code, 404)
        reader = self.client_for(self.make_user("rdr", "unit_admin", unit="BARI-POLICE-PERS", branch="POLICE"))
        self.assertEqual(reader.get(self.url(p)).status_code, 403)

    def test_a_download_of_an_unknown_or_foreign_document_is_a_plain_404(self):
        p, q, c = self.police("Doc Seven"), self.police("Doc Eight"), self.polis()
        doc_id = self.upload(c, p).data["id"]
        self.assertEqual(c.get(self.url(q, f"{doc_id}/download/")).status_code, 404)
        self.assertEqual(c.get(self.url(p, "not-a-uuid/download/")).status_code, 404)


class DuplicateIdentityTests(PoliceRecordsBase):
    URL = "/api/v1/personnel/"

    def create(self, c, name, unit, rank, **kw):
        body = {"full_name": name, "org_unit": str(self.unit(unit).pk), "rank": str(rank.pk)}
        body.update(kw)
        return c.post(self.URL, body, format="json")

    def test_same_name_and_phone_as_a_serving_person_in_another_service_is_blocked(self):
        self.army("Amina Yusuf Hersi", phone="+252 61 555 0100")
        c = self.polis()
        r = self.create(c, "amina yusuf hersi", "BARI-POLICE-PERS", self.p_rank, phone="+252615550100")
        self.assertEqual(r.status_code, 400)
        self.assertIn("duplicate_identity", self.codes(r, "full_name"))
        r = self.create(c, "amina yusuf hersi", "BARI-POLICE-PERS", self.p_rank, phone="+252615550100", confirm_duplicate=True)
        self.assertEqual(r.status_code, 400)                      # confirming cannot override a block
        self.assertEqual(Personnel.objects.filter(name_key="amina yusuf hersi").count(), 1)
        self.assertTrue(self.actions("personnel.duplicate_blocked").exists())
        self.assertNotIn("Army", str(r.data))                     # never says which service holds the match

    def test_a_retired_record_in_the_other_service_is_only_flagged(self):
        self.army("Barre Elmi Said", phone="+252610000777", status="retired")
        c = self.polis()
        r = self.create(c, "Barre Elmi Said", "BARI-POLICE-PERS", self.p_rank, phone="+252610000777")
        self.assertIn("possible_duplicate", self.codes(r, "full_name"))
        ok = self.create(c, "Barre Elmi Said", "BARI-POLICE-PERS", self.p_rank, phone="+252610000777", confirm_duplicate=True)
        self.assertEqual(ok.status_code, 201, ok.data)

    def test_same_name_in_another_service_without_phones_is_flagged(self):
        self.army("Nuur Farah Guled")
        c = self.polis()
        r = self.create(c, "Nuur Farah Guled", "BARI-POLICE-PERS", self.p_rank)
        self.assertIn("possible_duplicate", self.codes(r, "full_name"))

    def test_same_name_with_different_phones_in_two_services_is_not_flagged(self):
        self.army("Hodan Ali Warsame", phone="+252610001111")
        r = self.create(self.polis(), "Hodan Ali Warsame", "BARI-POLICE-PERS", self.p_rank, phone="+252610002222")
        self.assertEqual(r.status_code, 201, r.data)

    def test_editing_a_name_or_phone_into_a_duplicate_is_blocked(self):
        self.army("Dahir Omar Jama", phone="+252610003333")
        mine = self.police("Someone Else Entirely", phone="+252610004444")
        c = self.polis()
        r = c.patch(f"{self.URL}{mine.pk}/", {"full_name": "Dahir Omar Jama", "phone": "+252610003333", "version": 1}, format="json")
        self.assertIn("duplicate_identity", self.codes(r, "full_name"))

    def test_csv_import_rejects_cross_service_duplicates(self):
        self.army("Fuad Ismail Salah", phone="+252610005555")
        user = self.make_user("polis", "branch_admin", unit="BARI", branch="POLICE")
        rows = [{"service_number": "", "full_name": "Fuad Ismail Salah", "phone": "+252610005555",
                 "unit_code": "BARI-POLICE-PERS", "rank_code": self.p_rank.code, "status": "active"}]
        results = svc.validate_import_rows(user, rows)
        self.assertIn("duplicate_identity", results[0]["errors"])

    def test_report_command_lists_existing_cross_service_duplicates_by_id_only(self):
        a = self.army("Mukhtar Abdi Dahir", phone="+252610006666")
        b = self.police("Mukhtar Abdi Dahir", phone="+252610006666")   # created directly, as old data could have been
        from io import StringIO
        out = StringIO()
        call_command("report_duplicate_identities", stdout=out)
        text = out.getvalue()
        self.assertIn(str(a.pk), text)
        self.assertIn(str(b.pk), text)
        self.assertNotIn("Mukhtar", text)
        self.assertNotIn("610006666", text)


class CombinedReportTests(PoliceRecordsBase):
    URL = "/api/v1/reports/combined/"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rank = Rank.objects.filter(branch__code="POLICE", name_en="Inspector").first()
        arank = Rank.objects.filter(branch__code="ARMY", approval_status="approved").first()
        mk = lambda name, unit, r, status="active": svc.create_personnel(
            None, full_name=name, phone="", service_number=None, org_unit=OU.objects.get(code=unit), rank=r,
            status=status, effective_date=date.today())
        mk("Cmb Army 1", "BARI-ARMY", arank)
        mk("Cmb Army 2", "NUGAAL-ARMY", arank, "retired")
        mk("Cmb Pol 1", "BARI-POLICE-PERS", rank)
        mk("Cmb Pol 2", "BARI-POLICE-CID", rank)

    def test_command_authority_sees_both_services_but_not_cid(self):
        c = self.client_for(self.make_user("pres", "command_authority"))
        r = c.get(self.URL)
        self.assertEqual(r.status_code, 200, r.data)
        by = {b["code"]: b for b in r.data["branches"]}
        self.assertEqual(by["ARMY"]["total"], 2)
        self.assertEqual(by["ARMY"]["serving"], 1)
        self.assertEqual(by["POLICE"]["total"], 1)               # CID person excluded: no cid.access
        self.assertTrue(r.data["excludes_restricted_units"])
        self.assertEqual(r.data["totals"]["total"], 3)
        self.assertNotIn("Cmb", str(r.data))                     # aggregates only, no names
        self.assertEqual(self.actions("report.combined_view").count(), 1)

    def test_super_admin_holds_it_too_and_sees_cid(self):
        r = self.client_for(self.make_user("sup", "super_admin")).get(self.URL)
        by = {b["code"]: b for b in r.data["branches"]}
        self.assertEqual(by["POLICE"]["total"], 2)
        self.assertFalse(r.data["excludes_restricted_units"])

    def test_nobody_else_gets_it(self):
        for name, role, unit, branch in (("hqa", "hq_admin", "HQ", None), ("hqr", "hq_reporting", "HQ", None),
                                         ("chief", "regional_chief", "BARI", None), ("polis", "branch_admin", "BARI", "POLICE"),
                                         ("cid", "cid_officer", "BARI-POLICE-CID", "POLICE"), ("aud", "auditor", "HQ", None)):
            c = self.client_for(self.make_user(name, role, unit=unit, branch=branch))
            self.assertEqual(c.get(self.URL).status_code, 403, role)

    @override_settings(POLICE_MODULE_ENABLED=False)
    def test_police_is_left_out_while_the_module_is_off(self):
        r = self.client_for(self.make_user("pres", "command_authority")).get(self.URL)
        self.assertNotIn("POLICE", {b["code"] for b in r.data["branches"]})
        self.assertFalse(r.data["police_module_enabled"])


class StationTests(PoliceRecordsBase):
    def test_a_station_can_sit_only_directly_under_a_police_command(self):
        police_cmd, army_cmd = self.unit("BARI-POLICE"), self.unit("BARI-ARMY")
        self.assertEqual(check_placement("station", police_cmd, None).code, "POLICE")
        for bad in (army_cmd, self.unit("BARI-POLICE-PERS"), self.unit("BARI"), self.unit("HQ")):
            with self.assertRaises(PlacementError) as ctx:
                check_placement("station", bad, None)
            self.assertEqual(ctx.exception.code, "station_parent_must_be_police_command")

    def test_branch_admin_creates_a_station_and_staff_can_be_assigned_to_it(self):
        c = self.polis()
        r = c.post("/api/v1/organization/units/", {"code": "bari-stn-a", "name_en": "Bari Station A", "name_so": "Bari Station A",
                                                    "level": "station", "parent": str(self.unit("BARI-POLICE").pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["level"], "station")
        bad = c.post("/api/v1/organization/units/", {"code": "bari-stn-b", "name_en": "X", "name_so": "X", "level": "station",
                                                      "parent": str(self.unit("BARI-ARMY").pk)}, format="json")
        self.assertEqual(bad.status_code, 400)
        body = {"full_name": "Station Person", "org_unit": r.data["id"], "rank": str(self.p_rank.pk)}
        made = c.post("/api/v1/personnel/", body, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        self.assertEqual(made.data["org_unit"]["code"], "BARI-STN-A")
        placeable = c.get("/api/v1/organization/units/", {"placeable": "1", "q": "BARI-STN-A"}).data["results"]
        self.assertIn("BARI-STN-A", {u["code"] for u in placeable})

    def test_a_unit_admin_can_hold_the_role_at_a_station_and_sees_only_that_station(self):
        station = OU.objects.create(code="BARI-STN-C", name_en="C", level="station", parent=self.unit("BARI-POLICE"))
        OU.objects.create(code="BARI-STN-D", name_en="D", level="station", parent=self.unit("BARI-POLICE"))
        svc.create_personnel(None, full_name="At C", phone="", service_number="S-C", org_unit=station, rank=self.p_rank,
                             status="active", effective_date=date.today())
        svc.create_personnel(None, full_name="At D", phone="", service_number="S-D", org_unit=self.unit("BARI-STN-D"),
                             rank=self.p_rank, status="active", effective_date=date.today())
        c = self.client_for(self.make_user("stnadm", "unit_admin", unit="BARI-STN-C", branch="POLICE"))
        resp = c.get("/api/v1/personnel/")
        self.assertEqual({r["service_number"] for r in resp.data["results"]}, {"S-C"})

    def test_a_station_cannot_hold_child_units(self):
        station = OU.objects.create(code="BARI-STN-E", name_en="E", level="station", parent=self.unit("BARI-POLICE"))
        with self.assertRaises(PlacementError):
            check_placement("unit", station, None)


class PoliceSampleDataTests(PoliceRecordsBase):
    def test_police_sample_people_spread_over_departments_cid_and_stations(self):
        call_command("seed_test_personnel", count=50, police_count=40, verbosity=0)
        police = Personnel.objects.filter(service_number__startswith="TST-5")
        self.assertEqual(police.count(), 40)
        self.assertEqual(Personnel.objects.filter(service_number__startswith="TST-").exclude(branch__code="POLICE").count(), 50)
        units = set(police.values_list("org_unit__code", flat=True))
        self.assertTrue(any(u.endswith("-CID") for u in units))
        self.assertTrue(any("-STN-" in u for u in units))
        self.assertTrue(all(p.rank.approval_status == "approved" for p in police.select_related("rank")))
        # unit admin and CID see something; the Police admin does not see CID
        cid = self.client_for(self.make_user("cidoff", "cid_officer", unit="BARI-POLICE-CID", branch="POLICE"))
        self.assertTrue(cid.get("/api/v1/personnel/").data["count"] >= 1)
        call_command("seed_test_personnel", count=50, police_count=40, verbosity=0)    # idempotent
        self.assertEqual(Personnel.objects.filter(service_number__startswith="TST-5").count(), 40)
        call_command("seed_test_personnel", delete=True, verbosity=0)
        self.assertFalse(Personnel.objects.filter(service_number__startswith="TST-").exists())

    def test_without_approved_ranks_nothing_is_added_unless_the_demo_flag_is_set(self):
        Rank.objects.filter(branch__code="POLICE").update(approval_status="draft")
        call_command("seed_test_personnel", count=10, police_count=10, verbosity=0)
        self.assertFalse(Personnel.objects.filter(branch__code="POLICE").exists())
        call_command("seed_test_personnel", count=10, police_count=10, police_draft_ranks=True, verbosity=0)
        self.assertEqual(Personnel.objects.filter(branch__code="POLICE").count(), 10)

    @override_settings(POLICE_MODULE_ENABLED=False)
    def test_nothing_police_is_added_while_the_module_is_off(self):
        call_command("seed_test_personnel", count=10, police_count=10, verbosity=0)
        self.assertFalse(Personnel.objects.filter(branch__code="POLICE").exists())

    def test_clean_up_keeps_a_test_person_who_holds_append_only_records(self):
        call_command("seed_test_personnel", count=10, police_count=5, verbosity=0)
        keep = Personnel.objects.filter(service_number__startswith="TST-5").first()
        records.add_disciplinary(keep, None, {"category": "other", "incident_date": date.today(), "summary": "x"})
        call_command("seed_test_personnel", delete=True, verbosity=0)
        self.assertEqual(list(Personnel.objects.filter(service_number__startswith="TST-")), [keep])
