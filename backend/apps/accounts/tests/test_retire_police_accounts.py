from django.core.management import call_command

from apps.accounts.models import Role, RoleAssignment, User
from apps.core.testing import BaseApiTest


class RetirePoliceAccountsTests(BaseApiTest):
    """Police (CID included) accounts left in an older database are switched off; everyone else is untouched."""

    def setUp(self):
        super().setUp()
        Role.objects.create(code="cid_officer", name_en="CID officer", name_so="x")
        self.cid = self.make_user("cid1", "cid_officer")
        self.keep = self.make_user("keep", "hq_reporting")
        self.sa = self.make_user("boss", "super_admin")

    def test_police_accounts_are_disabled_and_others_are_not(self):
        call_command("retire_police", "--apply")
        self.assertFalse(User.objects.get(pk=self.cid.pk).is_active)
        self.assertFalse(RoleAssignment.objects.filter(user=self.cid, revoked_at__isnull=True).exists())
        self.assertTrue(User.objects.get(pk=self.keep.pk).is_active)
        self.assertTrue(RoleAssignment.objects.filter(user=self.keep, revoked_at__isnull=True).exists())

    def test_dry_run_changes_nothing(self):
        call_command("retire_police")
        self.assertTrue(User.objects.get(pk=self.cid.pk).is_active)

    def test_retired_roles_are_hidden_and_cannot_be_assigned(self):
        c = self.client_for(self.sa)
        codes = {r["code"] for r in c.get("/api/v1/roles/").json()}
        self.assertNotIn("cid_officer", codes)
        r = c.post(f"/api/v1/users/{self.keep.pk}/assignments/", {"role": "cid_officer", "org_unit": str(self.unit("HQ").pk)}, format="json")
        self.assertEqual(r.status_code, 400)


class RetirePoliceUnitsTests(BaseApiTest):
    def test_units_named_after_police_are_hidden_from_lists_and_purged_when_unused(self):
        from django.core.management import call_command

        from apps.organization.models import OrganizationalUnit as OU
        hq = OU.objects.filter(level="headquarters").first()
        stray = OU.objects.create(code="POL-CID-1", name_en="CID Bari", name_so="CID Bari", level="region", parent=hq)
        sa = self.client_for(self.make_user("boss", "super_admin"))
        ids = {u["id"] for u in sa.get("/api/v1/organization/units/?page_size=200").json()["results"]}
        self.assertIn(str(stray.pk), ids)
        call_command("retire_police", "--apply")
        ids = {u["id"] for u in sa.get("/api/v1/organization/units/?page_size=200").json()["results"]}
        self.assertNotIn(str(stray.pk), ids)
        call_command("retire_police", "--apply", "--purge")
        self.assertFalse(OU.objects.filter(pk=stray.pk).exists())
