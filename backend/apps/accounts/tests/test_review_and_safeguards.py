from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import scope
from apps.accounts.models import Permission, Role, RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase

U = "/api/v1/users/"


def verified(user, address):
    User.objects.filter(pk=user.pk).update(email=address, email_verified_at=timezone.now())


class UserListFilterTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.c = self.client_for(self.make_user("adm", "hq_admin"))
        self.a = self.make_user("has.all", "read_only")
        verified(self.a, "a@example.org")
        Personnel.objects.filter(pk=self.person("BARI-ARMY-A", "Has All").pk).update(account=self.a)
        User.objects.filter(pk=self.a.pk).update(last_login=timezone.now())
        self.b = User.objects.create_user("bare.one", password="x", full_name="Bare One", must_change_password=True)

    def names(self, **q):
        r = self.c.get(U, q)
        self.assertEqual(r.status_code, 200)
        return {u["username"] for u in r.json()["results"]}

    def test_filters(self):
        self.assertEqual(self.names(email_verified="true") & {"has.all", "bare.one", "adm"}, {"has.all"})
        self.assertIn("bare.one", self.names(email_verified="false"))
        self.assertEqual(self.names(linked="true") & {"has.all", "bare.one"}, {"has.all"})
        self.assertIn("bare.one", self.names(linked="false"))
        self.assertIn("bare.one", self.names(has_role="false"))
        self.assertNotIn("bare.one", self.names(has_role="true"))
        self.assertIn("bare.one", self.names(never_signed_in="true"))
        self.assertNotIn("has.all", self.names(never_signed_in="true"))
        self.assertEqual(self.names(temp_password="true") & {"has.all", "bare.one"}, {"bare.one"})

    def test_list_reports_role_count_link_and_verification(self):
        rows = {u["username"]: u for u in self.c.get(U).json()["results"]}
        self.assertEqual(rows["has.all"]["role_count"], 1)
        self.assertEqual(rows["bare.one"]["role_count"], 0)
        self.assertTrue(rows["has.all"]["email_verified"])
        self.assertIsNotNone(rows["has.all"]["personnel_id"])


class AdminSafeguardTests(PersonnelBase):
    def custom_admin_role(self):
        role = Role.objects.create(code="custom_admin", name_en="Custom admin", is_privileged=False)
        role.permissions.add(Permission.objects.get(code="users.manage"))
        return role

    def test_account_management_always_requires_mfa_even_on_an_unflagged_role(self):
        role = self.custom_admin_role()
        u = User.objects.create_user("sneaky", password="x", full_name="S")
        RoleAssignment.objects.create(user=u, role=role, org_unit=self.unit("HQ"))
        u = User.objects.get(pk=u.pk)
        self.assertTrue(scope.requires_mfa(u))
        r = self.login(APIClient(), "sneaky", password="x")
        self.assertIn("mfa_enrollment", r.data["restrictions"])

    def test_ordinary_role_does_not_force_mfa(self):
        self.assertFalse(scope.requires_mfa(self.make_user("plain", "read_only")))

    def test_granting_a_privileged_role_alerts_the_other_administrators_and_is_audited(self):
        actor, other = self.make_user("adm", "hq_admin"), self.make_user("adm2", "hq_admin")
        verified(actor, "actor@example.org")
        verified(other, "other@example.org")
        target = User.objects.create_user("newadmin", password="x", full_name="New Admin")
        c = self.client_for(actor)
        hq = str(self.unit("HQ").pk)
        mail.outbox.clear()
        r = c.post(f"{U}{target.pk}/assignments/", {"role": "hq_admin", "org_unit": hq}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([m.to for m in mail.outbox], [["other@example.org"]])  # not the actor
        self.assertIn("newadmin", mail.outbox[0].body)
        self.assertTrue(AuditEvent.objects.filter(action="role_assignment.privileged").exists())

    def test_ordinary_role_grant_sends_no_alert(self):
        actor, other = self.make_user("adm", "hq_admin"), self.make_user("adm2", "hq_admin")
        verified(other, "other@example.org")
        target = User.objects.create_user("plain.one", password="x", full_name="Plain One")
        mail.outbox.clear()
        r = self.client_for(actor).post(f"{U}{target.pk}/assignments/", {"role": "read_only", "org_unit": str(self.unit("HQ").pk)}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(AuditEvent.objects.filter(action="role_assignment.privileged").exists())

    def test_unverified_admin_addresses_are_never_used(self):
        actor, other = self.make_user("adm", "hq_admin"), self.make_user("adm2", "hq_admin")
        User.objects.filter(pk=other.pk).update(email="typo@example.org")  # typed by someone, never confirmed
        target = User.objects.create_user("t.two", password="x", full_name="T Two")
        mail.outbox.clear()
        self.client_for(actor).post(f"{U}{target.pk}/assignments/", {"role": "hq_admin", "org_unit": str(self.unit("HQ").pk)}, format="json")
        self.assertEqual(mail.outbox, [])


class AccessReviewTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.adm = self.make_user("adm", "hq_admin")
        self.c = self.client_for(self.adm)

    def codes(self):
        r = self.c.get(f"{U}access-review/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["findings"]

    def test_flags_each_kind_of_account(self):
        old = timezone.now() - timedelta(days=100)
        User.objects.create_user("norole", password="x", full_name="No Role")
        never = User.objects.create_user("never.in", password="x", full_name="Never In")
        User.objects.filter(pk=never.pk).update(created_at=old)
        dormant = self.make_user("dormant", "read_only")
        User.objects.filter(pk=dormant.pk).update(last_login=old)
        late = self.make_user("late.temp", "read_only", must_change_password=True)
        User.objects.filter(pk=late.pk).update(temp_password_expires_at=timezone.now() - timedelta(days=1))
        self.make_user("nomfa", "hq_admin", mfa=False)
        f = self.codes()
        self.assertIn("norole", f["no_role"]["items"])
        self.assertIn("never.in", f["never_signed_in"]["items"])
        self.assertTrue(any(i.startswith("dormant:") for i in f["dormant"]["items"]))
        self.assertIn("late.temp", f["temp_expired"]["items"])
        self.assertIn("nomfa: hq_admin", f["privileged_no_mfa"]["items"])
        self.assertNotIn("adm: hq_admin", f["privileged_no_mfa"]["items"])
        self.assertTrue(any(i.startswith("adm:") for i in f["global_access"]["items"]))

    def test_warns_when_there_are_fewer_than_two_administrators(self):
        self.assertEqual(self.codes()["few_admins"]["count"], 1)
        self.make_user("adm2", "hq_admin")
        self.assertEqual(self.codes()["few_admins"]["count"], 0)

    def test_review_is_for_user_administrators_and_is_audited(self):
        self.assertEqual(self.client_for(self.make_user("reader", "read_only")).get(f"{U}access-review/").status_code, 403)
        self.codes()
        self.assertTrue(AuditEvent.objects.filter(action="access.review", metadata__via="api").exists())

    def test_command_prints_and_emails_verified_administrators_only(self):
        other = self.make_user("adm2", "hq_admin")
        verified(other, "other@example.org")
        User.objects.filter(pk=self.adm.pk).update(email="unconfirmed@example.org")
        User.objects.create_user("norole", password="x", full_name="No Role")
        out = StringIO()
        mail.outbox.clear()
        call_command("access_review", "--email", stdout=out, stderr=StringIO())
        self.assertIn("norole", out.getvalue())
        self.assertEqual([m.to for m in mail.outbox], [["other@example.org"]])
        self.assertTrue(AuditEvent.objects.filter(action="access.review", metadata__via="management_command").exists())
