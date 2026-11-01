from apps.accounts.models import RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest


class UserAdminTests(BaseApiTest):
    def test_non_admins_cannot_touch_accounts(self):
        c = self.client_for(self.make_user("reader", "read_only"))
        self.assertEqual(c.get("/api/v1/users/").status_code, 403)
        r = c.post("/api/v1/users/", {"username": "x1x", "full_name": "X", "initial_password": "Abcdefghijk-123"},
                   format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.filter(username="x1x").exists())

    def test_regional_chief_cannot_list_users(self):
        c = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        self.assertEqual(c.get("/api/v1/users/").status_code, 403)

    def test_admin_creates_user_with_forced_password_change(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        r = c.post("/api/v1/users/", {"username": "Fatima.Demo", "full_name": "Fatima Demo",
                                      "initial_password": "Abcdefghijk-123"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["username"], "fatima.demo")
        self.assertTrue(r.data["must_change_password"])
        self.assertNotIn("password", r.data)
        self.assertTrue(AuditEvent.objects.filter(action="user.create", outcome="success").exists())

    def test_weak_password_and_duplicate_username_rejected(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        r = c.post("/api/v1/users/", {"username": "weak.one", "full_name": "W", "initial_password": "password"},
                   format="json")
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/v1/users/", {"username": "adm", "full_name": "W", "initial_password": "Abcdefghijk-123"},
                   format="json")
        self.assertIn("username_taken", self.codes(r, "username"))

    def test_assignment_rules(self):
        adm = self.make_user("adm", "hq_admin")
        target = User.objects.create_user("target", password="Abcdefghijk-123", full_name="T")
        c = self.client_for(adm)
        url = f"/api/v1/users/{target.pk}/assignments/"
        bari = str(self.unit("BARI").pk)
        ok = c.post(url, {"role": "regional_chief", "org_unit": bari}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        bad_level = c.post(url, {"role": "hq_admin", "org_unit": bari}, format="json")
        self.assertIn("scope_level_not_allowed", self.codes(bad_level, "org_unit"))
        no_branch = c.post(url, {"role": "branch_admin", "org_unit": bari}, format="json")
        self.assertIn("branch_required", self.codes(no_branch, "branch"))
        bad_range = c.post(url, {"role": "read_only", "org_unit": bari, "valid_from": "2030-01-02",
                                 "valid_until": "2030-01-01"}, format="json")
        self.assertIn("invalid_range", self.codes(bad_range, "valid_until"))
        self.assertTrue(AuditEvent.objects.filter(action="role_assignment.create").exists())

    def test_cannot_disable_self_or_last_admin(self):
        adm = self.make_user("adm", "hq_admin")
        c = self.client_for(adm)
        r = c.post(f"/api/v1/users/{adm.pk}/disable/")
        self.assertEqual((r.status_code, r.data["code"]), (409, "cannot_disable_self"))
        a = RoleAssignment.objects.get(user=adm)
        r = c.post(f"/api/v1/users/{adm.pk}/assignments/{a.pk}/revoke/")
        self.assertEqual((r.status_code, r.data["code"]), (409, "last_admin"))

    def test_second_admin_allows_disable_of_first(self):
        a1 = self.make_user("adm1", "hq_admin")
        a2 = self.make_user("adm2", "hq_admin")
        c = self.client_for(a2)
        self.assertEqual(c.post(f"/api/v1/users/{a1.pk}/disable/").status_code, 200)
        self.assertFalse(User.objects.get(pk=a1.pk).is_active)

    def test_user_update_uses_optimistic_concurrency(self):
        adm = self.make_user("adm", "hq_admin")
        target = self.make_user("t1", "read_only")
        c = self.client_for(adm)
        url = f"/api/v1/users/{target.pk}/"
        self.assertEqual(c.patch(url, {"full_name": "New"}, format="json").status_code, 400)  # version missing
        ok = c.patch(url, {"full_name": "New", "version": target.version}, format="json")
        self.assertEqual(ok.status_code, 200)
        stale = c.patch(url, {"full_name": "Newer", "version": target.version}, format="json")
        self.assertEqual((stale.status_code, stale.data["code"]), (409, "version_conflict"))

    def test_user_list_is_paginated_and_secrets_never_exposed(self):
        adm = self.make_user("adm", "hq_admin")
        for i in range(30):
            User.objects.create_user(f"bulk{i:02d}", password="Abcdefghijk-123", full_name="B")
        r = self.client_for(adm).get("/api/v1/users/")
        self.assertEqual(len(r.data["results"]), 25)
        self.assertIsNotNone(r.data["next"])
        for key in ("password", "mfa_secret_enc", "auth_epoch"):
            self.assertNotIn(key, r.data["results"][0])
