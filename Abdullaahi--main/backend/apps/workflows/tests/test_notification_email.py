"""Optional email alerts for in-app notifications: opt-in, verified address, rate limited, and never any details."""
from datetime import timedelta

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.leave.tests.test_leave import LeaveBase

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"
ME = "/api/v1/auth/me/"


@override_settings(NOTIFICATION_EMAILS_ENABLED=True, EMAIL_BACKEND=LOCMEM, EMAIL_SEND_ASYNC=False)
class NotificationEmailTests(LeaveBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def opt_in(self, user, verified=True, enabled=True):
        User.objects.filter(pk=user.pk).update(email="approver@example.org", notify_email=enabled,
                                               email_verified_at=timezone.now() if verified else None)

    def test_opted_in_approver_gets_one_generic_mail_when_leave_is_requested(self):
        self.opt_in(self.cmdr_user)
        self.assertEqual(self.ask().status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["approver@example.org"])
        self.assertIn("1 unread notification", m.body)
        for secret in ("Soldier One", "annual", "Family matter", str(self.day.year)):
            self.assertNotIn(secret, m.subject + m.body)  # nothing about the request leaves the app

    def test_no_mail_without_opt_in_verified_address_or_feature(self):
        self.opt_in(self.cmdr_user, enabled=False)
        self.ask()
        self.assertEqual(len(mail.outbox), 0)
        self.opt_in(self.cmdr_user, verified=False)
        self.ask(start_date=(self.day + timedelta(days=20)).isoformat(), end_date=(self.day + timedelta(days=21)).isoformat())
        self.assertEqual(len(mail.outbox), 0)
        self.opt_in(self.cmdr_user)
        cache.clear()
        with override_settings(NOTIFICATION_EMAILS_ENABLED=False):
            self.ask(start_date=(self.day + timedelta(days=40)).isoformat(), end_date=(self.day + timedelta(days=41)).isoformat())
        self.assertEqual(len(mail.outbox), 0)

    def test_at_most_one_mail_per_user_in_the_quiet_period(self):
        self.opt_in(self.cmdr_user)
        self.ask()
        self.ask(start_date=(self.day + timedelta(days=20)).isoformat(), end_date=(self.day + timedelta(days=21)).isoformat())
        self.assertEqual(len(mail.outbox), 1)  # the second notification is in the app; no second mail
        cache.clear()  # the quiet period ends
        self.ask(start_date=(self.day + timedelta(days=40)).isoformat(), end_date=(self.day + timedelta(days=41)).isoformat())
        self.assertEqual(len(mail.outbox), 2)

    def test_the_person_who_acted_is_not_mailed_about_their_own_request(self):
        self.opt_in(self.member_user)
        self.ask()
        self.assertEqual(len(mail.outbox), 0)


@override_settings(NOTIFICATION_EMAILS_ENABLED=True)
class NotifyEmailSettingTests(LeaveBase):
    def test_cannot_switch_on_without_a_verified_address(self):
        r = self.member.patch(ME, {"notify_email": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.member.get(ME).json()["notify_email"], False)

    def test_switch_on_and_off_with_a_verified_address(self):
        User.objects.filter(pk=self.member_user.pk).update(email="m@example.org", email_verified_at=timezone.now())
        r = self.member.patch(ME, {"notify_email": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["notify_email"])
        self.assertTrue(r.json()["features"]["notification_email"])
        self.assertFalse(self.member.patch(ME, {"notify_email": False}, format="json").json()["notify_email"])

    def test_language_change_still_works_and_feature_flag_is_enforced(self):
        self.assertEqual(self.member.patch(ME, {"preferred_language": "so"}, format="json").json()["preferred_language"], "so")
        User.objects.filter(pk=self.member_user.pk).update(email="m@example.org", email_verified_at=timezone.now())
        with override_settings(NOTIFICATION_EMAILS_ENABLED=False):
            self.assertEqual(self.member.patch(ME, {"notify_email": True}, format="json").status_code, 400)
