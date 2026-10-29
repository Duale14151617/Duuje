import json
import logging
from datetime import timedelta
from io import StringIO
from unittest import mock

import pyotp
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import PasswordResetToken, Role, RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.core import checks, crypto
from apps.core.logging import redact
from apps.core.testing import PASSWORD, BaseApiTest

NEW_PASSWORD = "Another-Strong-Pass-77"


class HeaderAndTransportTests(BaseApiTest):
    def test_api_responses_are_uncacheable_and_carry_security_headers(self):
        c = self.client_for(self.make_user("rd", "read_only"))
        r = c.get("/api/v1/ranks/")
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", r["Content-Security-Policy"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertIn("camera=()", r["Permissions-Policy"])
        self.assertTrue(r["X-Request-ID"])

    def test_no_cors_headers_are_ever_emitted(self):
        c = self.client_for(self.make_user("rd", "read_only"))
        r = c.get("/api/v1/ranks/", HTTP_ORIGIN="https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", r)
        pre = c.options("/api/v1/ranks/", HTTP_ORIGIN="https://evil.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", pre)
        self.assertNotIn("Access-Control-Allow-Credentials", pre)

    def test_unknown_host_header_is_rejected(self):
        self.assertEqual(APIClient().get("/api/v1/health/live/", HTTP_HOST="evil.example.com").status_code, 400)

    def test_oversized_requests_are_refused_before_parsing(self):
        r = APIClient().post("/api/v1/auth/login/", {"username": "a", "password": "b"}, format="json", CONTENT_LENGTH="99999999")
        self.assertEqual((r.status_code, r.json()["code"]), (413, "payload_too_large"))

    def test_unexpected_errors_do_not_leak_details(self):
        c = self.client_for(self.make_user("rd", "read_only"))
        c.raise_request_exception = False
        with mock.patch("apps.ranks.views.RankViewSet.list", side_effect=RuntimeError("boom secret-detail")):
            r = c.get("/api/v1/ranks/")
        self.assertEqual(r.status_code, 500)
        body = r.content.decode()
        self.assertNotIn("boom", body)
        self.assertNotIn("Traceback", body)
        self.assertEqual(json.loads(body)["code"], "server_error")
        self.assertTrue(json.loads(body)["correlation_id"])


class CsrfTests(BaseApiTest):
    MUTATING = [("/api/v1/users/", "post"), ("/api/v1/personnel/", "post"), ("/api/v1/reports/submissions/", "post"),
                ("/api/v1/logistics/stock/", "post"), ("/api/v1/training/records/", "post"), ("/api/v1/auth/logout/", "post"),
                ("/api/v1/auth/password/change/", "post"), ("/api/v1/auth/mfa/setup/", "post"), ("/api/v1/notifications/read-all/", "post")]

    def strict_client(self, user):
        c = APIClient(enforce_csrf_checks=True)
        c.force_login(user)
        s = c.session
        s["auth_epoch"], s["login_at"] = user.auth_epoch, int(timezone.now().timestamp())
        s.save()
        return c

    def test_every_state_changing_endpoint_requires_a_csrf_token(self):
        c = self.strict_client(self.make_user("adm", "hq_admin"))
        for url, _ in self.MUTATING:
            r = c.post(url, {}, format="json")
            self.assertEqual(r.status_code, 403, url)
            self.assertIn("CSRF", r.json()["detail"], url)
        self.assertEqual(c.patch("/api/v1/auth/me/", {"preferred_language": "so"}, format="json").status_code, 403)

    def test_a_valid_token_is_accepted(self):
        c = self.strict_client(self.make_user("rd", "read_only"))
        token = c.get("/api/v1/auth/csrf/").json()["csrf_token"]
        r = c.post("/api/v1/auth/password/change/", {"current_password": "wrong-wrong-wrong", "new_password": NEW_PASSWORD},
                   format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 400)  # got past CSRF, rejected on content

    def test_login_and_password_reset_also_require_csrf(self):
        c = APIClient(enforce_csrf_checks=True)
        self.assertEqual(c.post("/api/v1/auth/login/", {"username": "x", "password": "y"}, format="json").status_code, 403)
        self.assertEqual(c.post("/api/v1/auth/password/reset/", {"username": "x", "code": "y", "new_password": "z"}, format="json").status_code, 403)


class ThrottleTests(BaseApiTest):
    def test_login_is_rate_limited(self):
        self.make_user("rd", "read_only")
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"login": "3/min"}):
            codes = [self.login(APIClient(), "rd", "bad-password-000").status_code for _ in range(4)]
        self.assertEqual(codes, [401, 401, 401, 429])

    def test_spoofed_forwarded_for_header_cannot_dodge_the_limit(self):
        self.make_user("rd", "read_only")
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"login": "3/min"}):
            codes = []
            for i in range(4):
                c = APIClient()
                r = c.post("/api/v1/auth/login/", {"username": "rd", "password": "bad-password-000"}, format="json",
                           HTTP_X_FORWARDED_FOR=f"203.0.113.{i}")
                codes.append(r.status_code)
        self.assertEqual(codes, [401, 401, 401, 429])
        self.assertEqual(settings.NUM_PROXIES, 0)

    def test_bulk_endpoints_have_their_own_limit(self):
        c = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"bulk": "2/min"}):
            codes = [c.get("/api/v1/personnel/export/").status_code for _ in range(3)]
        self.assertEqual(codes, [403, 403, 429])  # 403 = export switched off, then throttled


class SessionTests(BaseApiTest):
    def test_session_cookie_flags_and_settings(self):
        self.make_user("rd", "read_only")
        r = self.login(APIClient(), "rd")
        cookie = r.cookies["sessionid"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 3600)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertLessEqual(settings.SESSION_ABSOLUTE_SECONDS, 86400)

    def test_session_id_changes_at_login(self):
        self.make_user("rd", "read_only")
        c = APIClient()
        s = c.session
        s["probe"] = 1
        s.save()
        before = c.cookies["sessionid"].value
        self.login(c, "rd")
        self.assertNotEqual(c.cookies["sessionid"].value, before)

    def test_logout_destroys_the_server_side_session(self):
        self.make_user("rd", "read_only")
        c = APIClient()
        self.login(c, "rd")
        key = c.cookies["sessionid"].value
        self.assertTrue(Session.objects.filter(session_key=key).exists())
        c.post("/api/v1/auth/logout/")
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_sessions_have_an_absolute_lifetime(self):
        self.make_user("rd", "read_only")
        c = APIClient()
        self.login(c, "rd")
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 200)
        s = c.session
        s["login_at"] = 0
        s.save()
        r = c.get("/api/v1/ranks/")
        self.assertEqual((r.status_code, r.json()["code"]), (403, "not_authenticated"))

    def test_a_session_without_login_time_is_not_trusted(self):
        user = self.make_user("rd", "read_only")
        c = APIClient()
        c.force_login(user)
        s = c.session
        s["auth_epoch"] = user.auth_epoch  # but no login_at
        s.save()
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 403)

    def test_password_change_signs_out_other_sessions(self):
        self.make_user("rd", "read_only")
        a, b = APIClient(), APIClient()
        self.login(a, "rd")
        self.login(b, "rd")
        r = a.post("/api/v1/auth/password/change/", {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(a.get("/api/v1/ranks/").status_code, 200)
        self.assertEqual(b.get("/api/v1/ranks/").status_code, 403)


class MfaReplayTests(BaseApiTest):
    T = 1_700_000_000.0

    def test_a_totp_code_works_once(self):
        user = self.make_user("aud", "auditor")
        totp = pyotp.TOTP(crypto.decrypt(user.mfa_secret_enc))
        with mock.patch("apps.accounts.security._now", return_value=self.T):
            self.assertEqual(self.login(APIClient(), "aud", otp=totp.at(self.T)).status_code, 200)
            again = self.login(APIClient(), "aud", otp=totp.at(self.T))
            self.assertEqual((again.status_code, again.data["code"]), (401, "invalid_otp"))
        with mock.patch("apps.accounts.security._now", return_value=self.T + 30):
            self.assertEqual(self.login(APIClient(), "aud", otp=totp.at(self.T + 30)).status_code, 200)
            self.assertEqual(self.login(APIClient(), "aud", otp=totp.at(self.T)).status_code, 401)  # older step stays dead

    def test_malformed_codes_are_rejected(self):
        self.make_user("aud", "auditor")
        for bad in ("12345", "1234567", "abcdef", "12 345"):
            self.assertEqual(self.login(APIClient(), "aud", otp=bad).status_code, 401, bad)

    def test_enrolment_code_cannot_be_replayed_to_log_in(self):
        self.make_user("chief", "regional_chief", unit="BARI", mfa=False)
        c = APIClient()
        self.login(c, "chief")
        setup = c.post("/api/v1/auth/mfa/setup/").json()
        totp = pyotp.TOTP(setup["secret"])
        with mock.patch("apps.accounts.security._now", return_value=self.T):
            ok = c.post("/api/v1/auth/mfa/confirm/", {"code": totp.at(self.T)}, format="json")
            self.assertEqual(ok.status_code, 200)
            replay = self.login(APIClient(), "chief", otp=totp.at(self.T))
            self.assertEqual(replay.status_code, 401)

    def test_every_privileged_role_is_confined_until_mfa_is_enrolled(self):
        privileged = set(Role.objects.filter(is_privileged=True).values_list("code", flat=True))
        self.assertEqual(privileged, {"hq_admin", "regional_chief", "branch_admin", "auditor", "restricted_custodian", "logistics_reviewer",
                                      "structure_approver", "command_authority", "super_admin",
                                      "payroll_officer", "payroll_approver", "survivor_officer", "payment_officer", "payment_reconciler",
                                      "weapons_custodian", "regional_commander", "transport_officer", "vehicle_disposal_approver"})
        unit_for = {"headquarters": "HQ", "region": "BARI", "branch_command": "BARI-ARMY", "unit": "BARI-ARMY"}
        for code in sorted(privileged):
            role = Role.objects.get(code=code)
            unit = unit_for[role.allowed_scope_levels[0]] if role.allowed_scope_levels else "BARI-ARMY"
            self.make_user(f"u-{code}", code, unit=unit, branch="ARMY" if role.requires_branch else None, mfa=False)
            c = APIClient()
            cache.clear()  # one login per role in a loop would otherwise hit the login throttle
            r = self.login(c, f"u-{code}")
            self.assertIn("mfa_enrollment", r.data["restrictions"], code)
            blocked = c.get("/api/v1/organization/units/")
            self.assertEqual((blocked.status_code, blocked.json()["code"]), (403, "restricted"), code)
        self.make_user("plain", "read_only", unit="BARI", mfa=False)
        cache.clear()
        self.assertEqual(self.login(APIClient(), "plain").data["restrictions"], [])


class PasswordResetTests(BaseApiTest):
    URL = "/api/v1/auth/password/reset/"

    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("adm", "hq_admin"))
        self.target = self.make_user("target", "read_only", unit="BARI", mfa=False)

    def issue(self, user=None):
        r = self.admin.post(f"/api/v1/users/{(user or self.target).pk}/issue-reset-code/")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data["code"]

    def redeem(self, code, password=NEW_PASSWORD, username="target"):
        return APIClient().post(self.URL, {"username": username, "code": code, "new_password": password}, format="json")

    def test_only_a_hash_is_stored_and_only_admins_can_issue(self):
        code = self.issue()
        token = PasswordResetToken.objects.get()
        self.assertEqual(len(token.token_hash), 64)
        self.assertNotIn(code, token.token_hash)
        self.assertEqual(self.client_for(self.make_user("off", "reporting_officer", unit="BARI-ARMY")).post(
            f"/api/v1/users/{self.target.pk}/issue-reset-code/").status_code, 403)

    def test_redeeming_sets_the_password_signs_everyone_out_and_clears_lockout(self):
        live = self.client_for(self.target)
        User.objects.filter(pk=self.target.pk).update(failed_login_count=3, locked_until=timezone.now() + timedelta(minutes=10))
        self.assertEqual(self.redeem(self.issue().lower()).status_code, 204)  # codes are case-insensitive
        self.assertEqual(live.get("/api/v1/ranks/").status_code, 403)
        self.assertEqual(self.login(APIClient(), "target", PASSWORD).status_code, 401)
        self.assertEqual(self.login(APIClient(), "target", NEW_PASSWORD).status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action="auth.password_reset", outcome="success").exists())

    def test_codes_are_single_use_and_newer_codes_supersede_older_ones(self):
        first = self.issue()
        second = self.issue()
        self.assertEqual(self.redeem(first).data["code"], "invalid_reset")
        self.assertEqual(self.redeem(second).status_code, 204)
        self.assertEqual(self.redeem(second, "Yet-Another-Pass-1234").status_code, 400)

    def test_every_failure_looks_the_same(self):
        code = self.issue()
        PasswordResetToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        results = [self.redeem(code), self.redeem("WRONG00000"), self.redeem(code, username="nobody"),
                   self.redeem(code, username="adm")]
        self.assertEqual({(r.status_code, json.dumps(r.data, sort_keys=True)) for r in results},
                         {(400, json.dumps({"code": "invalid_reset", "detail": "That reset code is not valid or has expired."}, sort_keys=True))})
        self.assertTrue(AuditEvent.objects.filter(action="auth.password_reset", outcome="failure").exists())

    def test_a_weak_password_does_not_burn_the_code(self):
        code = self.issue()
        bad = self.redeem(code, "short")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.redeem(code).status_code, 204)

    def test_reset_never_bypasses_mfa(self):
        user = self.make_user("secure", "auditor")
        code = self.issue(user)
        self.assertEqual(self.redeem(code, username="secure").status_code, 204)
        r = self.login(APIClient(), "secure", NEW_PASSWORD)
        self.assertEqual((r.status_code, r.data["code"]), (401, "otp_required"))

    def test_disabled_accounts_cannot_be_reset_and_redeeming_is_rate_limited(self):
        code = self.issue()
        self.admin.post(f"/api/v1/users/{self.target.pk}/disable/")
        self.assertEqual(self.redeem(code).status_code, 400)
        cache.clear()  # the redeem above already counted against the limit
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"reset": "2/min"}):
            codes = [self.redeem("GUESS00000").status_code for _ in range(3)]
        self.assertEqual(codes, [400, 400, 429])


class InvalidationTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("adm", "hq_admin"))

    def test_a_new_role_applies_immediately_to_a_live_session(self):
        user = User.objects.create_user("norole", password=PASSWORD, full_name="No Role")
        c = self.client_for(user)
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 403)
        r = self.admin.post(f"/api/v1/users/{user.pk}/assignments/", {"role": "read_only", "org_unit": str(self.unit("BARI").pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 200)

    def test_an_assignment_that_expires_mid_session_stops_working(self):
        user = self.make_user("temp", "read_only", unit="BARI")
        c = self.client_for(user)
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 200)
        RoleAssignment.objects.filter(user=user).update(valid_until=timezone.localdate() - timedelta(days=1))
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 403)

    def test_resetting_mfa_signs_the_user_out(self):
        user = self.make_user("aud", "auditor")
        c = self.client_for(user)
        self.assertEqual(c.get("/api/v1/audit-events/").status_code, 200)
        self.assertEqual(self.admin.post(f"/api/v1/users/{user.pk}/reset-mfa/").status_code, 200)
        self.assertEqual(c.get("/api/v1/audit-events/").status_code, 403)

    def test_disabled_users_lose_every_module_at_once_and_cannot_log_in(self):
        user = self.make_user("chief", "regional_chief", unit="BARI")
        c = self.client_for(user)
        urls = ["/api/v1/organization/units/", "/api/v1/personnel/", "/api/v1/reports/submissions/", "/api/v1/logistics/stock/",
                "/api/v1/training/records/", "/api/v1/dashboard/", "/api/v1/notifications/"]
        self.assertEqual([c.get(u).status_code for u in urls], [200] * len(urls))
        self.admin.post(f"/api/v1/users/{user.pk}/disable/")
        self.assertEqual([c.get(u).status_code for u in urls], [403] * len(urls))
        self.assertEqual(self.login(APIClient(), "chief").status_code, 401)
        self.admin.post(f"/api/v1/users/{user.pk}/enable/")
        self.assertEqual(self.login(APIClient(), "chief", otp=pyotp.TOTP(crypto.decrypt(User.objects.get(pk=user.pk).mfa_secret_enc)).now()).status_code, 200)

    def test_lockout_expires(self):
        self.make_user("rd", "read_only")
        for _ in range(5):
            self.login(APIClient(), "rd", "bad-password-000")
        self.assertEqual(self.login(APIClient(), "rd").status_code, 401)
        User.objects.filter(username="rd").update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.login(APIClient(), "rd").status_code, 200)

    def test_changing_someones_scope_takes_effect_on_the_next_request(self):
        user = self.make_user("chief", "regional_chief", unit="BARI")
        old = RoleAssignment.objects.get(user=user)
        self.assertEqual(self.admin.post(f"/api/v1/users/{user.pk}/assignments/{old.pk}/revoke/").status_code, 204)
        self.admin.post(f"/api/v1/users/{user.pk}/assignments/", {"role": "regional_chief", "org_unit": str(self.unit("NUGAAL").pk)}, format="json")
        fresh = self.client_for(User.objects.get(pk=user.pk))
        codes = {u["code"] for u in fresh.get("/api/v1/organization/units/?page_size=100").data["results"]}
        self.assertTrue(codes)
        self.assertTrue(all(c.startswith("NUGAAL") for c in codes), codes)


class AuditHardeningTests(BaseApiTest):
    def test_reading_the_audit_log_is_itself_audited(self):
        aud = self.client_for(self.make_user("aud", "auditor"))
        aud.get("/api/v1/audit-events/?action=auth.login")
        ev = AuditEvent.objects.get(action="audit.read")
        self.assertEqual((ev.actor_username, ev.metadata["filters"]), ("aud", {"action": "auth.login"}))

    def test_non_auditors_cannot_read_audit_and_the_attempt_is_recorded(self):
        c = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        self.assertEqual(c.get("/api/v1/audit-events/").status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="access.denied", actor_username="chief").exists())

    def test_history_and_ledger_models_are_append_only(self):
        from apps.core.appendonly import AppendOnlyModel
        from apps.core.db_triggers import append_only_trigger
        from apps.logistics.models import AssetEvent, StockTransaction
        from apps.personnel.models import PersonnelHistory
        from apps.workflows.models import ApprovalAction, SubmissionRevision
        for model in (PersonnelHistory, ApprovalAction, SubmissionRevision, StockTransaction, AssetEvent):
            self.assertTrue(issubclass(model, AppendOnlyModel), model.__name__)
        self.assertIsNotNone(append_only_trigger("x").reverse_code)

    def test_database_triggers_block_tampering(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL only")
        AuditEvent.objects.create(action="probe", outcome="success")
        with connection.cursor() as cur:
            cur.execute("SELECT tgname FROM pg_trigger WHERE tgname LIKE %s", ["%no_change"])
            names = {r[0] for r in cur.fetchall()}
        self.assertTrue({"audit_events_no_change", "stock_transactions_no_change", "asset_events_no_change",
                         "personnel_history_no_change", "approval_actions_no_change", "submission_revisions_no_change"} <= names)
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
            cur.execute("UPDATE audit_events SET action = 'tampered'")


class DeploymentCheckTests(SimpleTestCase):
    GOOD = dict(DEBUG=False, SECRET_KEY="k" * 64, ALLOWED_HOSTS=["armyhq.example.org"], CSRF_TRUSTED_ORIGINS=["https://armyhq.example.org"],
                SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, PERSONNEL_EXPORT_ENABLED=False, REPORT_EXPORT_ENABLED=False,
                ENABLE_API_DOCS=False, TRUST_PROXY_HEADERS=False, NUM_PROXIES=0)
    PG = {"ENGINE": "django.db.backends.postgresql", "OPTIONS": {"sslmode": "require"}}

    def ids(self, **overrides):
        from cryptography.fernet import Fernet
        cfg = {**self.GOOD, "FIELD_ENCRYPTION_KEY": Fernet.generate_key().decode(), **overrides}
        with override_settings(**cfg), mock.patch("apps.core.checks._db_settings", return_value=self.PG):
            return {m.id for m in checks.deployment_checks(None)}

    def test_a_correct_production_configuration_has_no_findings(self):
        self.assertEqual(self.ids(), set())

    def test_each_unsafe_setting_is_reported(self):
        self.assertIn("armyhq.E001", self.ids(DEBUG=True))
        self.assertIn("armyhq.E002", self.ids(SECRET_KEY="dev-only-short"))
        self.assertIn("armyhq.E003", self.ids(FIELD_ENCRYPTION_KEY="not-a-fernet-key"))
        self.assertIn("armyhq.E004", self.ids(ALLOWED_HOSTS=["*"]))
        self.assertIn("armyhq.E005", self.ids(CSRF_TRUSTED_ORIGINS=["http://plain.example.org"]))
        self.assertIn("armyhq.E007", self.ids(SESSION_COOKIE_SECURE=False))
        self.assertIn("armyhq.E008", self.ids(TRUST_PROXY_HEADERS=True, NUM_PROXIES=0))
        self.assertIn("armyhq.W002", self.ids(PERSONNEL_EXPORT_ENABLED=True))
        self.assertIn("armyhq.W003", self.ids(ENABLE_API_DOCS=True))
        with override_settings(**self.GOOD, FIELD_ENCRYPTION_KEY="x"), mock.patch(
                "apps.core.checks._db_settings", return_value={"ENGINE": "django.db.backends.sqlite3"}):
            self.assertIn("armyhq.E006", {m.id for m in checks.deployment_checks(None)})


class LoggingAndHealthTests(BaseApiTest):
    def test_secrets_are_redacted_from_log_text(self):
        for raw in ("login failed password=hunter2 user=bob", "payload {'new_password': 'hunter2'}",
                    'body {"temporary_password": "hunter2"}', "Authorization: Bearer abc.def.ghi", "otp=123456 csrf=abcdef"):
            self.assertNotIn("hunter2", redact(raw))
            self.assertNotIn("abc.def", redact(raw))
            self.assertNotIn("123456", redact(raw))
        self.assertIn("user=bob", redact("login failed password=hunter2 user=bob"))

    def test_redaction_filter_cleans_records(self):
        from apps.core.logging import RedactingFilter
        rec = logging.LogRecord("t", logging.INFO, __file__, 1, "pw %s", ("password=hunter2",), None)
        RedactingFilter().filter(rec)
        self.assertNotIn("hunter2", rec.getMessage())

    def test_health_endpoints_are_public_minimal_and_honest(self):
        c = APIClient()
        self.assertEqual(c.get("/api/v1/health/live/").json(), {"status": "ok"})
        r = c.get("/api/v1/health/ready/")
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok", "checks": {"database": True, "cache": True, "migrations": True}}))
        with mock.patch("apps.core.views._db_ok", return_value=False):
            r = c.get("/api/v1/health/ready/")
        self.assertEqual((r.status_code, r.json()["status"], r.json()["checks"]["database"]), (503, "degraded", False))


class OpsCommandTests(BaseApiTest):
    def test_security_report_counts_and_signals_breaches(self):
        for _ in range(3):
            AuditEvent.objects.create(action="auth.login", outcome="failure", metadata={"reason": "bad_password"})
        AuditEvent.objects.create(action="auth.login", outcome="failure", metadata={"reason": "bad_password+locked"})
        out = StringIO()
        call_command("security_report", stdout=out)
        report = json.loads(out.getvalue())
        self.assertEqual((report["failed_logins"], report["lockouts"], report["breaches"]), (4, 1, []))
        with self.assertRaises(SystemExit) as ctx:
            call_command("security_report", "--max-failed-logins", "2", stdout=StringIO())
        self.assertEqual(ctx.exception.code, 2)

    def test_import_batches_are_purged_by_retention_rules_only(self):
        from apps.personnel.models import ImportBatch
        now = timezone.now()
        live = ImportBatch.objects.create(rows=[{"x": 1}], expires_at=now + timedelta(hours=1))
        expired = ImportBatch.objects.create(rows=[{"x": 1}], expires_at=now - timedelta(minutes=1))
        done_old = ImportBatch.objects.create(rows=[], status="committed", expires_at=now)
        ImportBatch.objects.filter(pk=done_old.pk).update(created_at=now - timedelta(days=30))
        done_new = ImportBatch.objects.create(rows=[], status="committed", expires_at=now)
        call_command("purge_import_batches", "--dry-run", stdout=StringIO())
        self.assertEqual(ImportBatch.objects.count(), 4)
        call_command("purge_import_batches", stdout=StringIO())
        self.assertEqual(set(ImportBatch.objects.values_list("pk", flat=True)), {live.pk, done_new.pk})
        self.assertTrue(AuditEvent.objects.filter(action="personnel.import_purge").exists())
