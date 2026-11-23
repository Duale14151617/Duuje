"""Regression tests for the security review fixes (client IP, credential takeover, reset-code guessing, CSV injection)."""
from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.access_report import to_csv
from apps.accounts.models import PasswordResetToken, User
from apps.audit.services import client_ip
from apps.core.testing import BaseApiTest

U = "/api/v1/users/"
NEW_PASSWORD = "Brand-New-Passphrase-42"


class ClientIpTests(BaseApiTest):
    def _ip(self, **meta):
        return client_ip(RequestFactory().get("/", **meta))

    @override_settings(TRUST_PROXY_HEADERS=True, NUM_PROXIES=1)
    def test_uses_the_address_the_trusted_proxy_appended_not_the_forged_leftmost_one(self):
        self.assertEqual(self._ip(HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9", REMOTE_ADDR="10.0.0.1"), "203.0.113.9")

    @override_settings(TRUST_PROXY_HEADERS=True, NUM_PROXIES=1)
    def test_garbage_forwarded_value_is_discarded(self):
        self.assertEqual(self._ip(HTTP_X_FORWARDED_FOR="not-an-ip", REMOTE_ADDR="10.0.0.1"), "10.0.0.1")

    @override_settings(TRUST_PROXY_HEADERS=False)
    def test_forwarded_header_ignored_when_proxy_not_trusted(self):
        self.assertEqual(self._ip(HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.1"), "10.0.0.1")


class CredentialTakeoverTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("adm", "hq_admin"))

    def test_user_admin_cannot_take_over_an_account_that_holds_approval_authority(self):
        approver = self.make_user("pa", "payroll_approver")
        for action in ("issue-reset-code", "reset-password", "reset-mfa"):
            r = self.admin.post(f"{U}{approver.pk}/{action}/", {}, format="json")
            self.assertEqual(r.status_code, 403, action)

    def test_user_admin_still_manages_ordinary_accounts(self):
        victim = self.make_user("ro", "read_only")
        self.assertEqual(self.admin.post(f"{U}{victim.pk}/issue-reset-code/").status_code, 200)

    def test_super_admin_can_still_reset_anyone(self):
        approver = self.make_user("pa2", "payroll_approver")
        boss = self.client_for(self.make_user("boss", "super_admin"))
        self.assertEqual(boss.post(f"{U}{approver.pk}/issue-reset-code/").status_code, 200)


class ResetCodeGuessingTests(BaseApiTest):
    URL = "/api/v1/auth/password/reset/"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.admin = self.client_for(self.make_user("adm", "hq_admin"))
        self.target = self.make_user("target", "read_only", unit="BARI", mfa=False)

    def redeem(self, code):
        return APIClient().post(self.URL, {"username": "target", "code": code, "new_password": NEW_PASSWORD}, format="json")

    def test_wrong_codes_lock_redemption_for_the_account_even_across_addresses(self):
        code = self.admin.post(f"{U}{self.target.pk}/issue-reset-code/").data["code"]
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"reset": "1000/min"}):
            for i in range(10):
                self.assertEqual(self.redeem(f"WRONG{i:05d}").status_code, 400)
            self.assertEqual(self.redeem(code).status_code, 400)  # the right code is refused while the account is locked out
        self.assertFalse(PasswordResetToken.objects.get().used_at)

    def test_redeeming_retires_every_other_outstanding_code(self):
        code = self.admin.post(f"{U}{self.target.pk}/issue-reset-code/").data["code"]
        extra = PasswordResetToken.objects.create(user=self.target, token_hash="f" * 64,
                                                  expires_at=PasswordResetToken.objects.get().expires_at)
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"reset": "1000/min"}):
            self.assertEqual(self.redeem(code).status_code, 204)
        extra.refresh_from_db()
        self.assertIsNotNone(extra.used_at)
        self.assertTrue(User.objects.get(pk=self.target.pk).check_password(NEW_PASSWORD))


class AccessReportCsvTests(BaseApiTest):
    def test_formula_in_a_name_is_neutralised(self):
        report = {"users": [{"username": "x.y", "full_name": '=HYPERLINK("http://evil","click")', "active": True,
                             "mfa_enabled": False, "assignments": []}]}
        out = to_csv(report)
        self.assertIn("'=HYPERLINK", out)
        self.assertNotIn(",=HYPERLINK", out)
