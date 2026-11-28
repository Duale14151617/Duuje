"""Unit report (PDF) and event alert emails."""
from types import SimpleNamespace

from django.core import mail
from django.test import override_settings

from apps.core.pdf import build_pdf
from apps.schedules import alerts, unitreport
from apps.schedules.models import AlertLog, AlertPreference, ReportSchedule
from apps.schedules.tests.test_schedules import LOCMEM, ScheduleBase

REPORT = "/api/v1/unit-report/"
PREFS = "/api/v1/alerts/preferences/"
SCHEDULES = "/api/v1/schedules/"


class PdfWriterTests(ScheduleBase):
    def test_it_makes_a_valid_multi_page_pdf_with_somali_and_odd_characters(self):
        rows = [[f"Rank {i} (Sarkaal) café – ا", i, i * 2] for i in range(120)]
        data = build_pdf("Test", [{"heading": "By rank", "columns": ["Rank", "A", "B"], "rows": rows}], org="Org", footer="f")
        self.assertTrue(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"))
        self.assertGreaterEqual(data.count(b"/Type /Page "), 2)


class UnitReportTests(ScheduleBase):
    def get(self, client, **q):
        q.setdefault("unit", str(self.unit("BARI").pk))
        return client.get(REPORT, q)

    def test_download_is_a_pdf_with_totals_and_no_names(self):
        r = self.get(self.client_a)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("attachment", r["Content-Disposition"])
        body = b"".join(r.streaming_content) if r.streaming else r.content
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertIn(b"Strength", body)
        self.assertNotIn(b"Secret Name Person", body)

    def test_another_region_is_not_found_and_a_bad_period_is_refused(self):
        c = self.client_for(self.cmd)  # regional chief of BARI
        self.assertEqual(self.get(c, unit=str(self.unit("NUGAAL").pk)).status_code, 404)
        self.assertEqual(self.get(self.client_a, **{"from": "2026-12-01", "to": "2026-11-01"}).status_code, 400)
        self.assertEqual(self.get(self.client_a, unit="not-an-id").status_code, 404)

    def test_period_helper(self):
        d0, d1 = unitreport.period("2026-11-01", "2026-11-10")
        self.assertEqual((d0.isoformat(), d1.isoformat()), ("2026-11-01", "2026-11-10"))
        with self.assertRaises(ValueError):
            unitreport.period("2024-01-01", "2026-11-10")


@override_settings(EMAIL_SEND_ASYNC=False, **LOCMEM)
class ScheduledPdfTests(ScheduleBase):
    def test_report_kind_is_checked_and_the_pdf_is_attached(self):
        bad = self.create(report="nonsense")
        self.assertEqual((bad.status_code, self.codes(bad, "report")), (400, ["invalid"]))
        made = self.create(report="unit")
        self.assertEqual((made.status_code, made.data["report"]), (201, "unit"))
        r = self.client_a.post(f"{SCHEDULES}{made.data['id']}/send-now/", {"to_me": True}, format="json")
        self.assertEqual((r.status_code, r.data["status"]), (200, "sent"), r.data)
        msg = mail.outbox[0]
        self.assertEqual(len(msg.attachments), 1)
        name, content, mime = msg.attachments[0]
        self.assertTrue(name.endswith(".pdf") and content.startswith(b"%PDF") and mime == "application/pdf")
        self.assertNotIn("Secret Name Person", msg.body)
        self.assertEqual(ReportSchedule.objects.get(pk=made.data["id"]).report, "unit")


@override_settings(EMAIL_SEND_ASYNC=False, **LOCMEM)
class AlertTests(ScheduleBase):
    def prefer(self, client, kinds):
        return client.patch(PREFS, {"kinds": kinds}, format="json")

    def test_a_person_only_sees_and_sets_the_alerts_their_permissions_allow(self):
        r = self.client_a.get(PREFS)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["email_ok"])
        self.assertIn("death_report", [k["kind"] for k in r.data["kinds"]])
        self.assertEqual(self.prefer(self.client_a, ["nonsense"]).status_code, 400)
        ok = self.prefer(self.client_a, ["death_report"])
        self.assertEqual(ok.status_code, 200)
        self.assertEqual([k["kind"] for k in ok.data["kinds"] if k["on"]], ["death_report"])
        off = self.prefer(self.client_a, [])
        self.assertEqual([k for k in off.data["kinds"] if k["on"]], [])
        self.assertFalse(AlertPreference.objects.filter(user=self.admin).exists())

    def test_death_alert_reaches_only_people_who_switched_it_on_and_names_nobody(self):
        self.prefer(self.client_a, ["death_report"])  # the chief of the region has not switched it on
        person = SimpleNamespace(org_unit=self.unit("BARI-ARMY-A"))
        record = SimpleNamespace(date_of_death="2026-11-01")
        with self.captureOnCommitCallbacks(execute=True):
            alerts.death_reported(person, record)
        self.assertEqual([m.to for m in mail.outbox], [["admin@example.test"]])
        self.assertIn("Alert", mail.outbox[0].subject)
        self.assertNotIn("Secret Name Person", mail.outbox[0].body)

    def test_a_person_without_access_to_the_unit_is_not_told(self):
        AlertPreference.objects.create(user=self.cmd, kind="death_report")  # chief of BARI, event is in NUGAAL
        with self.captureOnCommitCallbacks(execute=True):
            alerts.alert("death_report", self.unit("NUGAAL"), "x", ["line"])
        self.assertEqual(mail.outbox, [])

    def test_a_lasting_condition_is_sent_once(self):
        AlertPreference.objects.create(user=self.admin, kind="tracker_silent")
        unit = self.unit("BARI")
        first = alerts._deliver("tracker_silent", unit.pk, "s", ["l"], key="t1:20261101")
        again = alerts._deliver("tracker_silent", unit.pk, "s", ["l"], key="t1:20261101")
        self.assertEqual((first, again, len(mail.outbox)), (1, 0, 1))
        self.assertEqual(AlertLog.objects.filter(kind="tracker_silent").count(), 1)

    def test_with_nobody_to_tell_nothing_is_remembered(self):
        self.assertEqual(alerts._deliver("tracker_silent", self.unit("BARI").pk, "s", ["l"], key="t2:1"), 0)
        self.assertFalse(AlertLog.objects.exists())

    @override_settings(EVENT_ALERTS_ENABLED=False)
    def test_switched_off_server_wide(self):
        AlertPreference.objects.create(user=self.admin, kind="death_report")
        with self.captureOnCommitCallbacks(execute=True):
            alerts.alert("death_report", self.unit("BARI"), "x", ["line"])
        self.assertEqual(mail.outbox, [])
