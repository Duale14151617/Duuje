"""Last sign-in and failed attempts shown to the user, and the signed-in-only status footer data."""
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest

ME = "/api/v1/auth/me/"
STATUS = "/api/v1/system/status/"


class SignInInfoTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("walker", "hq_admin")

    def event(self, outcome, ago, ip="10.0.0.9"):
        # the audit table is append-only (no updates), so the date is given when the row is created
        return AuditEvent.objects.create(actor_id=self.user.pk, actor_username="walker", action="auth.login", outcome=outcome,
                                         ip_address=ip, occurred_at=timezone.now() - ago)

    def test_first_ever_sign_in_has_no_previous(self):
        c = self.client_for(self.user)
        self.assertIsNone(c.get(ME).json()["sign_in"])

    def test_shows_previous_sign_in_and_failures_since_but_not_the_current_one(self):
        self.event("success", timedelta(days=3), ip="10.0.0.5")   # an older sign-in
        self.event("success", timedelta(days=1), ip="10.0.0.7")   # the previous one
        self.event("failure", timedelta(hours=20))                # wrong password while away
        self.event("denied", timedelta(hours=19))                 # then locked
        self.event("failure", timedelta(days=2))                  # before the previous sign-in: not counted
        c = self.client_for(self.user)                            # signs in now (the current session)
        info = c.get(ME).json()["sign_in"]
        self.assertEqual((info["previous_ip"], info["failed_since"]), ("10.0.0.7", 2))
        self.assertIsNotNone(info["previous_at"])

    def test_another_users_attempts_never_appear(self):
        other = self.make_user("other.person", "read_only")
        AuditEvent.objects.create(actor_id=other.pk, actor_username="other.person", action="auth.login", outcome="failure",
                                  occurred_at=timezone.now() - timedelta(hours=2))
        self.event("success", timedelta(days=1))
        self.assertEqual(self.client_for(self.user).get(ME).json()["sign_in"]["failed_since"], 0)


@override_settings(APP_VERSION="9.9.9", APP_BUILD="abc1234", SUPPORT_CONTACT="help@example.org")
class SystemStatusTests(BaseApiTest):
    def test_signed_in_users_see_status_version_and_support(self):
        r = self.client_for(self.make_user("reader", "read_only")).get(STATUS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["version"], r.json()["build"], r.json()["support"]), ("9.9.9", "abc1234", "help@example.org"))
        self.assertIn(r.json()["status"], ("operational", "degraded"))

    def test_the_version_is_not_public(self):
        from rest_framework.test import APIClient
        r = APIClient().get(STATUS)
        self.assertIn(r.status_code, (401, 403))
        self.assertNotIn("9.9.9", r.content.decode())
        self.assertNotIn("9.9.9", APIClient().get("/api/v1/health/ready/").content.decode())
        self.assertNotIn("9.9.9", APIClient().get("/api/v1/profile/").content.decode())
