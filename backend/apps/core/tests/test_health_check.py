"""Setup health check, test email and the backup heartbeat."""
from datetime import timedelta

from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import health
from apps.core.models import Heartbeat
from apps.core.testing import BaseApiTest

URL = "/api/v1/system/health-check/"
BEAT = "/api/v1/system/heartbeat/backup/"
TOKEN = "t" * 32


class HealthCheckTests(BaseApiTest):
    def codes(self, data):
        return {x["code"]: x["status"] for x in data["lines"]}

    def test_only_user_administrators_may_read_it(self):
        self.assertEqual(self.client_for(self.make_user("walker", "member", mfa=False)).get(URL).status_code, 403)
        self.assertEqual(self.client_for(self.make_user("adm", "hq_admin")).get(URL).status_code, 200)

    def test_problems_come_first_and_a_missing_backup_is_a_warning(self):
        data = self.client_for(self.make_user("adm", "hq_admin")).get(URL).json()
        self.assertEqual(self.codes(data)["backup"], "warn")
        statuses = [x["status"] for x in data["lines"]]
        self.assertEqual(statuses, sorted(statuses, key=["bad", "warn", "ok"].index))

    def test_a_stale_backup_is_bad_and_a_fresh_one_is_ok(self):
        Heartbeat.objects.create(name="backup", at=timezone.now() - timedelta(hours=60))
        self.assertEqual(self.codes(health.run())["backup"], "bad")
        health.record_beat("backup")
        self.assertEqual(self.codes(health.run())["backup"], "ok")

    @override_settings(BACKUP_HEARTBEAT_TOKEN=TOKEN)
    def test_heartbeat_needs_the_token(self):
        c = APIClient()
        self.assertEqual(c.post(BEAT).status_code, 404)
        self.assertEqual(c.post(BEAT, HTTP_X_CRON_TOKEN="wrong" * 8).status_code, 404)
        self.assertEqual(c.post(BEAT, HTTP_X_CRON_TOKEN=TOKEN).status_code, 204)
        self.assertTrue(Heartbeat.objects.filter(name="backup").exists())

    def test_heartbeat_is_off_when_no_token_is_set(self):
        self.assertEqual(APIClient().post(BEAT, HTTP_X_CRON_TOKEN=TOKEN).status_code, 404)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_test_email_goes_only_to_the_callers_verified_address(self):
        from apps.accounts.models import User
        adm = self.make_user("adm", "hq_admin")
        c = self.client_for(adm)
        self.assertEqual(c.post(URL + "test-email/").status_code, 409)
        User.objects.filter(pk=adm.pk).update(email="adm@example.test", email_verified_at=timezone.now())
        self.assertEqual(c.post(URL + "test-email/").status_code, 200)
        self.assertEqual([m.to for m in mail.outbox], [["adm@example.test"]])
