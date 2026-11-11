"""Strength trend: daily aggregate snapshots shown on the combined report. Synthetic data only."""
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from apps.organization.models import OrganizationalUnit as OU
from apps.personnel.models import Personnel, StrengthSnapshot
from apps.personnel import strength_trend

from .test_personnel import PersonnelBase

COMBINED = "/api/v1/reports/combined/"


class StrengthTrendTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.a = self.person("BARI-ARMY-A", "Alpha One")
        self.b = self.person("BARI-ARMY-A", "Alpha Two")
        self.gone = self.person("BARI-ARMY-B", "Bravo One")
        Personnel.objects.filter(pk=self.gone.pk).update(status="retired")

    def test_snapshot_counts_total_and_serving_and_is_idempotent(self):
        snap = strength_trend.take_snapshot()
        self.assertEqual((snap.total_all, snap.serving_all), (3, 2))
        again = strength_trend.take_snapshot()
        self.assertEqual(again.pk, snap.pk)
        self.assertEqual(StrengthSnapshot.objects.count(), 1)

    def test_restricted_units_are_left_out_of_the_open_series(self):
        OU.objects.filter(code="BARI-ARMY-B").update(restricted=True)
        snap = strength_trend.take_snapshot()
        self.assertEqual((snap.serving_all, snap.serving_open), (2, 2))
        OU.objects.filter(code="BARI-ARMY-A").update(restricted=True)
        StrengthSnapshot.objects.all().delete()
        snap = strength_trend.take_snapshot()
        self.assertEqual((snap.serving_all, snap.serving_open), (2, 0))

    def test_management_command_records_a_snapshot(self):
        call_command("snapshot_strength")
        self.assertEqual(StrengthSnapshot.objects.count(), 1)

    def test_series_is_chronological_and_limited_to_the_window(self):
        today = timezone.localdate()
        for back in (200, 3, 1):
            StrengthSnapshot.objects.create(date=today - timedelta(days=back), total_all=5, serving_all=4, total_open=5, serving_open=4)
        dates = [p["date"] for p in strength_trend.series(True)]
        self.assertEqual(dates, [(today - timedelta(days=3)).isoformat(), (today - timedelta(days=1)).isoformat()])

    def test_combined_report_includes_trend_and_records_today(self):
        hq = self.make_user("boss", "super_admin")
        r = self.client_for(hq).get(COMBINED)
        self.assertEqual(r.status_code, 200)
        trend = r.json()["trend"]
        self.assertEqual(len(trend), 1)
        self.assertEqual(trend[0]["date"], timezone.localdate().isoformat())
        self.assertEqual(trend[0]["serving"], 2)
