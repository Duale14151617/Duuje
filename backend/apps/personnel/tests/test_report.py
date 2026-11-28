"""Personnel report: counts by unit, region and rank for a period, scope, audit, no personal data."""
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase

URL = "/api/v1/personnel-report/"


class PersonnelReportTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.cmdr = self.client_for(self.make_user("cmdr_r", "unit_commander", unit="BARI-ARMY"))
        self.nugaal = self.client_for(self.make_user("cmdr_rn", "unit_commander", unit="NUGAAL-ARMY"))
        self.member = self.client_for(self.make_user("plain_r", "member", unit="BARI-ARMY"))
        self.a = self.person("BARI-ARMY-A", "Report Person One")
        self.b = self.person("BARI-ARMY-A", "Report Person Two")
        self.c = self.person("BARI-ARMY-B", "Report Person Three")
        Personnel.objects.filter(pk=self.b.pk).update(status="retired")

    def get(self, c=None, **q):
        return (c or self.cmdr).get(URL, q)

    def test_counts_by_unit_region_and_rank(self):
        d = self.get().data
        self.assertEqual((d["totals"]["on_file"], d["totals"]["serving"], d["totals"]["retired"], d["totals"]["active"]), (3, 2, 1, 2))
        by = {u["unit"]["code"]: u for u in d["units"]}
        self.assertEqual((by["BARI-ARMY-A"]["on_file"], by["BARI-ARMY-A"]["serving"]), (2, 1))
        self.assertEqual(by["BARI-ARMY-B"]["on_file"], 1)
        self.assertEqual(sum(r["on_file"] for r in d["ranks"]), 3)
        self.assertEqual(len(d["regions"]), 1)  # everything sits under one region
        self.assertEqual(d["regions"][0]["on_file"], 3)

    def test_joined_counts_records_created_in_the_period(self):
        self.assertEqual(self.get().data["totals"]["joined"], 3)
        old = timezone.now() - timedelta(days=90)
        Personnel.objects.filter(pk=self.c.pk).update(created_at=old)
        self.assertEqual(self.get().data["totals"]["joined"], 2)

    def test_one_unit_limits_the_report(self):
        d = self.get(unit=str(self.unit("BARI-ARMY-B").pk)).data
        self.assertEqual(d["totals"]["on_file"], 1)

    def test_scope_and_permission(self):
        self.assertEqual(self.get(self.nugaal).data["totals"]["on_file"], 0)  # other region sees nothing of ours
        self.assertEqual(self.get(self.nugaal, unit=str(self.unit("BARI-ARMY-A").pk)).status_code, 404)
        self.assertEqual(self.get(self.member).status_code, 403)

    def test_period_rules(self):
        self.assertEqual(self.get(**{"from": "2026-02-01", "to": "2026-01-01"}).status_code, 400)
        self.assertEqual(self.get(**{"from": "nonsense"}).status_code, 400)
        self.assertEqual(self.get(**{"from": "2020-01-01", "to": "2026-01-01"}).status_code, 400)

    def test_no_personal_data_and_audited(self):
        d = self.get().data
        self.assertNotIn("Report Person", str(d))
        ev = AuditEvent.objects.get(action="personnel.read_report")
        self.assertNotIn("Report Person", str(ev.metadata))
