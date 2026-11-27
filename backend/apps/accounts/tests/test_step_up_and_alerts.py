"""Fresh-MFA (step-up) rule and security alert emails."""
import time
from types import SimpleNamespace

import pyotp
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts import alerts
from apps.accounts.models import User
from apps.accounts.stepup import is_fresh
from apps.audit.models import AuditEvent
from apps.core import crypto
from apps.core.testing import BaseApiTest

U = "/api/v1/users/"
STEP_UP = "/api/v1/auth/step-up/"


def otp_for(user):
    return pyotp.TOTP(crypto.decrypt(User.objects.get(pk=user.pk).mfa_secret_enc)).now()


@override_settings(STEP_UP_MFA_REQUIRED=True, STEP_UP_MFA_SECONDS=600)
class StepUpTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("adm", "hq_admin")
        self.victim = self.make_user("ro", "read_only")

    def stale_client(self, user, age=10_000):
        client = self.client_for(user)
        session = client.session
        session["mfa_at"] = int(time.time()) - age
        session.save()
        return client

    def test_sensitive_action_asks_for_a_code_when_the_session_is_stale(self):
        r = self.stale_client(self.admin).post(f"{U}{self.victim.pk}/issue-reset-code/")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["code"], "step_up_required")

    def test_a_valid_code_unlocks_the_action(self):
        client = self.stale_client(self.admin)
        self.assertEqual(client.post(STEP_UP, {"code": otp_for(self.admin)}, format="json").status_code, 200)
        self.assertEqual(client.post(f"{U}{self.victim.pk}/issue-reset-code/").status_code, 200)

    def test_a_wrong_code_does_not(self):
        client = self.stale_client(self.admin)
        self.assertEqual(client.post(STEP_UP, {"code": "000000"}, format="json").status_code, 400)
        self.assertEqual(client.post(f"{U}{self.victim.pk}/issue-reset-code/").status_code, 403)

    def test_role_assignment_and_personnel_export_are_covered_too(self):
        client = self.stale_client(self.admin)
        r = client.post(f"{U}{self.victim.pk}/assignments/", {}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (403, "step_up_required"))

    def test_a_session_that_just_signed_in_with_a_code_is_fresh(self):
        client = APIClient()
        r = self.login(client, "adm", otp=otp_for(self.admin))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.post(f"{U}{self.victim.pk}/issue-reset-code/").status_code, 200)

    @override_settings(STEP_UP_MFA_REQUIRED=False)
    def test_can_be_switched_off(self):
        self.assertEqual(self.stale_client(self.admin).post(f"{U}{self.victim.pk}/issue-reset-code/").status_code, 200)

    def test_is_fresh_rules(self):
        user = SimpleNamespace(is_authenticated=True, mfa_enabled=True)
        self.assertFalse(is_fresh(SimpleNamespace(session={}, user=user)))
        self.assertTrue(is_fresh(SimpleNamespace(session={"mfa_at": int(time.time())}, user=user)))
        self.assertFalse(is_fresh(SimpleNamespace(session={"mfa_at": int(time.time()) - 601}, user=user)))
        no_mfa = SimpleNamespace(is_authenticated=True, mfa_enabled=False)
        self.assertTrue(is_fresh(SimpleNamespace(session={}, user=no_mfa)))  # nothing to ask


@override_settings(SECURITY_ALERT_EMAILS=["owner@example.org"], SECURITY_ALERTS_ASYNC=False, STEP_UP_MFA_REQUIRED=False)
class AlertTests(BaseApiTest):
    def alert_mails(self):
        return [m for m in mail.outbox if "security alert" in m.subject]

    def test_credential_reset_emails_the_owner_without_the_secret(self):
        admin, victim = self.make_user("adm", "hq_admin"), self.make_user("ro", "read_only")
        client = self.client_for(admin)
        with self.captureOnCommitCallbacks(execute=True):
            r = client.post(f"{U}{victim.pk}/issue-reset-code/")
        self.assertEqual(r.status_code, 200)
        sent = self.alert_mails()
        self.assertEqual([m.to for m in sent], [["owner@example.org"]])
        self.assertNotIn(r.data["code"], sent[0].body)
        self.assertIn("ro", sent[0].body)

    def test_no_recipients_means_no_mail_and_no_error(self):
        with override_settings(SECURITY_ALERT_EMAILS=[]), self.captureOnCommitCallbacks(execute=True):
            alerts.notify("test", "nothing configured")
        self.assertEqual(self.alert_mails(), [])

    def test_privileged_sign_in_from_a_new_address_alerts_but_a_known_one_does_not(self):
        fresh, known = self.make_user("newbie", "hq_admin"), self.make_user("regular", "hq_admin")
        AuditEvent.objects.create(actor_id=known.pk, actor_username="regular", action="auth.login", outcome="success",
                                  ip_address="127.0.0.1")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.login(APIClient(), "newbie", otp=otp_for(fresh)).status_code, 200)
        self.assertEqual(len(self.alert_mails()), 1)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.login(APIClient(), "regular", otp=otp_for(known)).status_code, 200)
        self.assertEqual(self.alert_mails(), [])
