import pyotp
from rest_framework.test import APIClient

from apps.accounts.models import RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.core import crypto
from apps.core.testing import PASSWORD, BaseApiTest


class AuthTests(BaseApiTest):
    def test_unauthenticated_requests_are_denied(self):
        c = APIClient()
        for url in ("/api/v1/users/", "/api/v1/organization/units/", "/api/v1/ranks/",
                    "/api/v1/dashboard/", "/api/v1/audit-events/", "/api/v1/auth/me/"):
            r = c.get(url)
            self.assertIn(r.status_code, (401, 403), url)
            self.assertEqual(r.data["code"], "not_authenticated", url)

    def test_login_success_and_failure_are_audited(self):
        self.make_user("reader", "read_only")
        c = APIClient()
        self.assertEqual(self.login(c, "reader", "wrong-password-123").status_code, 401)
        r = self.login(c, "reader")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["username"], "reader")
        self.assertTrue(AuditEvent.objects.filter(action="auth.login", outcome="failure").exists())
        self.assertTrue(AuditEvent.objects.filter(action="auth.login", outcome="success").exists())

    def test_unknown_user_gets_same_error_as_bad_password(self):
        self.make_user("reader", "read_only")
        a = self.login(APIClient(), "nobody", "whatever-1234567")
        b = self.login(APIClient(), "reader", "whatever-1234567")
        self.assertEqual((a.status_code, a.data), (b.status_code, b.data))

    def test_lockout_after_repeated_failures(self):
        self.make_user("reader", "read_only")
        c = APIClient()
        for _ in range(5):
            self.login(c, "reader", "bad-password-0000")
        r = self.login(c, "reader")  # correct password, but locked
        self.assertEqual(r.status_code, 401)
        self.assertTrue(AuditEvent.objects.filter(metadata__reason="locked").exists())

    def test_login_requires_csrf_token(self):
        self.make_user("reader", "read_only")
        c = APIClient(enforce_csrf_checks=True)
        r = self.login(c, "reader")
        self.assertEqual(r.status_code, 403)

    def test_privileged_user_without_mfa_is_confined_until_enrolled(self):
        self.make_user("chief", "regional_chief", unit="BARI", mfa=False)
        c = APIClient()
        r = self.login(c, "chief")
        self.assertEqual(r.status_code, 200)
        self.assertIn("mfa_enrollment", r.data["restrictions"])
        blocked = c.get("/api/v1/organization/units/")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.data["code"], "restricted")
        setup = c.post("/api/v1/auth/mfa/setup/")
        self.assertEqual(setup.status_code, 200)
        bad = c.post("/api/v1/auth/mfa/confirm/", {"code": "000000"}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = c.post("/api/v1/auth/mfa/confirm/", {"code": pyotp.TOTP(setup.data["secret"]).now()}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data["restrictions"], [])
        self.assertEqual(c.get("/api/v1/organization/units/").status_code, 200)

    def test_otp_required_once_mfa_enabled(self):
        user = self.make_user("auditor1", "auditor")
        secret = crypto.decrypt(user.mfa_secret_enc)
        c = APIClient()
        r = self.login(c, "auditor1")
        self.assertEqual((r.status_code, r.data["code"]), (401, "otp_required"))
        self.assertEqual(self.login(c, "auditor1", otp="000000").data["code"], "invalid_otp")
        self.assertEqual(self.login(c, "auditor1", otp=pyotp.TOTP(secret).now()).status_code, 200)

    def test_must_change_password_confines_session_then_releases(self):
        self.make_user("newbie", "read_only", must_change_password=True)
        c = APIClient()
        r = self.login(c, "newbie")
        self.assertIn("password_change", r.data["restrictions"])
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 403)
        weak = c.post("/api/v1/auth/password/change/",
                      {"current_password": PASSWORD, "new_password": "short"}, format="json")
        self.assertEqual(weak.status_code, 400)
        ok = c.post("/api/v1/auth/password/change/",
                    {"current_password": PASSWORD, "new_password": "Another-Strong-Pass-77"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 200)

    def test_disabling_account_invalidates_live_session(self):
        admin = self.make_user("admin1", "hq_admin")
        victim = self.make_user("victim", "read_only")
        vc, ac = self.client_for(victim), self.client_for(admin)
        self.assertEqual(vc.get("/api/v1/ranks/").status_code, 200)
        self.assertEqual(ac.post(f"/api/v1/users/{victim.pk}/disable/").status_code, 200)
        self.assertEqual(vc.get("/api/v1/ranks/").status_code, 403)

    def test_revoking_role_assignment_cuts_access_immediately(self):
        admin = self.make_user("admin1", "hq_admin")
        user = self.make_user("reader", "read_only")
        uc, ac = self.client_for(user), self.client_for(admin)
        self.assertEqual(uc.get("/api/v1/ranks/").status_code, 200)
        assignment = RoleAssignment.objects.get(user=user)
        self.assertEqual(ac.post(f"/api/v1/users/{user.pk}/assignments/{assignment.pk}/revoke/").status_code, 204)
        self.assertEqual(uc.get("/api/v1/ranks/").status_code, 403)

    def test_admin_revoke_sessions_signs_user_out(self):
        admin = self.make_user("admin1", "hq_admin")
        user = self.make_user("reader", "read_only")
        uc, ac = self.client_for(user), self.client_for(admin)
        ac.post(f"/api/v1/users/{user.pk}/revoke-sessions/")
        self.assertEqual(uc.get("/api/v1/ranks/").status_code, 403)

    def test_logout_ends_session(self):
        user = self.make_user("reader", "read_only")
        c = self.client_for(user)
        self.assertEqual(c.post("/api/v1/auth/logout/").status_code, 204)
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 403)

    def test_user_without_any_role_can_log_in_but_reach_nothing(self):
        User.objects.create_user("norole", password=PASSWORD, full_name="No Role")
        c = APIClient()
        self.assertEqual(self.login(c, "norole").status_code, 200)
        for url in ("/api/v1/ranks/", "/api/v1/organization/units/", "/api/v1/dashboard/", "/api/v1/users/"):
            self.assertEqual(c.get(url).status_code, 403, url)


class ErrorShapeTests(BaseApiTest):
    """Regression: field error codes must reach the client as {errors: {field: [{message, code}]}}."""

    def test_codes_survive_for_hand_raised_validation_errors(self):
        c = self.client_for(self.make_user("rd", "read_only"))
        r = c.post("/api/v1/auth/password/change/", {"current_password": "nope-nope-nope", "new_password": "Another-Strong-Pass-77"}, format="json")
        self.assertEqual(self.codes(r, "current_password"), ["wrong_password"])
        r = c.patch("/api/v1/auth/me/", {"preferred_language": "fr"}, format="json")
        self.assertEqual(self.codes(r, "preferred_language"), ["invalid_choice"])
        adm = self.client_for(self.make_user("adm", "hq_admin"))
        r = adm.patch(f"/api/v1/users/{User.objects.get(username='rd').pk}/", {"full_name": "Q"}, format="json")
        self.assertEqual(self.codes(r, "version"), ["version_required"])
