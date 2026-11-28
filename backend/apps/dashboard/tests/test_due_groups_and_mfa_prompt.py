"""Due-soon groups for fitness, leave, training and roles; and the sensitive-role two-step sign-in prompt."""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from apps.accounts import scope
from apps.accounts.models import Role, RoleAssignment
from apps.core.testing import BaseApiTest
from apps.dashboard.due import due_soon

URL = "/api/v1/due-soon/"


class DueGroupsTests(BaseApiTest):
    def test_new_groups_exist_for_an_admin_and_are_empty_without_data(self):
        adm = self.make_user("adm", "hq_admin")
        kinds = {g["kind"] for g in due_soon(adm)["groups"]}
        self.assertTrue({"fitness_reviews", "leave_ending", "training_open", "role_ends"} <= kinds)

    def test_role_assignment_ending_soon_is_listed_and_an_ended_long_ago_one_is_not(self):
        adm = self.make_user("adm", "hq_admin")
        today = timezone.localdate()
        soon = self.make_user("soon", "member", mfa=False)
        old = self.make_user("old", "member", mfa=False)
        role = Role.objects.get(code="member")
        hq = self.unit("HQ")
        RoleAssignment.objects.create(user=soon, role=role, org_unit=hq, valid_until=today + timedelta(days=5))
        RoleAssignment.objects.create(user=old, role=role, org_unit=hq, valid_until=today - timedelta(days=90))
        group = next(g for g in due_soon(adm)["groups"] if g["kind"] == "role_ends")
        labels = " ".join(i["label"] for i in group["items"])
        self.assertIn("soon", labels)
        self.assertNotIn("old", labels)

    def test_a_person_without_the_permission_gets_none_of_the_new_groups(self):
        user = self.make_user("walker", "member", mfa=False)
        self.assertEqual(self.client_for(user).get(URL).json()["total"], 0)


class SensitiveMfaTests(BaseApiTest):
    def test_sensitive_role_is_prompted_but_not_forced_by_default(self):
        user = self.make_user("pay", "member", mfa=False)
        with mock.patch.object(scope, "holds_sensitive", return_value=True):
            me = self.client_for(user).get("/api/v1/auth/me/").json()
        self.assertTrue(me["mfa_recommended"])
        self.assertIsNone(me["mfa_required_from"])
        self.assertEqual(me["restrictions"], [])

    def test_deadline_in_the_future_only_announces_the_date(self):
        user = self.make_user("pay", "member", mfa=False)
        date = (timezone.localdate() + timedelta(days=30)).isoformat()
        with override_settings(MFA_SENSITIVE_REQUIRED_FROM=date), mock.patch.object(scope, "holds_sensitive", return_value=True):
            me = self.client_for(user).get("/api/v1/auth/me/").json()
        self.assertEqual(me["mfa_required_from"], date)
        self.assertNotIn("mfa_enrollment", me["restrictions"])

    def test_after_the_deadline_two_step_sign_in_is_mandatory(self):
        user = self.make_user("pay", "member", mfa=False)
        date = (timezone.localdate() - timedelta(days=1)).isoformat()
        with override_settings(MFA_SENSITIVE_REQUIRED_FROM=date), mock.patch.object(scope, "holds_sensitive", return_value=True):
            self.assertTrue(scope.requires_mfa(user))
            self.assertFalse(scope.recommends_mfa(user))

    def test_ordinary_role_is_never_prompted(self):
        user = self.make_user("walker", "member", mfa=False)
        me = self.client_for(user).get("/api/v1/auth/me/").json()
        self.assertFalse(me["mfa_recommended"])
