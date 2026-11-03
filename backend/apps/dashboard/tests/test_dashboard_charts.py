"""Dashboard chart series: personnel by region and the 7-day audit activity. Synthetic data only."""
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU, ServiceBranch
from apps.personnel import services as pers
from apps.ranks.models import Rank

URL = "/api/v1/dashboard/"


class DashboardChartSeries(BaseApiTest):
    def setUp(self):
        super().setUp()
        Rank.objects.filter(branch__code="ARMY", code="PA-03").update(approval_status="approved", name_so="x")
        self.rank = Rank.objects.get(branch__code="ARMY", code="PA-03")
        self.bari = OU.objects.create(code="BARI-ARMY-A", name_en="Bari A", level="unit", parent=self.unit("BARI-ARMY"))
        self.karkaar = OU.objects.create(code="KARKAAR-ARMY-A", name_en="Karkaar A", level="unit", parent=self.unit("KARKAAR-ARMY"))
        for i in range(7):  # 7 in Bari, 2 of them not active
            self.person(f"Bari {i}", self.bari, status="active" if i < 5 else "retired")
        for i in range(3):
            self.person(f"Karkaar {i}", self.karkaar)

    def person(self, name, unit, status="active"):
        return pers.create_personnel(None, full_name=name, phone="", service_number=None, org_unit=unit, rank=self.rank,
                                     status=status, effective_date=None)

    def by_region(self, user):
        return {r["code"]: r for r in self.client_for(user).get(URL).data["personnel"]["by_region"]}

    def test_headcount_per_region_with_active_split_largest_first(self):
        resp = self.client_for(self.make_user("adm", "super_admin")).get(URL)
        rows = resp.data["personnel"]["by_region"]
        self.assertEqual([r["code"] for r in rows][:2], ["BARI", "KARKAAR"])
        by = {r["code"]: r for r in rows}
        self.assertEqual((by["BARI"]["total"], by["BARI"]["active"]), (7, 5))
        self.assertEqual((by["KARKAAR"]["total"], by["KARKAAR"]["active"]), (3, 3))
        self.assertEqual(sum(r["total"] for r in rows), resp.data["personnel"]["total"])

    def test_a_regional_reader_only_gets_their_own_region(self):
        by = self.by_region(self.make_user("reader", "read_only", unit="BARI"))
        self.assertEqual(set(by), {"BARI"})
        self.assertEqual(by["BARI"]["total"], 7)

    def test_units_outside_any_region_are_grouped_as_one_headquarters_row(self):
        army = ServiceBranch.objects.get(code="ARMY")
        cmd = OU.objects.create(code="T-ARMY-HQ", name_en="Army HQ", level="branch_command", parent=self.unit("HQ"), branch=army)
        sub = OU.objects.create(code="T-ARMY-HQ-A", name_en="Directorate", level="unit", parent=cmd)
        self.person("Hq one", sub)
        self.person("Hq two", sub)
        by = self.by_region(self.make_user("adm2", "super_admin"))
        self.assertEqual(by[None]["total"], 2)
        self.assertEqual(by[None]["name_en"], "")
        self.assertEqual(by["BARI"]["total"], 7)  # regions are unaffected

    def test_activity_series_covers_seven_days_ending_today_with_zero_filled_gaps(self):
        now = timezone.now()
        AuditEvent.objects.create(action="t.a", outcome="success", occurred_at=now - timedelta(days=3))
        AuditEvent.objects.create(action="t.b", outcome="denied", occurred_at=now - timedelta(days=3))
        AuditEvent.objects.create(action="t.c", outcome="failure", occurred_at=now - timedelta(days=1))
        AuditEvent.objects.create(action="t.old", outcome="success", occurred_at=now - timedelta(days=30))  # outside the window
        daily = self.client_for(self.make_user("adm3", "hq_admin")).get(URL).data["audit"]["daily"]
        dates = [d["date"] for d in daily]
        self.assertEqual(len(daily), 7)
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(dates[-1], timezone.localdate().isoformat())
        by = {d["date"]: d for d in daily}
        day = lambda n: (timezone.localtime(now) - timedelta(days=n)).date().isoformat()
        self.assertEqual((by[day(3)]["events"], by[day(3)]["issues"]), (2, 1))
        self.assertEqual((by[day(1)]["events"], by[day(1)]["issues"]), (1, 1))
        self.assertEqual((by[day(5)]["events"], by[day(5)]["issues"]), (0, 0))
        self.assertTrue(all(d["issues"] <= d["events"] for d in daily))

    def test_activity_series_is_only_for_people_who_may_view_the_audit_log(self):
        data = self.client_for(self.make_user("reader2", "read_only", unit="BARI")).get(URL).data
        self.assertNotIn("audit", data)
        self.assertIn("by_region", data["personnel"])  # headcount follows personnel.view, not the audit permission


class DashboardActivityRange(BaseApiTest):
    URL = "/api/v1/dashboard/activity/"

    def get(self, user, **params):
        return self.client_for(user).get(self.URL, params)

    def test_thirty_day_range_is_zero_filled_and_ends_today(self):
        now = timezone.now()
        AuditEvent.objects.create(action="t.a", outcome="success", occurred_at=now - timedelta(days=20))
        AuditEvent.objects.create(action="t.b", outcome="denied", occurred_at=now - timedelta(days=20))
        resp = self.get(self.make_user("adm4", "hq_admin"), days=30)
        self.assertEqual(resp.status_code, 200)
        daily = resp.data["daily"]
        self.assertEqual(len(daily), 30)
        self.assertEqual(daily[-1]["date"], timezone.localdate().isoformat())
        day = (timezone.localtime(now) - timedelta(days=20)).date().isoformat()
        by = {d["date"]: d for d in daily}
        self.assertEqual((by[day]["events"], by[day]["issues"]), (2, 1))

    def test_default_is_seven_days_and_other_values_fall_back_to_seven(self):
        user = self.make_user("adm5", "hq_admin")
        self.assertEqual(len(self.get(user).data["daily"]), 7)
        self.assertEqual(len(self.get(user, days=90).data["daily"]), 7)
        self.assertEqual(len(self.get(user, days="abc").data["daily"]), 7)

    def test_only_people_who_may_view_the_audit_log_can_read_it(self):
        resp = self.get(self.make_user("reader3", "read_only", unit="BARI"), days=30)
        self.assertEqual(resp.status_code, 403)
