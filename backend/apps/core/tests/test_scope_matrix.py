"""One canary record per module lives in Nugaal. Every Bari role then probes every list, search, detail,
summary, export and mutation route; a marker from Nugaal must never appear and nothing may change."""
from datetime import date

from django.test import override_settings
from django.urls import reverse

from apps.core.testing import BaseApiTest
from apps.logistics.models import Asset, InventoryCategory, Reconciliation, ReconciliationLine, StockLine
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import ServiceBranch
from apps.personnel import services as pers
from apps.personnel.models import Personnel
from apps.ranks.models import Rank
from apps.training.models import Course, TrainingRecord
from apps.workflows.models import ReportType, Submission, SubmissionRevision
from config.api_v1 import router

MARK = "ZZCANARY"
MARKERS = [MARK, "ZZ-CAN-1", "424242", "777777", "611900900"]


class ScopeMatrixTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        for code, parent in (("BARI-ARMY-A", "BARI-ARMY"), ("NUGAAL-ARMY-A", "NUGAAL-ARMY")):
            OU.objects.create(code=code, name_en=code, level="unit", parent=OU.objects.get(code=parent))
        InventoryCategory.objects.all().update(approval_status="approved")
        Rank.objects.filter(branch=ServiceBranch.objects.get(code="ARMY"), code="PA-03").update(approval_status="approved", name_so="x")
        n = self.unit("NUGAAL-ARMY-A")
        cat = lambda c: InventoryCategory.objects.get(code=c)
        self.person = pers.create_personnel(None, full_name=f"{MARK} Person", phone="+252611900900", service_number="ZZ-CAN-1",
                                            org_unit=n, rank=Rank.objects.get(branch__code="ARMY", code="PA-03"), status="active", effective_date=None)
        self.stock = StockLine.objects.create(category=cat("general_supplies"), org_unit=n, quantity=424242, reorder_level=1)
        self.asset = Asset.objects.create(category=cat("vehicles"), org_unit=n, identifier=f"{MARK}-VEH")
        self.rasset = Asset.objects.create(category=cat("restricted_equipment"), org_unit=n, identifier=f"{MARK}-RX")
        self.record = TrainingRecord.objects.create(personnel=self.person, course=Course.objects.get(code="first_aid"),
                                                    start_date=date(2026, 3, 1), notes=MARK)
        self.recon = Reconciliation.objects.create(org_unit=n, includes_restricted=True)
        ReconciliationLine.objects.create(reconciliation=self.recon, stock_line=self.stock, label=f"{MARK} line", expected_quantity=424242)
        self.sub = Submission.objects.create(
            report_type=ReportType.objects.get(code="monthly_admin_report"), org_unit=n, title=f"{MARK} report",
            period_start=date(2026, 5, 1), period_end=date(2026, 5, 31), submitter_username="n-officer",
            figures={"personnel_strength": 777777, "personnel_on_leave": 1, "personnel_in_training": 1})
        rev = SubmissionRevision.objects.create(submission=self.sub, revision_no=1, title=self.sub.title, period_start=self.sub.period_start,
                                                period_end=self.sub.period_end, figures=self.sub.figures, submitted_by_username="n-officer")
        Submission.objects.filter(pk=self.sub.pk).update(status="approved", current_revision=1, approved_revision=rev)

        who = lambda name, role, unit, branch=None: self.client_for(self.make_user(name, role, unit=unit, branch=branch))
        self.bari = {
            "chief": who("b-chief", "regional_chief", "BARI"), "branch": who("b-branch", "branch_admin", "BARI", "ARMY"),
            "unitadm": who("b-unit", "unit_admin", "BARI-ARMY-A"), "cust": who("b-cust", "logistics_custodian", "BARI-ARMY"),
            "rcust": who("b-rcust", "restricted_custodian", "BARI-ARMY"), "trainer": who("b-trainer", "training_admin", "BARI"),
            "officer": who("b-officer", "reporting_officer", "BARI-ARMY-A"), "ro": who("b-ro", "read_only", "BARI"),
        }
        self.nugaal = {
            "chief": who("n-chief", "regional_chief", "NUGAAL"), "cust": who("n-cust", "logistics_custodian", "NUGAAL-ARMY"),
            "rcust": who("n-rcust", "restricted_custodian", "NUGAAL-ARMY"), "trainer": who("n-trainer", "training_admin", "NUGAAL"),
        }

    def list_urls(self):
        urls = []
        for _, _, basename in router.registry:
            base = reverse(f"{basename}-list")
            urls += [base, f"{base}?q={MARK}", f"{base}?search={MARK}&page_size=100"]
        return urls + ["/api/v1/dashboard/", "/api/v1/notifications/"]

    def detail_urls(self):
        p, s, a, r, t, c, b = self.person.pk, self.stock.pk, self.asset.pk, self.rasset.pk, self.record.pk, self.recon.pk, self.sub.pk
        return [f"/api/v1/personnel/{p}/", f"/api/v1/personnel/{p}/history/", f"/api/v1/logistics/stock/{s}/",
                f"/api/v1/logistics/stock/{s}/transactions/", f"/api/v1/logistics/assets/{a}/", f"/api/v1/logistics/assets/{a}/events/",
                f"/api/v1/logistics/assets/{r}/", f"/api/v1/training/records/{t}/", f"/api/v1/logistics/reconciliations/{c}/",
                f"/api/v1/reports/submissions/{b}/"]

    def mutations(self):
        p, s, a, r, t, c, b = self.person.pk, self.stock.pk, self.asset.pk, self.rasset.pk, self.record.pk, self.recon.pk, self.sub.pk
        bari_unit = str(self.unit("BARI-ARMY-A").pk)
        return [("patch", f"/api/v1/personnel/{p}/", {"full_name": "Hacked", "version": 1}),
                ("post", f"/api/v1/personnel/{p}/change-status/", {"status": "retired", "version": 1}),
                ("post", f"/api/v1/personnel/{p}/transfer/", {"org_unit": bari_unit, "version": 1}),
                ("post", f"/api/v1/logistics/stock/{s}/transactions/", {"kind": "issue", "quantity": 1}),
                ("post", f"/api/v1/logistics/stock/{s}/transfer/", {"to_unit": bari_unit, "quantity": 1}),
                ("post", f"/api/v1/logistics/assets/{a}/change/", {"action": "lost", "note": "x", "version": 1}),
                ("post", f"/api/v1/logistics/assets/{r}/change/", {"action": "lost", "note": "x", "version": 1}),
                ("post", f"/api/v1/logistics/reconciliations/{c}/complete/", {"version": 1}),
                ("post", f"/api/v1/logistics/reconciliations/{c}/cancel/", {"version": 1}),
                ("post", f"/api/v1/training/records/{t}/status/", {"status": "withdrawn", "version": 1}),
                ("patch", f"/api/v1/training/records/{t}/", {"notes": "Hacked", "version": 1}),
                ("post", f"/api/v1/reports/submissions/{b}/amend/", {"comment": "x", "version": 1}),
                ("post", f"/api/v1/reports/submissions/{b}/start-review/", {"version": 1}),
                ("patch", f"/api/v1/reports/submissions/{b}/", {"title": "Hacked", "version": 1})]

    def test_no_bari_role_can_see_a_nugaal_canary_through_any_list_search_or_summary(self):
        for role, client in self.bari.items():
            for url in self.list_urls():
                r = client.get(url)
                body = r.content.decode()
                for marker in MARKERS:
                    self.assertNotIn(marker, body, f"{role} saw {marker} via {url}")

    def test_direct_object_urls_never_answer_for_a_nugaal_record(self):
        for role, client in self.bari.items():
            for url in self.detail_urls():
                self.assertIn(client.get(url).status_code, (403, 404), f"{role} {url}")

    def test_no_bari_role_can_change_a_nugaal_record_and_nothing_changes(self):
        for role, client in self.bari.items():
            for method, url, body in self.mutations():
                self.assertIn(getattr(client, method)(url, body, format="json").status_code, (403, 404), f"{role} {method} {url}")
        self.assertEqual(StockLine.objects.get(pk=self.stock.pk).quantity, 424242)
        self.assertEqual(Personnel.objects.get(pk=self.person.pk).full_name, f"{MARK} Person")
        self.assertEqual(Personnel.objects.get(pk=self.person.pk).status, "active")
        self.assertEqual(Asset.objects.get(pk=self.asset.pk).status, "in_stock")
        self.assertEqual(Asset.objects.get(pk=self.rasset.pk).status, "in_stock")
        self.assertEqual(Reconciliation.objects.get(pk=self.recon.pk).status, "open")
        self.assertEqual(TrainingRecord.objects.get(pk=self.record.pk).status, "enrolled")
        self.assertEqual(Submission.objects.get(pk=self.sub.pk).status, "approved")
        self.assertEqual(Submission.objects.get(pk=self.sub.pk).title, f"{MARK} report")

    @override_settings(PERSONNEL_EXPORT_ENABLED=True, REPORT_EXPORT_ENABLED=True)
    def test_exports_never_include_other_regions(self):
        for role, client in self.bari.items():
            for url in ("/api/v1/personnel/export/", "/api/v1/reports/summary/export/"):
                body = client.get(url, HTTP_ACCEPT="text/csv").content.decode()
                for marker in MARKERS:
                    self.assertNotIn(marker, body, f"{role} {url}")

    def test_the_canaries_are_visible_to_their_own_region_so_the_matrix_is_not_vacuous(self):
        n = self.nugaal
        self.assertIn(MARK, n["chief"].get("/api/v1/personnel/").content.decode())
        self.assertIn(MARK, n["chief"].get("/api/v1/reports/submissions/").content.decode())
        self.assertIn("777777", n["chief"].get("/api/v1/reports/summary/").content.decode())
        self.assertIn("424242", n["cust"].get("/api/v1/logistics/stock/").content.decode())
        self.assertIn(f"{MARK}-VEH", n["cust"].get("/api/v1/logistics/assets/").content.decode())
        self.assertNotIn(f"{MARK}-RX", n["cust"].get("/api/v1/logistics/assets/").content.decode())  # restricted stays hidden even at home
        self.assertIn(f"{MARK}-RX", n["rcust"].get("/api/v1/logistics/assets/").content.decode())
        self.assertIn(MARK, n["trainer"].get("/api/v1/training/records/").content.decode())
        self.assertEqual(n["rcust"].get(f"/api/v1/logistics/reconciliations/{self.recon.pk}/").status_code, 200)
