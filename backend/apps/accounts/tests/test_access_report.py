"""Access report: usernames, roles, scope and capabilities, read-only and without secrets. Synthetic data only."""
import csv
import io
import json
import os
import tempfile
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from apps.accounts import access_report as ar
from apps.accounts.models import RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest


class AccessReportTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.sup = self.make_user("boss", "super_admin")
        self.cmdr = self.make_user("cmdr", "unit_commander", unit="BARI-ARMY-A")
        self.idle = self.make_user("idle", "member", unit="BARI-ARMY")
        RoleAssignment.objects.filter(user=self.idle).update(revoked_at=timezone.now())
        self.off = self.make_user("gone", "unit_commander", unit="BARI-ARMY-A")
        User.objects.filter(pk=self.off.pk).update(is_active=False)

    def users(self, **kw):
        return {u["username"]: u for u in ar.build(**kw)["users"]}

    def test_every_user_with_role_scope_and_permissions(self):
        u = self.users()
        self.assertEqual(set(u), {"boss", "cmdr", "idle", "gone"})
        boss = u["boss"]["assignments"][0]
        self.assertEqual((boss["role"], boss["status"], boss["scope"]["global"]), ("super_admin", "active", True))
        self.assertIn("weapons.manage", boss["permissions"])
        cmdr = u["cmdr"]["assignments"][0]
        self.assertEqual((cmdr["scope"]["unit_code"], cmdr["scope"]["global"]), ("BARI-ARMY-A", False))
        self.assertIn("every unit below it", cmdr["scope"]["text"])
        self.assertIn("weapons.view", cmdr["permissions"])
        self.assertNotIn("weapons.manage", cmdr["permissions"])

    def test_revoked_and_disabled_are_labelled_not_counted_as_in_force(self):
        u = self.users()
        self.assertEqual(u["idle"]["assignments"][0]["status"], "revoked")
        self.assertEqual(u["gone"]["assignments"][0]["status"], "user disabled")
        self.assertEqual(u["idle"]["effective_permission_count"], 0)
        self.assertNotIn("gone", self.users(include_inactive=False))
        self.assertIn("idle", ar.build()["findings"]["Active users with no effective role"])

    def test_findings_flag_expiry_and_missing_mfa(self):
        RoleAssignment.objects.filter(user=self.cmdr).update(valid_until=timezone.localdate() + timedelta(days=10))
        User.objects.filter(pk=self.sup.pk).update(mfa_enabled=False)
        f = ar.build()["findings"]
        self.assertTrue(any(i.startswith("cmdr") for i in f["Assignments ending within 30 days"]))
        self.assertTrue(any(i.startswith("boss") for i in f["Privileged role without MFA enrolled"]))
        self.assertTrue(any(i.startswith("boss") for i in f["Active whole-system access"]))

    def test_no_secret_ever_appears_in_any_format(self):
        User.objects.filter(pk=self.sup.pk).update(mfa_secret_enc="SECRET-TOTP-VALUE", mfa_enabled=True)
        r = ar.build()
        for text in (json.dumps(r), ar.to_csv(r), ar.to_markdown(r)):
            self.assertNotIn("SECRET-TOTP-VALUE", text)
            self.assertNotIn("pbkdf2", text)

    def test_csv_has_one_row_per_assignment_and_markdown_lists_role_capabilities(self):
        r = ar.build()
        rows = list(csv.DictReader(io.StringIO(ar.to_csv(r))))
        self.assertEqual({(x["username"], x["role"]) for x in rows}, {("boss", "super_admin"), ("cmdr", "unit_commander"), ("idle", "member"), ("gone", "unit_commander")})
        md = ar.to_markdown(r)
        self.assertIn("## What each role can do", md)
        self.assertIn("`weapons.view`", md)

    def test_command_writes_a_private_file_and_is_audited(self):
        path = os.path.join(tempfile.mkdtemp(), "access.csv")
        call_command("access_report", "--format", "csv", "--output", path)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.assertIn("boss", open(path, encoding="utf-8").read())
        self.assertTrue(AuditEvent.objects.filter(action="access.report").exists())
