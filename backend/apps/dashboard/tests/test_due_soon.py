"""Due soon list and daily digest."""
from datetime import timedelta

from django.utils import timezone

from apps.core.testing import BaseApiTest
from apps.dashboard.digest import KIND, send_due_digests
from apps.dashboard.due import due_soon
from apps.workflows.models import Notification

URL = "/api/v1/due-soon/"


class DueSoonTests(BaseApiTest):
    def test_user_without_any_relevant_access_sees_nothing(self):
        user = self.make_user("walker", "member", mfa=False)
        data = self.client_for(user).get(URL).json()
        self.assertEqual(data["total"], 0)

    def test_digest_is_skipped_when_nothing_is_due_and_never_sent_twice_a_day(self):
        self.make_user("adm", "hq_admin")
        self.assertEqual(send_due_digests(), 0)
        self.assertFalse(Notification.objects.filter(kind=KIND).exists())

    def test_digest_goes_once_per_day_to_people_with_something_due(self):
        from apps.accounts.models import User
        adm = self.make_user("adm", "hq_admin")
        from unittest import mock
        with mock.patch("apps.dashboard.digest.due_soon", return_value={"total": 3, "groups": []}):
            self.assertGreaterEqual(send_due_digests(), 1)
            self.assertEqual(send_due_digests(), 0)  # already told today
        self.assertEqual(Notification.objects.filter(kind=KIND, recipient=adm).count(), 1)
