"""Email recovery for a lost authenticator app. The authenticator stays the normal second factor. Synthetic data only."""
import re
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import MfaRecoveryCode, User
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, BaseApiTest

REQUEST = "/api/v1/auth/mfa/recover/request/"
REDEEM = "/api/v1/auth/mfa/recover/redeem/"


@override_settings(MFA_EMAIL_RECOVERY_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MfaEmailRecoveryTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("auditor1", "auditor", mfa=True, email="a1@example.test")
        self.c = APIClient()

    def ask(self, password=PASSWORD, username="auditor1"):
        return self.c.post(REQUEST, {"username": username, "password": password}, format="json")

    def emailed_code(self):
        return re.search(r"code is ([0-9A-F]{10})", mail.outbox[-1].body).group(1)

    def test_disabled_by_default_returns_404(self):
        with override_settings(MFA_EMAIL_RECOVERY_ENABLED=False):
            self.assertEqual(self.ask().status_code, 404)
            self.assertEqual(self.c.post(REDEEM, {"username": "auditor1", "password": PASSWORD, "code": "X"}, format="json").status_code, 404)

    def test_login_prompt_says_whether_email_recovery_exists(self):
        self.assertTrue(self.login(self.c, "auditor1").data["email_recovery"])
        with override_settings(MFA_EMAIL_RECOVERY_ENABLED=False):
            self.assertFalse(self.login(self.c, "auditor1").data["email_recovery"])

    def test_answer_is_the_same_for_right_wrong_and_unknown_and_only_the_right_one_sends(self):
        right, wrong, unknown = self.ask(), self.ask(password="wrong-password-000"), self.ask(username="nobody")
        self.assertEqual((right.status_code, right.data), (wrong.status_code, wrong.data))
        self.assertEqual((right.status_code, right.data), (unknown.status_code, unknown.data))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["a1@example.test"])

    def test_right_password_but_no_email_or_no_mfa_is_told_plainly_and_sends_nothing(self):
        self.make_user("noemail", "auditor", mfa=True)
        self.make_user("nomfa", "read_only", email="n@example.test")
        no_email, no_mfa = self.ask(username="noemail"), self.ask(username="nomfa")
        self.assertEqual((no_email.status_code, no_email.data["code"]), (400, "recovery_no_email"))
        self.assertEqual((no_mfa.status_code, no_mfa.data["code"]), (400, "recovery_no_mfa"))
        self.assertEqual(len(mail.outbox), 0)

    def test_wrong_password_never_learns_whether_an_email_exists(self):
        self.make_user("noemail", "auditor", mfa=True)
        a = self.ask(username="noemail", password="wrong-password-000")
        b = self.ask(username="auditor1", password="wrong-password-000")
        self.assertEqual((a.status_code, a.data), (b.status_code, b.data))

    def test_code_resets_enrolment_ends_sessions_and_works_once(self):
        self.ask()
        code = self.emailed_code()
        epoch = User.objects.get(pk=self.user.pk).auth_epoch
        r = self.c.post(REDEEM, {"username": "auditor1", "password": PASSWORD, "code": code}, format="json")
        self.assertEqual(r.status_code, 204)
        u = User.objects.get(pk=self.user.pk)
        self.assertFalse(u.mfa_enabled)
        self.assertEqual(u.mfa_secret_enc, "")
        self.assertGreater(u.auth_epoch, epoch)
        self.assertTrue(AuditEvent.objects.filter(action="auth.mfa_recovery", outcome="success").exists())
        self.assertEqual(len(mail.outbox), 2)  # the code, then the "authenticator was reset" notice
        again = self.c.post(REDEEM, {"username": "auditor1", "password": PASSWORD, "code": code}, format="json")
        self.assertEqual((again.status_code, again.data["code"]), (400, "invalid_recovery"))

    def test_password_is_still_required_and_wrong_code_expired_code_fail_identically(self):
        self.ask()
        code = self.emailed_code()
        bad_pw = self.c.post(REDEEM, {"username": "auditor1", "password": "wrong-password-000", "code": code}, format="json")
        bad_code = self.c.post(REDEEM, {"username": "auditor1", "password": PASSWORD, "code": "0000000000"}, format="json")
        self.assertEqual((bad_pw.status_code, bad_pw.data), (bad_code.status_code, bad_code.data))
        self.assertTrue(User.objects.get(pk=self.user.pk).mfa_enabled)
        MfaRecoveryCode.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        expired = self.c.post(REDEEM, {"username": "auditor1", "password": PASSWORD, "code": code}, format="json")
        self.assertEqual(expired.status_code, 400)
        self.assertTrue(User.objects.get(pk=self.user.pk).mfa_enabled)

    def test_new_request_replaces_the_old_code(self):
        self.ask()
        first = self.emailed_code()
        self.ask()
        second = self.emailed_code()
        self.assertNotEqual(first, second)
        r = self.c.post(REDEEM, {"username": "auditor1", "password": PASSWORD, "code": first}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_only_a_hash_of_the_code_is_stored(self):
        self.ask()
        code = self.emailed_code()
        self.assertNotIn(code, MfaRecoveryCode.objects.get().code_hash)

    def test_guessing_codes_leads_to_lockout(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"recover": "50/min"}):  # isolate the lockout from the rate limit
            for _ in range(5):
                self.c.post(REDEEM, {"username": "auditor1", "password": PASSWORD, "code": "0000000000"}, format="json")
        self.assertIsNotNone(User.objects.get(pk=self.user.pk).locked_until)

    def test_requests_are_rate_limited(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"recover": "2/min"}):
            codes = [self.ask().status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
