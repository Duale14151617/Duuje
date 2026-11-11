from apps.accounts.models import Role, User
from apps.core.management.commands.seed_reference_data import HQ_ADMIN_RESERVED
from apps.core.testing import BaseApiTest

U = "/api/v1/users/"


class HqAdminLimitsTests(BaseApiTest):
    """The headquarters administrator works every day, but cannot take authority from the super administrator."""

    def setUp(self):
        super().setUp()
        self.sa = self.make_user("boss", "super_admin")
        self.adm = self.make_user("adm", "hq_admin")
        self.c = self.client_for(self.adm)

    def test_hq_admin_holds_no_reserved_permission(self):
        have = set(Role.objects.get(code="hq_admin").permissions.values_list("code", flat=True))
        self.assertFalse(have & HQ_ADMIN_RESERVED)
        self.assertTrue({"personnel.manage", "logistics.manage", "weapons.manage", "vehicles.edit", "training.manage"} <= have)

    def test_cannot_reset_or_disable_a_super_administrator(self):
        for action in ("reset-password", "reset-mfa", "disable", "issue-reset-code", "revoke-sessions"):
            r = self.c.post(f"{U}{self.sa.pk}/{action}/", {}, format="json")
            self.assertEqual(r.status_code, 403, action)

    def test_cannot_hand_out_the_super_administrator_role(self):
        hq = self.unit("HQ")
        for target in (self.adm, self.make_user("other", "read_only")):
            r = self.c.post(f"{U}{target.pk}/assignments/", {"role": "super_admin", "org_unit": str(hq.pk)}, format="json")
            self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.get(pk=self.adm.pk).assignments.filter(role__code="super_admin").exists())

    def test_cannot_hand_out_an_approval_role_but_can_assign_ordinary_ones(self):
        other = self.make_user("other2", "read_only")
        hq = self.unit("HQ")
        r = self.c.post(f"{U}{other.pk}/assignments/", {"role": "logistics_reviewer", "org_unit": str(hq.pk)}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.c.post(f"{U}{other.pk}/assignments/", {"role": "hq_reporting", "org_unit": str(hq.pk)}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_super_administrator_can_still_do_all_of_it(self):
        r = self.client_for(self.sa).post(f"{U}{self.adm.pk}/assignments/",
                                          {"role": "logistics_reviewer", "org_unit": str(self.unit("HQ").pk)}, format="json")
        self.assertEqual(r.status_code, 201)
