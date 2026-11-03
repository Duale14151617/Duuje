from apps.accounts import scope
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU


class ScopeTests(BaseApiTest):
    def codes_in(self, resp):
        return {u["code"] for u in resp.data["results"]}

    def test_global_user_sees_whole_tree(self):
        c = self.client_for(self.make_user("hqr", "hq_reporting"))
        r = c.get("/api/v1/organization/units/?page_size=100")
        self.assertEqual(r.data["count"], 1 + 4 + 8)  # headquarters, 4 regions, Army and Navy command in each

    def test_regional_chief_is_confined_to_own_region(self):
        c = self.client_for(self.make_user("bari", "regional_chief", unit="BARI"))
        r = c.get("/api/v1/organization/units/?page_size=100")
        codes = self.codes_in(r)
        self.assertIn("BARI-ARMY", codes)
        self.assertFalse({"NUGAAL", "NUGAAL-ARMY", "HQ", "MUDUG-NAVY"} & codes)

    def test_direct_lookup_and_edit_outside_scope_is_404(self):
        c = self.client_for(self.make_user("bari", "regional_chief", unit="BARI"))
        other = self.unit("NUGAAL-ARMY")
        self.assertEqual(c.get(f"/api/v1/organization/units/{other.pk}/").status_code, 404)
        r = c.patch(f"/api/v1/organization/units/{other.pk}/", {"name_en": "x", "version": 1}, format="json")
        # A regional chief holds no org.manage at all, so the edit is refused outright (403); a manager out of scope gets 404.
        self.assertIn(r.status_code, (403, 404))

    def test_filter_parameters_cannot_widen_scope(self):
        c = self.client_for(self.make_user("bari", "regional_chief", unit="BARI"))
        nugaal = self.unit("NUGAAL")
        r = c.get(f"/api/v1/organization/units/?parent={nugaal.pk}")
        self.assertEqual(r.data["count"], 0)

    def test_branch_limited_admin_sees_only_their_branch(self):
        c = self.client_for(self.make_user("armyadm", "branch_admin", unit="BARI", branch="ARMY"))
        codes = self.codes_in(c.get("/api/v1/organization/units/?page_size=100"))
        self.assertEqual(codes, {"BARI-ARMY"})
        navy = self.unit("BARI-NAVY")
        self.assertEqual(c.get(f"/api/v1/organization/units/{navy.pk}/").status_code, 404)

    def test_branch_admin_can_create_in_scope_but_not_outside(self):
        c = self.client_for(self.make_user("armyadm", "branch_admin", unit="BARI", branch="ARMY"))
        body = {"code": "bari-army-u1", "name_en": "Unit 1", "level": "unit",
                "parent": str(self.unit("BARI-ARMY").pk)}
        r = c.post("/api/v1/organization/units/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["code"], "BARI-ARMY-U1")
        for parent in ("BARI-NAVY", "NUGAAL-ARMY"):
            bad = c.post("/api/v1/organization/units/", {**body, "code": "X1", "parent": str(self.unit(parent).pk)},
                         format="json")
            self.assertEqual(bad.status_code, 400, parent)
            self.assertIn("out_of_scope", self.codes(bad, "parent"))

    def test_read_only_roles_cannot_modify_structure(self):
        c = self.client_for(self.make_user("bari", "regional_chief", unit="BARI"))
        body = {"code": "NEW1", "name_en": "New", "level": "unit", "parent": str(self.unit("BARI-ARMY").pk)}
        self.assertEqual(c.post("/api/v1/organization/units/", body, format="json").status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="access.denied", outcome="denied").exists())

    def test_unit_admin_scope_is_subtree_only(self):
        parent = self.unit("BARI-ARMY")
        OU.objects.create(code="U-A", name_en="A", level="unit", parent=parent)
        OU.objects.create(code="U-B", name_en="B", level="unit", parent=parent)
        c = self.client_for(self.make_user("ua", "unit_admin", unit="U-A"))
        self.assertEqual(self.codes_in(c.get("/api/v1/organization/units/")), {"U-A"})

    def test_scope_engine_rules(self):
        chief = self.make_user("bari", "regional_chief", unit="BARI")
        self.assertTrue(scope.can(chief, "org.view", unit=self.unit("BARI-NAVY")))
        self.assertFalse(scope.can(chief, "org.view", unit=self.unit("MUDUG")))
        self.assertFalse(scope.can(chief, "org.view"))  # no global grant
        self.assertFalse(scope.can(chief, "org.manage", unit=self.unit("BARI")))  # role lacks permission
        admin = self.make_user("adm", "hq_admin")
        self.assertTrue(scope.can(admin, "users.manage"))

    def test_branch_scoped_hq_assignment_is_not_global(self):
        user = self.make_user("hqarmy", "hq_reporting", unit="HQ", branch="ARMY")
        self.assertFalse(scope.can(user, "org.view"))
        self.assertTrue(scope.can(user, "org.view", unit=self.unit("MUDUG-ARMY")))
        self.assertFalse(scope.can(user, "org.view", unit=self.unit("MUDUG-NAVY")))

    def test_expired_assignment_grants_nothing(self):
        from datetime import date, timedelta
        from apps.accounts.models import RoleAssignment
        user = self.make_user("old", "read_only", unit="BARI")
        RoleAssignment.objects.filter(user=user).update(valid_until=date.today() - timedelta(days=1))
        c = self.client_for(user)
        self.assertEqual(c.get("/api/v1/ranks/").status_code, 403)

    def test_dashboard_blocks_follow_permissions(self):
        reader = self.client_for(self.make_user("reader", "read_only", unit="BARI"))
        data = reader.get("/api/v1/dashboard/").data
        self.assertNotIn("accounts", data)
        self.assertNotIn("audit", data)
        self.assertNotIn("demo", data)  # no fabricated figures
        admin = self.client_for(self.make_user("adm", "hq_admin"))
        data = admin.get("/api/v1/dashboard/").data
        self.assertIn("accounts", data)
        self.assertEqual(data["scope"]["units_in_scope"], 13)
