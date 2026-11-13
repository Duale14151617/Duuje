"""Background email and encryption-key rotation."""
from io import StringIO
from unittest import mock

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core import crypto, mailer
from apps.core.testing import BaseApiTest

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


class FakePool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))

    def run_all(self):
        for fn, args in self.jobs:
            fn(*args)


@override_settings(EMAIL_BACKEND=LOCMEM)
class MailerTests(BaseApiTest):
    @override_settings(EMAIL_SEND_ASYNC=False)
    def test_inline_when_async_is_off(self):
        self.assertTrue(mailer.send_background("a@example.test", "s", "b"))
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_SEND_ASYNC=False)
    def test_a_send_failure_is_reported_not_raised(self):
        with mock.patch("apps.core.mailer.send_mail", side_effect=OSError("smtp down")):
            self.assertFalse(mailer.send_background("a@example.test", "s", "b"))

    @override_settings(EMAIL_SEND_ASYNC=True)
    def test_async_returns_at_once_and_sends_after_commit(self):
        pool = FakePool()
        with mock.patch("apps.core.mailer._executor", return_value=pool), self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(mailer.send_background("a@example.test", "s", "b"))
            self.assertEqual(pool.jobs, [])  # nothing is queued before the transaction commits
        self.assertEqual(len(pool.jobs), 1)
        self.assertEqual(mail.outbox, [])
        pool.run_all()
        self.assertEqual([m.to for m in mail.outbox], [["a@example.test"]])

    @override_settings(EMAIL_VERIFICATION_ENABLED=True, PASSWORD_FORGOT_ENABLED=True, EMAIL_SEND_ASYNC=True)
    def test_forgot_password_reply_does_not_wait_for_the_mail_provider(self):
        user = self.make_user("clerk3", "read_only", mfa=False, email="clerk3@example.test")
        User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())
        pool = FakePool()
        with mock.patch("apps.core.mailer._executor", return_value=pool), self.captureOnCommitCallbacks(execute=True):
            r = APIClient().post("/api/v1/auth/password/forgot/", {"identifier": "clerk3"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((len(pool.jobs), mail.outbox), (1, []))
        pool.run_all()
        self.assertIn("reset code", mail.outbox[0].subject)


class KeyRotationTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.current = settings.FIELD_ENCRYPTION_KEY
        self.new = Fernet.generate_key().decode()

    def test_old_data_reads_while_both_keys_are_listed_and_new_data_uses_the_first(self):
        token = crypto.encrypt("secret")
        with override_settings(FIELD_ENCRYPTION_KEY=f"{self.new},{self.current}"):
            self.assertEqual(crypto.decrypt(token), "secret")
            self.assertFalse(crypto.is_current(token.encode()))
            fresh = crypto.encrypt("later")
            self.assertTrue(crypto.is_current(fresh.encode()))
        with override_settings(FIELD_ENCRYPTION_KEY=self.new):
            self.assertEqual(crypto.decrypt(fresh), "later")
            with self.assertRaises(InvalidToken):
                crypto.decrypt(token)  # the old key is gone, so un-rotated data would be lost: hence the command

    def test_bytes_round_trip(self):
        blob = crypto.encrypt_bytes(b"\x00photo\xff")
        with override_settings(FIELD_ENCRYPTION_KEY=f"{self.new},{self.current}"):
            self.assertEqual(crypto.decrypt_bytes(blob), b"\x00photo\xff")
            self.assertEqual(crypto.decrypt_bytes(crypto.rotate(blob)), b"\x00photo\xff")

    def run_command(self, *args):
        out = StringIO()
        call_command("rotate_encryption_key", *args, stdout=out)
        return out.getvalue()

    def test_command_dry_run_changes_nothing_then_apply_moves_data_to_the_new_key(self):
        user = self.make_user("rot", "hq_admin")
        before = User.objects.get(pk=user.pk).mfa_secret_enc
        secret = crypto.decrypt(before)
        with override_settings(FIELD_ENCRYPTION_KEY=f"{self.new},{self.current}"):
            self.assertIn("Dry run", self.run_command())
            self.assertEqual(User.objects.get(pk=user.pk).mfa_secret_enc, before)
            self.assertIn("Everything is under the new key", self.run_command("--apply"))
            after = User.objects.get(pk=user.pk).mfa_secret_enc
            self.assertNotEqual(after, before)
            self.assertIn("0 value(s)", self.run_command("--apply").split("Rewrote")[1])  # repeating is a no-op
        with override_settings(FIELD_ENCRYPTION_KEY=self.new):
            self.assertEqual(crypto.decrypt(after), secret)  # readable with the new key alone

    def test_a_value_no_key_can_read_stops_the_run_loudly(self):
        user = self.make_user("rot2", "hq_admin")
        User.objects.filter(pk=user.pk).update(mfa_secret_enc=Fernet(Fernet.generate_key()).encrypt(b"x").decode())
        with override_settings(FIELD_ENCRYPTION_KEY=f"{self.new},{self.current}"), self.assertRaises(CommandError):
            self.run_command("--apply")

    def test_one_key_means_nothing_to_rotate(self):
        self.assertIn("nothing to rotate", self.run_command())


class HmacKeyTests(SimpleTestCase):
    def test_weapon_key_is_independent_of_which_encryption_key_is_first(self):
        from apps.personnel import profile
        with override_settings(FIELD_HMAC_KEY="pinned-key", FIELD_ENCRYPTION_KEY="A"):
            one = profile._weapon_key("W-123")
        with override_settings(FIELD_HMAC_KEY="pinned-key", FIELD_ENCRYPTION_KEY="B,A"):
            two = profile._weapon_key("W-123")
        self.assertEqual(one, two)
