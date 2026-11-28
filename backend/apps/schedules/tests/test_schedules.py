"""Scheduled email reports."""
from datetime import datetime, timezone as dt_tz

from datetime import timedelta

from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.personnel.tests.test_personnel import PersonnelBase
from apps.schedules import services
from apps.schedules.models import ReportSchedule

URL = "/api/v1/schedules/"
LOCMEM = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


class ScheduleBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.admin = self.make_user("sched_admin", "hq_admin", email="admin@example.test", email_verified_at=now)
        self.client_a = self.client_for(self.admin)
        self.cmd = self.make_user("sched_cmd", "regional_chief", unit="BARI", email="cmd@example.test", email_verified_at=now)
        self.noverify = self.make_user("sched_nv", "regional_chief", unit="BARI", email="nv@example.test")
        self.person("BARI-ARMY-A", "Secret Name Person")

    def create(self, **kw):
        body = {"name": "Weekly strength", "org_unit": str(self.unit("BARI").pk), "frequency": "weekly", "weekday": 0, "send_hour": 7,
                "recipients": [str(self.cmd.pk)], **kw}
        return self.client_a.post(URL, body, format="json")


class TimingTests(ScheduleBase):
    def test_weekly_next_run_is_the_next_monday_at_the_chosen_hour(self):
        s = ReportSchedule(frequency="weekly", weekday=0, send_hour=7)
        nxt = services.compute_next(s, datetime(2026, 11, 20, 12, 0, tzinfo=dt_tz.utc))  # a Friday
        local = nxt.astimezone(services.tz())
        self.assertEqual((local.weekday(), local.hour, local.minute), (0, 7, 0))
        self.assertGreater(nxt, datetime(2026, 11, 20, 12, 0, tzinfo=dt_tz.utc))

    def test_monthly_and_daily(self):
        after = datetime(2026, 11, 20, 12, 0, tzinfo=dt_tz.utc)
        m = services.compute_next(ReportSchedule(frequency="monthly", day_of_month=1, send_hour=6), after).astimezone(services.tz())
        self.assertEqual((m.month, m.day, m.hour), (12, 1, 6))
        d = services.compute_next(ReportSchedule(frequency="daily", send_hour=23), after).astimezone(services.tz())
        self.assertEqual((d.day, d.hour), (20, 23))


class ApiTests(ScheduleBase):
    def test_create_and_recipient_rules(self):
        r = self.create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNotNone(r.data["next_run_at"])
        bad = self.create(recipients=[str(self.noverify.pk)])
        self.assertEqual((bad.status_code, self.codes(bad, "recipients")), (400, ["not_eligible"]))

    def test_regional_chief_cannot_schedule_another_region(self):
        c = self.client_for(self.cmd)
        r = c.post(URL, {"name": "x", "org_unit": str(self.unit("NUGAAL").pk), "frequency": "daily", "recipients": []}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_update_needs_current_version_and_can_pause(self):
        s = self.create().data
        r = self.client_a.patch(f"{URL}{s['id']}/", {"version": s["version"], "enabled": False}, format="json")
        self.assertEqual((r.status_code, r.data["enabled"], r.data["next_run_at"]), (200, False, None))
        stale = self.client_a.patch(f"{URL}{s['id']}/", {"version": s["version"], "name": "Again"}, format="json")
        self.assertEqual(stale.status_code, 400)

    def test_remove_is_a_post_action_and_the_delete_verb_is_not_offered(self):
        sid = self.create().json()["id"]
        self.assertEqual(self.client_a.delete(f"{URL}{sid}/").status_code, 405)
        self.assertEqual(self.client_a.post(f"{URL}{sid}/remove/", {}, format="json").status_code, 204)
        self.assertFalse(ReportSchedule.objects.filter(pk=sid).exists())


@override_settings(**LOCMEM)
class SendTests(ScheduleBase):
    def test_test_email_goes_to_the_caller_only_and_has_no_names(self):
        s = self.create().data
        r = self.client_a.post(f"{URL}{s['id']}/send-now/", {"to_me": True}, format="json")
        self.assertEqual((r.status_code, r.data["status"]), (200, "sent"), r.data)
        self.assertEqual([m.to for m in mail.outbox], [["admin@example.test"]])
        self.assertIn("STRENGTH", mail.outbox[0].body)
        self.assertNotIn("Secret Name Person", mail.outbox[0].body)

    def test_run_due_sends_once_and_moves_the_next_run(self):
        s = self.create().data
        ReportSchedule.objects.filter(pk=s["id"]).update(next_run_at=timezone.now() - timedelta(minutes=5))
        first = services.run_due()
        second = services.run_due()
        self.assertEqual((len(first), len(second)), (1, 0))
        self.assertEqual([m.to for m in mail.outbox], [["cmd@example.test"]])
        self.assertGreater(ReportSchedule.objects.get(pk=s["id"]).next_run_at, timezone.now())

    def test_recipient_who_lost_access_is_skipped(self):
        s = self.create().data
        ReportSchedule.objects.get(pk=s["id"]).recipients.add(self.noverify)  # no verified email: still never emailed
        status, _ = services.run(ReportSchedule.objects.get(pk=s["id"]))
        self.assertEqual(status, "sent")
        self.assertEqual(len(mail.outbox), 1)


class CronTriggerTests(ScheduleBase):
    def test_off_without_a_token_and_needs_the_right_one(self):
        c = APIClient()
        self.assertEqual(c.post(URL + "run-due/").status_code, 404)
        with override_settings(SCHEDULES_CRON_TOKEN="t" * 32):
            self.assertEqual(c.post(URL + "run-due/", HTTP_X_CRON_TOKEN="wrong").status_code, 404)
            ok = c.post(URL + "run-due/", HTTP_X_CRON_TOKEN="t" * 32)
            self.assertEqual((ok.status_code, ok.data["processed"]), (200, 0))
