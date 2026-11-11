"""Email verification and self-service "forgot password". Synthetic data only."""
import re
from datetime import timedelta
from unittest import mock

import pyotp
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import EmailVerificationCode, PasswordResetToken, User
from apps.audit.models import AuditEvent
from apps.core import crypto
from apps.core.testing import PASSWORD, BaseApiTest

FORGOT = "/api/v1/auth/password/forgot/"
RESET = "/api/v1/auth/password/reset/"
OPTIONS = "/api/v1/auth/options/"
VERIFY_REQUEST = "/api/v1/auth/email/verify/request/"
VERIFY_CONFIRM = "/api/v1/auth/email/verify/confirm/"
NEW_PASSWORD = "Another-Strong-Pass-77"
LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


def mark_verified(user):
    User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())


@override_settings(EMAIL_VERIFICATION_ENABLED=True, EMAIL_BACKEND=LOCMEM)
class EmailVerificationTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("clerk1", "read_only", mfa=False, email="clerk1@example.test")
        self.c = self.client_for(self.user)

    def emailed_code(self):
        return re.search(r"code is (\d{6})", mail.outbox[-1].body).group(1)

    def wrong_code(self):
        return "000000" if self.emailed_code() != "000000" else "111111"

    def test_disabled_by_default_returns_404(self):
        with override_settings(EMAIL_VERIFICATION_ENABLED=False):
            self.assertEqual(self.c.post(VERIFY_REQUEST, {}, format="json").status_code, 404)
            self.assertEqual(self.c.post(VERIFY_CONFIRM, {"code": "123456"}, format="json").status_code, 404)

    def test_signed_out_requests_are_refused(self):
        self.assertEqual(APIClient().post(VERIFY_REQUEST, {}, format="json").status_code, 403)
        self.assertEqual(APIClient().post(VERIFY_CONFIRM, {"code": "123456"}, format="json").status_code, 403)

    def test_request_emails_a_six_digit_code_and_stores_only_a_hash(self):
        self.assertEqual(self.c.post(VERIFY_REQUEST, {}, format="json").status_code, 204)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["clerk1@example.test"])
        row = EmailVerificationCode.objects.get()
        self.assertEqual(len(row.code_hash), 64)
        self.assertNotIn(self.emailed_code(), row.code_hash)

    def test_confirming_the_code_verifies_the_address(self):
        self.c.post(VERIFY_REQUEST, {}, format="json")
        r = self.c.post(VERIFY_CONFIRM, {"code": self.emailed_code()}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["email_verified"])
        self.assertEqual(r.data["email"], "clerk1@example.test")
        self.assertTrue(self.c.get("/api/v1/auth/me/").data["email_verified"])
        self.assertIsNotNone(User.objects.get(pk=self.user.pk).email_verified_at)
        self.assertTrue(AuditEvent.objects.filter(action="auth.email_verified", outcome="success").exists())
        again = self.c.post(VERIFY_REQUEST, {}, format="json")  # nothing left to verify
        self.assertEqual((again.status_code, again.data["code"]), (409, "already_verified"))

    def test_a_code_works_once(self):
        self.c.post(VERIFY_REQUEST, {}, format="json")
        code = self.emailed_code()
        self.assertEqual(self.c.post(VERIFY_CONFIRM, {"code": code}, format="json").status_code, 200)
        self.assertEqual(self.c.post(VERIFY_CONFIRM, {"code": code}, format="json").data["code"], "invalid_email_code")

    def test_five_wrong_guesses_burn_the_code_even_for_the_right_one(self):
        self.c.post(VERIFY_REQUEST, {}, format="json")
        right, wrong = self.emailed_code(), self.wrong_code()
        for _ in range(5):
            self.assertEqual(self.c.post(VERIFY_CONFIRM, {"code": wrong}, format="json").data["code"], "invalid_email_code")
        late = self.c.post(VERIFY_CONFIRM, {"code": right}, format="json")
        self.assertEqual((late.status_code, late.data["code"]), (400, "too_many_attempts"))
        self.assertIsNone(User.objects.get(pk=self.user.pk).email_verified_at)

    def test_an_expired_code_is_refused(self):
        self.c.post(VERIFY_REQUEST, {}, format="json")
        EmailVerificationCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.c.post(VERIFY_CONFIRM, {"code": self.emailed_code()}, format="json").data["code"], "invalid_email_code")

    def test_asking_again_within_a_minute_is_refused_and_a_failed_send_does_not_start_the_wait(self):
        self.assertEqual(self.c.post(VERIFY_REQUEST, {}, format="json").status_code, 204)
        soon = self.c.post(VERIFY_REQUEST, {}, format="json")
        self.assertEqual((soon.status_code, soon.data["code"]), (429, "too_soon"))
        self.assertEqual(len(mail.outbox), 1)
        EmailVerificationCode.objects.all().delete()
        with mock.patch("apps.accounts.views.send_mail", side_effect=OSError("smtp down")):
            failed = self.c.post(VERIFY_REQUEST, {}, format="json")
        self.assertEqual((failed.status_code, failed.data["code"]), (502, "email_send_failed"))
        self.assertEqual(self.c.post(VERIFY_REQUEST, {}, format="json").status_code, 204)  # no one-minute lockout after a failed send

    def test_a_different_address_needs_the_password_and_replaces_the_old_one(self):
        new = "clerk1.new@example.test"
        no_pw = self.c.post(VERIFY_REQUEST, {"email": new}, format="json")
        self.assertEqual(no_pw.status_code, 400)
        self.assertEqual(self.codes(no_pw, "password"), ["wrong_password"])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.c.post(VERIFY_REQUEST, {"email": new, "password": PASSWORD}, format="json").status_code, 204)
        self.assertEqual(mail.outbox[-1].to, [new])
        r = self.c.post(VERIFY_CONFIRM, {"code": self.emailed_code(), "email": new}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual((user.email, user.email_verified_at is not None), (new, True))
        self.assertTrue(AuditEvent.objects.filter(action="auth.email_changed").exists())

    def test_a_code_sent_to_one_address_cannot_confirm_another(self):
        self.c.post(VERIFY_REQUEST, {}, format="json")
        r = self.c.post(VERIFY_CONFIRM, {"code": self.emailed_code(), "email": "someone.else@example.test"}, format="json")
        self.assertEqual(r.data["code"], "invalid_email_code")

    def test_an_address_already_verified_on_another_account_cannot_be_claimed(self):
        other = self.make_user("clerk9", "read_only", mfa=False, email="shared@example.test")
        mark_verified(other)
        self.c.post(VERIFY_REQUEST, {"email": "shared@example.test", "password": PASSWORD}, format="json")
        r = self.c.post(VERIFY_CONFIRM, {"code": self.emailed_code(), "email": "shared@example.test"}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (409, "email_in_use"))
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "clerk1@example.test")

    def test_an_administrator_changing_the_address_clears_verification_but_a_case_change_does_not(self):
        mark_verified(self.user)
        admin = self.client_for(self.make_user("adm", "hq_admin"))
        version = User.objects.get(pk=self.user.pk).version
        same = admin.patch(f"/api/v1/users/{self.user.pk}/", {"email": "CLERK1@example.test", "version": version}, format="json")
        self.assertEqual(same.status_code, 200, same.data)
        self.assertTrue(same.data["email_verified"])
        moved = admin.patch(f"/api/v1/users/{self.user.pk}/", {"email": "typo@example.test", "version": version + 1}, format="json")
        self.assertEqual(moved.status_code, 200, moved.data)
        self.assertFalse(moved.data["email_verified"])
        self.assertIsNone(User.objects.get(pk=self.user.pk).email_verified_at)


@override_settings(EMAIL_VERIFICATION_ENABLED=True, PASSWORD_FORGOT_ENABLED=True, EMAIL_BACKEND=LOCMEM)
class ForgotPasswordTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("clerk2", "read_only", mfa=False, email="clerk2@example.test")
        mark_verified(self.user)
        self.c = APIClient()

    def ask(self, identifier="clerk2"):
        return self.c.post(FORGOT, {"identifier": identifier}, format="json")

    def emailed_code(self):
        return re.search(r"code is ([0-9A-F]{10})", mail.outbox[-1].body).group(1)

    def redeem(self, code, username="clerk2", password=NEW_PASSWORD, **extra):
        return APIClient().post(RESET, {"username": username, "code": code, "new_password": password, **extra}, format="json")

    def test_disabled_by_default_returns_404(self):
        with override_settings(PASSWORD_FORGOT_ENABLED=False):
            self.assertEqual(self.ask().status_code, 404)

    def test_options_tell_the_sign_in_page_what_is_switched_on(self):
        self.assertEqual(APIClient().get(OPTIONS).json(), {"password_forgot": True, "email_verification": True})
        with override_settings(PASSWORD_FORGOT_ENABLED=False, EMAIL_VERIFICATION_ENABLED=False):
            self.assertEqual(APIClient().get(OPTIONS).json(), {"password_forgot": False, "email_verification": False})

    def test_the_answer_is_identical_for_every_case_and_only_a_verified_account_gets_a_code(self):
        self.make_user("unverified", "read_only", mfa=False, email="unverified@example.test")
        self.make_user("noemail", "read_only", mfa=False)
        answers = [self.ask(name) for name in ("clerk2", "unverified", "noemail", "nobody")]
        self.assertEqual({(r.status_code, str(r.data)) for r in answers}, {(200, str(answers[0].data))})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["clerk2@example.test"])

    def test_the_verified_address_works_in_place_of_the_username(self):
        self.ask("CLERK2@Example.Test")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["clerk2@example.test"])

    def test_a_disabled_account_gets_nothing(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.ask()
        self.assertEqual(len(mail.outbox), 0)

    def test_an_address_that_matches_two_accounts_is_ambiguous_and_sends_nothing(self):
        twin = self.make_user("clerk3", "read_only", mfa=False, email="clerk2@example.test")
        mark_verified(twin)  # possible only through data fixes, since confirming refuses a second verified owner
        self.ask("clerk2@example.test")
        self.assertEqual(len(mail.outbox), 0)
        self.ask("clerk2")  # the username is still unambiguous
        self.assertEqual(len(mail.outbox), 1)

    def test_full_flow_sets_the_password_signs_everyone_out_and_the_code_works_once(self):
        live = self.client_for(self.user)
        self.ask()
        code = self.emailed_code()
        stored = PasswordResetToken.objects.get().token_hash  # only a hash is kept
        self.assertEqual(len(stored), 64)
        self.assertNotIn(code, stored)
        self.assertEqual(self.redeem(code.lower()).status_code, 204)  # case-insensitive, like administrator codes
        self.assertEqual(live.get("/api/v1/auth/me/").status_code, 403)  # old sessions are gone
        self.assertEqual(self.login(APIClient(), "clerk2", PASSWORD).status_code, 401)
        self.assertEqual(self.login(APIClient(), "clerk2", NEW_PASSWORD).status_code, 200)
        self.assertEqual(self.redeem(code, password="Yet-Another-Pass-1234").data["code"], "invalid_reset")
        self.assertIn("password was changed", mail.outbox[-1].subject)  # the owner is told
        self.assertTrue(AuditEvent.objects.filter(action="auth.password_forgot", outcome="success").exists())

    def test_asking_again_within_a_minute_sends_nothing_and_a_newer_code_supersedes_the_older_one(self):
        self.ask()
        self.ask()
        self.assertEqual(len(mail.outbox), 1)
        first = self.emailed_code()
        PasswordResetToken.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        self.ask()
        self.assertEqual(len(mail.outbox), 2)
        second = self.emailed_code()
        self.assertNotEqual(first, second)
        self.assertEqual(self.redeem(first).data["code"], "invalid_reset")
        self.assertEqual(self.redeem(second).status_code, 204)

    def test_an_emailed_code_does_not_cancel_a_code_an_administrator_issued(self):
        admin = self.client_for(self.make_user("adm", "hq_admin"))
        admin_code = admin.post(f"/api/v1/users/{self.user.pk}/issue-reset-code/").data["code"]
        self.ask()
        self.assertEqual(self.redeem(admin_code).status_code, 204)

    def test_an_authenticator_account_must_also_give_its_current_code_and_a_missing_one_does_not_burn_the_reset_code(self):
        secure = self.make_user("secure", "auditor", email="secure@example.test")  # privileged role: has an authenticator
        mark_verified(secure)
        self.ask("secure")
        code = self.emailed_code()
        missing = self.redeem(code, username="secure")
        self.assertEqual((missing.status_code, missing.data["code"]), (401, "otp_required"))
        wrong = self.redeem(code, username="secure", otp="000000")
        self.assertEqual((wrong.status_code, wrong.data["code"]), (401, "invalid_otp"))
        self.assertEqual(PasswordResetToken.objects.filter(used_at__isnull=True).count(), 1)  # still usable
        otp = pyotp.TOTP(crypto.decrypt(User.objects.get(pk=secure.pk).mfa_secret_enc)).now()
        self.assertEqual(self.redeem(code, username="secure", otp=otp).status_code, 204)

    def test_a_weak_password_does_not_burn_the_code(self):
        self.ask()
        code = self.emailed_code()
        self.assertEqual(self.redeem(code, password="short").status_code, 400)
        self.assertEqual(self.redeem(code).status_code, 204)

    def test_a_mail_failure_looks_the_same_to_the_requester_and_is_audited(self):
        ok = self.ask()
        PasswordResetToken.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        with mock.patch("apps.accounts.views.send_mail", side_effect=OSError("smtp down")):
            failed = self.ask()
        self.assertEqual((failed.status_code, failed.data), (ok.status_code, ok.data))
        self.assertTrue(AuditEvent.objects.filter(action="auth.password_forgot", outcome="failure").exists())
