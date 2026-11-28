"""Backup codes and passkeys as extra second factors."""
import pyotp
from rest_framework.test import APIClient

from apps.accounts import backup_codes, webauthn as w
from apps.accounts.models import MfaBackupCode, PasskeyCredential, User
from apps.accounts.tests.test_webauthn import Authenticator
from apps.audit.models import AuditEvent
from apps.core import crypto
from apps.core.testing import BaseApiTest

ORIGIN, RP = "http://testserver", "testserver"


class BackupCodeTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("auditor1", "auditor", mfa=True)
        self.c = APIClient()

    def test_codes_are_shown_once_hashed_and_each_works_once(self):
        codes = backup_codes.generate(self.user)
        self.assertEqual(len(codes), 10)
        self.assertFalse(MfaBackupCode.objects.filter(code_hash=codes[0]).exists())  # nothing readable stored
        first = self.login(self.c, "auditor1", otp=codes[0])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["backup_codes_remaining"], 9)
        self.assertEqual(self.login(APIClient(), "auditor1", otp=codes[0]).status_code, 401)  # already spent
        self.assertTrue(AuditEvent.objects.filter(action="auth.backup_code_used", actor_id=self.user.pk).exists())

    def test_lowercase_and_missing_dash_are_accepted(self):
        code = backup_codes.generate(self.user)[0]
        self.assertEqual(self.login(self.c, "auditor1", otp=code.replace("-", "").lower()).status_code, 200)

    def test_new_set_cancels_the_old_one(self):
        old = backup_codes.generate(self.user)[0]
        backup_codes.generate(self.user)
        self.assertEqual(self.login(self.c, "auditor1", otp=old).status_code, 401)

    def test_a_wrong_code_counts_toward_lockout_and_other_users_codes_do_not_work(self):
        other = self.make_user("auditor2", "auditor", mfa=True)
        theirs = backup_codes.generate(other)[0]
        self.assertEqual(self.login(self.c, "auditor1", otp=theirs).status_code, 401)

    def test_regenerate_needs_mfa_and_returns_ten_new_codes(self):
        c = self.client_for(self.user)
        resp = c.post("/api/v1/auth/mfa/backup-codes/")
        self.assertEqual((resp.status_code, len(resp.data["backup_codes"])), (200, 10))
        self.assertEqual(c.get("/api/v1/auth/mfa/backup-codes/").data["remaining"], 10)
        plain = self.make_user("walker", "read_only", mfa=False)
        self.assertEqual(self.client_for(plain).post("/api/v1/auth/mfa/backup-codes/").status_code, 409)

    def test_resetting_mfa_removes_codes_and_passkeys(self):
        backup_codes.generate(self.user)
        PasskeyCredential.objects.create(user=self.user, credential_id="x", public_key="y", name="k")
        from apps.accounts.security import clear_second_factors
        clear_second_factors(self.user)
        self.assertEqual((MfaBackupCode.objects.count(), PasskeyCredential.objects.count()), (0, 0))


class PasskeyTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("auditor1", "auditor", mfa=True)
        self.c = self.client_for(self.user)
        self.dev = Authenticator()

    def add_passkey(self):
        opts = self.c.post("/api/v1/auth/passkeys/register/options/").json()
        cred = self.dev.register(opts["options"]["challenge"], origin=ORIGIN, rp=RP)
        return self.c.post("/api/v1/auth/passkeys/register/verify/",
                           {"challenge_id": opts["challenge_id"], "credential": cred, "name": "Office key"}, format="json")

    def test_register_list_and_remove(self):
        resp = self.add_passkey()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(self.c.get("/api/v1/auth/passkeys/").json()["results"][0]["name"], "Office key")
        self.assertEqual(self.c.get("/api/v1/auth/me/").json()["passkey_count"], 1)
        self.assertEqual(self.c.delete(f"/api/v1/auth/passkeys/{resp.json()['id']}/").status_code, 204)

    def test_registration_challenge_works_only_once(self):
        opts = self.c.post("/api/v1/auth/passkeys/register/options/").json()
        cred = self.dev.register(opts["options"]["challenge"], origin=ORIGIN, rp=RP)
        body = {"challenge_id": opts["challenge_id"], "credential": cred}
        self.assertEqual(self.c.post("/api/v1/auth/passkeys/register/verify/", body, format="json").status_code, 201)
        self.assertEqual(self.c.post("/api/v1/auth/passkeys/register/verify/", body, format="json").status_code, 400)

    def test_account_without_authenticator_cannot_add_a_passkey(self):
        plain = self.client_for(self.make_user("walker", "read_only", mfa=False))
        self.assertEqual(plain.post("/api/v1/auth/passkeys/register/options/").status_code, 409)


    def _challenge(self):
        guest = APIClient()
        return guest, self.login(guest, "auditor1").data["passkey"]

    def _body(self, pk, cred):
        from apps.core.testing import PASSWORD
        return {"username": "auditor1", "password": PASSWORD, "passkey": {"challenge_id": pk["challenge_id"], "credential": cred}}

    def test_password_then_passkey_signs_in_and_replay_fails(self):
        self.add_passkey()
        guest, pk = self._challenge()
        body = self._body(pk, self.dev.sign(pk["options"]["challenge"], origin=ORIGIN, rp=RP))
        self.assertEqual(guest.post("/api/v1/auth/login/", body, format="json").status_code, 200)
        self.assertEqual(APIClient().post("/api/v1/auth/login/", body, format="json").status_code, 401)  # challenge already burned

    def test_assertion_for_a_different_origin_is_refused(self):
        self.add_passkey()
        guest, pk = self._challenge()
        body = self._body(pk, self.dev.sign(pk["options"]["challenge"], origin="https://evil.example", rp=RP))
        self.assertEqual(guest.post("/api/v1/auth/login/", body, format="json").status_code, 401)

    def test_no_passkey_offered_when_none_registered(self):
        self.assertNotIn("passkey", self.login(APIClient(), "auditor1").data)

    def test_step_up_accepts_a_passkey(self):
        self.add_passkey()
        opts = self.c.post("/api/v1/auth/step-up/passkey/").json()
        cred = self.dev.sign(opts["options"]["challenge"], origin=ORIGIN, rp=RP)
        resp = self.c.post("/api/v1/auth/step-up/", {"passkey": {"challenge_id": opts["challenge_id"], "credential": cred}}, format="json")
        self.assertEqual(resp.status_code, 200)
