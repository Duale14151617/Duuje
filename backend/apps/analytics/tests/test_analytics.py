"""Analytics (2.0): scope is inherited from the permissions that already govern each data set. Synthetic data only."""
from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from apps.accounts.models import Permission, Role
from apps.analytics.services import protect
from apps.core.testing import BaseApiTest
from apps.logistics.models import Asset, InventoryCategory, StockLine
from apps.organization.models import OrganizationalUnit as OU
from apps.personnel import services as pers
from apps.ranks.models import Rank
from apps.training.models import Course, TrainingRecord
from apps.workflows.models import ReportType, Submission

BASE = "/api/v1/analytics/"


class AnalyticsData(BaseApiTest):
    def setUp(self):
        super().setUp()
        Rank.objects.filter(branch__code="ARMY", code="PA-03").update(approval_status="approved", name_so="x")
        self.rank = Rank.objects.get(branch__code="ARMY", code="PA-03")
        self.bari = OU.objects.create(code="BARI-ARMY-A", name_en="Bari A", level="unit", parent=self.unit("BARI-ARMY"))
        self.karkaar = OU.objects.create(code="KARKAAR-ARMY-A", name_en="Karkaar A", level="unit", parent=self.unit("KARKAAR-ARMY"))
        self.bari_people = [self.person(f"Bari {i}", self.bari) for i in range(7)]
        self.karkaar_people = [self.person(f"Karkaar {i}", self.karkaar) for i in range(3)]

    def person(self, name, unit, status="active"):
        return pers.create_personnel(None, full_name=name, phone="", service_number=None, org_unit=unit, rank=self.rank,
                                     status=status, effective_date=None)

    def submission(self, unit, status="approved", **kw):
        now = timezone.now()
        defaults = dict(report_type=ReportType.objects.get(code="monthly_admin_report"), org_unit=unit, title="T",
                        period_start="2026-01-01", period_end="2026-01-31", submitter_username="x", status=status)
        if status == "approved":
            defaults.update(submitted_at=now - timedelta(hours=4), decided_at=now)
        defaults.update(kw)
        return Submission.objects.create(**defaults)

    def analyst_only(self):
        role = Role.objects.create(code="analyst_only", name_en="Analyst only")
        role.permissions.set(Permission.objects.filter(code__in=["analytics.view", "dashboard.view"]))
        return self.client_for(self.make_user("analyst", "analyst_only"))


class PersonnelAnalyticsTests(AnalyticsData):
    def test_headquarters_reporting_sees_everything_in_scope(self):
        r = self.client_for(self.make_user("hqr", "hq_reporting")).get(BASE + "personnel/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["by_status"]["total"], 10)
        self.assertEqual({row["unit"]["code"]: row["count"] for row in r.data["by_child_unit"]["rows"]}, {"BARI": 7, "KARKAAR": 3})

    def test_regional_chief_sees_only_their_region(self):
        c = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        r = c.get(BASE + "personnel/")
        self.assertEqual(r.data["by_status"]["total"], 7)
        self.assertEqual([row["unit"]["code"] for row in r.data["by_child_unit"]["rows"]], ["BARI"])

    def test_a_unit_outside_scope_is_not_found_not_forbidden(self):
        c = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        other = c.get(f"{BASE}personnel/?unit={self.karkaar.pk}")
        ghost = c.get(f"{BASE}personnel/?unit=00000000-0000-0000-0000-000000000000")
        self.assertEqual((other.status_code, ghost.status_code), (404, 404))
        self.assertEqual(other.json(), ghost.json())

    def test_drilling_into_a_unit_in_scope(self):
        c = self.client_for(self.make_user("hqr", "hq_reporting"))
        r = c.get(f"{BASE}personnel/?unit={self.unit('BARI').pk}")
        self.assertEqual(r.data["by_status"]["total"], 7)

    def test_status_counts_and_history(self):
        self.person("On leave", self.bari, status="on_leave")
        r = self.client_for(self.make_user("hqr", "hq_reporting")).get(BASE + "personnel/")
        statuses = {row["status"]: row["count"] for row in r.data["by_status"]["rows"]}
        self.assertEqual(statuses, {"active": 10, "on_leave": 1})
        self.assertTrue(r.data["changes_by_month"]["rows"])

    def test_bad_dates_are_validation_errors(self):
        c = self.client_for(self.make_user("hqr", "hq_reporting"))
        self.assertEqual(self.codes(c.get(BASE + "personnel/?from=nope"), "from"), ["invalid_date"])
        self.assertEqual(self.codes(c.get(BASE + "personnel/?from=2026-02-01&to=2026-01-01"), "to"), ["date_range_invalid"])
        self.assertEqual(self.codes(c.get(BASE + "personnel/?unit=zzz"), "unit"), ["invalid_id"])


class PermissionGateTests(AnalyticsData):
    def test_administrators_get_no_analytics_by_default(self):
        adm = self.client_for(self.make_user("adm", "hq_admin"))
        self.assertEqual(adm.get(BASE).status_code, 403)
        self.assertEqual(adm.get(BASE + "personnel/").status_code, 403)

    def test_analytics_view_alone_exposes_no_data(self):
        c = self.analyst_only()
        self.assertEqual(c.get(BASE).data, {"sections": []})
        for section in ("personnel", "reports", "logistics", "training"):
            self.assertEqual(c.get(f"{BASE}{section}/").status_code, 403, section)

    def test_sections_listed_follow_underlying_permissions(self):
        c = self.client_for(self.make_user("hqr", "hq_reporting"))
        self.assertEqual(sorted(c.get(BASE).data["sections"]), ["logistics", "personnel", "reports", "training"])

    def test_read_only(self):
        c = self.client_for(self.make_user("hqr", "hq_reporting"))
        for method in ("post", "patch", "put", "delete"):  # authorization is decided before the method is dispatched
            self.assertEqual(getattr(c, method)(BASE + "personnel/", {}, format="json").status_code, 403, method)


class ReportsAnalyticsTests(AnalyticsData):
    def test_only_approved_reports_are_counted_and_pipeline_needs_reports_view(self):
        self.submission(self.bari)
        self.submission(self.bari, status="draft")
        self.submission(self.karkaar)
        r = self.client_for(self.make_user("hqr", "hq_reporting")).get(BASE + "reports/")
        self.assertEqual(r.data["approved_by_type"]["total"], 2)
        pipeline = {x["status"]: x["count"] for x in r.data["pipeline"]["by_status"]["rows"]}
        self.assertEqual(pipeline, {"approved": 2, "draft": 1})
        self.assertAlmostEqual(r.data["pipeline"]["turnaround_hours"]["median"], 4.0, places=0)

    def test_regional_scope_applies_to_reports(self):
        self.submission(self.bari)
        self.submission(self.karkaar)
        c = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        self.assertEqual(c.get(BASE + "reports/").data["approved_by_type"]["total"], 1)


class LogisticsAnalyticsTests(AnalyticsData):
    def test_restricted_equipment_is_never_aggregated(self):
        general, restricted = InventoryCategory.objects.get(code="general_supplies"), InventoryCategory.objects.get(code="restricted_equipment")
        StockLine.objects.create(category=general, org_unit=self.bari, quantity=5, reorder_level=10)
        StockLine.objects.create(category=restricted, org_unit=self.bari, quantity=99)
        Asset.objects.create(category=InventoryCategory.objects.get(code="vehicles"), org_unit=self.bari, identifier="V-1")
        Asset.objects.create(category=InventoryCategory.objects.get(code="restricted_equipment"), org_unit=self.bari, identifier="R-1")
        r = self.client_for(self.make_user("hqr", "hq_reporting")).get(BASE + "logistics/")
        self.assertEqual([x["code"] for x in r.data["stock_by_category"]["rows"]], ["general_supplies"])
        self.assertEqual(r.data["low_stock_lines"], 1)
        self.assertEqual(r.data["assets_by_status"]["total"], 1)
        self.assertTrue(r.data["excludes_restricted"])


class TrainingAnalyticsTests(AnalyticsData):
    def test_completion_rate_ignores_withdrawn(self):
        course, today = Course.objects.get(code="first_aid"), timezone.localdate()
        TrainingRecord.objects.create(personnel=self.bari_people[0], course=course, start_date=today, status="completed", completed_on=today)
        TrainingRecord.objects.create(personnel=self.bari_people[1], course=course, start_date=today, status="in_progress")
        TrainingRecord.objects.create(personnel=self.bari_people[2], course=course, start_date=today, status="withdrawn")
        TrainingRecord.objects.create(personnel=self.karkaar_people[0], course=course, start_date=today, status="completed", completed_on=today)
        hq = self.client_for(self.make_user("hqr", "hq_reporting")).get(BASE + "training/")
        row = hq.data["by_course"]["rows"][0]
        self.assertEqual((row["count"], row["completion_rate"]), (4, 0.667))
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI")).get(BASE + "training/")
        self.assertEqual(chief.data["by_course"]["rows"][0]["count"], 3)


class SmallCellProtectionTests(SimpleTestCase):
    rows = [{"k": "a", "count": 2}, {"k": "b", "count": 9}, {"k": "c", "count": 6}]

    def test_internal_users_see_everything(self):
        out = protect(self.rows, 0)
        self.assertEqual((out["total"], out["suppressed"]), (17, False))

    def test_small_cells_and_the_total_are_withheld(self):
        out = protect(self.rows, 5)
        counts = {r["k"]: r["count"] for r in out["rows"]}
        self.assertIsNone(counts["a"])
        self.assertIsNone(out["total"])
        self.assertTrue(out["suppressed"])

    def test_a_lone_suppressed_cell_cannot_be_recovered_by_subtraction(self):
        out = protect(self.rows, 5)
        # a is below the threshold; c (the next smallest) is hidden too, so b alone gives no way to derive a.
        counts = {r["k"]: r["count"] for r in out["rows"]}
        self.assertEqual((counts["a"], counts["c"], counts["b"]), (None, None, 9))

    def test_nothing_suppressed_means_total_shown(self):
        out = protect([{"count": 8}, {"count": 9}], 5)
        self.assertEqual((out["total"], out["suppressed"]), (17, False))
