"""v1.4 -> v2.0 compatibility. v2.0 must only ADD: nothing a v1.4 client, role, route or table relied on may change.

The baselines below were extracted mechanically from the v1.4.0 sources (seed_reference_data.py and config/api_v1.py).
"""
import os
from pathlib import Path

from django.conf import settings
from django.db.migrations import operations as ops
from django.db.migrations.loader import MigrationLoader

from apps.accounts.models import Role
from apps.core.testing import BaseApiTest
from config.api_v1 import router

V14_ROLE_PERMISSIONS = {'auditor': ['audit.view', 'dashboard.view', 'org.view'],
 'branch_admin': ['dashboard.view', 'logistics.report', 'logistics.view', 'org.manage', 'org.view',
                  'personnel.import', 'personnel.manage', 'personnel.view', 'ranks.view', 'reports.review',
                  'reports.submit', 'reports.summary', 'reports.view', 'training.report', 'training.view'],
 'hq_admin': ['audit.view', 'dashboard.view', 'logistics.configure', 'org.manage', 'org.view',
              'ranks.approve', 'ranks.manage', 'ranks.view', 'reports.configure', 'roles.assign',
              'training.configure', 'users.manage', 'users.view'],
 'hq_reporting': ['dashboard.view', 'logistics.report', 'org.view', 'personnel.export', 'personnel.view',
                  'ranks.view', 'reports.export', 'reports.summary', 'reports.view', 'training.report'],
 'logistics_custodian': ['dashboard.view', 'logistics.manage', 'logistics.reconcile', 'logistics.report',
                         'logistics.view', 'org.view'],
 'logistics_reviewer': ['dashboard.view', 'logistics.approve', 'logistics.restricted_approve', 'org.view'],
 'read_only': ['dashboard.view', 'org.view', 'personnel.view', 'ranks.view', 'reports.view'],
 'regional_chief': ['dashboard.view', 'logistics.report', 'logistics.view', 'org.view', 'personnel.export',
                    'personnel.manage', 'personnel.view', 'ranks.view', 'reports.export', 'reports.review',
                    'reports.summary', 'reports.view', 'training.report', 'training.view'],
 'reporting_officer': ['dashboard.view', 'org.view', 'personnel.view', 'ranks.view', 'reports.submit',
                       'reports.view'],
 'restricted_custodian': ['dashboard.view', 'logistics.manage', 'logistics.reconcile', 'logistics.report',
                          'logistics.restricted', 'logistics.view', 'org.view'],
 'training_admin': ['dashboard.view', 'org.view', 'training.configure', 'training.manage', 'training.report',
                    'training.view'],
 'unit_admin': ['dashboard.view', 'logistics.view', 'org.manage', 'org.view', 'personnel.manage',
                'personnel.view', 'ranks.view', 'reports.submit', 'reports.view', 'training.view']}

V14_ROUTES = [('users', 'user'), ('roles', 'role'), ('organization/units', 'unit'),
 ('organization/unit-types', 'unit-type'), ('organization/designations', 'designation'),
 ('organization/designation-rules', 'designation-rule'), ('organization/structure', 'structure'),
 ('organization/branches', 'branch'), ('ranks', 'rank'), ('personnel', 'personnel'),
 ('reports/types', 'report-type'), ('reports/submissions', 'submission'),
 ('reports/summary', 'report-summary'), ('notifications', 'notification'),
 ('logistics/categories', 'inv-category'), ('logistics/stock', 'stock'), ('logistics/assets', 'asset'),
 ('logistics/reconciliations', 'reconciliation'), ('logistics/summary', 'logistics-summary'),
 ('training/courses', 'course'), ('training/records', 'training-record'),
 ('training/people', 'training-person'), ('training/summary', 'training-summary'),
 ('audit-events', 'audit-event')]

V14_MIGRATIONS = {
    "accounts": ["0001_initial", "0002_mfa_replay_and_password_reset"],
    "audit": ["0001_initial", "0002_immutability_trigger"],
    "logistics": ["0001_initial", "0002_append_only_triggers"],
    "organization": ["0001_initial", "0002_specialistdesignation_and_more", "0003_puntland_army_structure"],
    "personnel": ["0001_initial", "0002_append_only_triggers"],
    "ranks": ["0001_initial", "0002_alter_rank_category", "0003_official_puntland_army_ranks"],
    "training": ["0001_initial"],
    "workflows": ["0001_initial", "0002_append_only_triggers"],
}
NEW_PERMISSIONS = {"analytics.view", "integrations.view", "integrations.manage", "org.structure_propose", "org.structure_approve"}
ROLES_GAINING_ANALYTICS = {"hq_reporting", "regional_chief", "branch_admin"}
NEW_ROLES = {"structure_approver", "super_admin"}
# hq_admin receives every non-sensitive permission automatically, so it gains the integration and structure-proposal ones.
HQ_ADMIN_GAINS = {"integrations.view", "integrations.manage", "org.structure_propose"}


class RoleCompatibilityTests(BaseApiTest):
    def test_no_role_lost_a_permission(self):
        for role, codes in V14_ROLE_PERMISSIONS.items():
            have = set(Role.objects.get(code=role).permissions.values_list("code", flat=True))
            self.assertFalse(set(codes) - have, f"{role} lost {set(codes) - have}")

    def test_roles_only_gained_the_documented_permission(self):
        for role, codes in V14_ROLE_PERMISSIONS.items():
            have = set(Role.objects.get(code=role).permissions.values_list("code", flat=True))
            gained = have - set(codes)
            allowed = ({"analytics.view"} if role in ROLES_GAINING_ANALYTICS else set()) | (HQ_ADMIN_GAINS if role == "hq_admin" else set())
            self.assertEqual(gained, allowed, role)

    def test_only_the_documented_role_was_added_and_none_removed(self):
        self.assertEqual(set(Role.objects.values_list("code", flat=True)), set(V14_ROLE_PERMISSIONS) | NEW_ROLES)

    def test_every_new_permission_is_registered(self):
        from apps.accounts.models import Permission
        self.assertTrue(NEW_PERMISSIONS <= set(Permission.objects.values_list("code", flat=True)))

    def test_administrators_still_hold_no_data_permissions(self):
        have = set(Role.objects.get(code="hq_admin").permissions.values_list("code", flat=True))
        sensitive = ("personnel.", "reports.view", "reports.submit", "reports.review", "reports.summary", "logistics.view",
                     "logistics.manage", "logistics.restricted", "training.view", "training.manage", "analytics.", "org.structure_approve")
        self.assertFalse([c for c in have if c.startswith(sensitive)])
        self.assertTrue({"integrations.view", "integrations.manage", "org.structure_propose"} <= have)
        self.assertNotIn("org.structure_approve", have)  # approving a structure change is a separate duty


class RouteCompatibilityTests(BaseApiTest):
    def test_every_v14_route_is_still_registered_under_the_same_name(self):
        now = {(prefix, basename) for prefix, _, basename in router.registry}
        missing = {tuple(r) for r in V14_ROUTES} - now
        self.assertFalse(missing, missing)

    def test_v2_adds_only_the_documented_routes(self):
        now = {(prefix, basename) for prefix, _, basename in router.registry}
        added = now - {tuple(r) for r in V14_ROUTES}
        self.assertEqual(added, {("analytics", "analytics"), ("integrations/clients", "integration-client"),
                                 ("organization/structure-changes", "structure-change")})

    def test_version_1_prefix_is_unchanged(self):
        self.assertEqual(self.client_for(self.make_user("hqr", "hq_reporting")).get("/api/v1/auth/me/").status_code, 200)

    def test_me_and_dashboard_keep_their_v14_shape(self):
        c = self.client_for(self.make_user("hqr", "hq_reporting"))
        me = c.get("/api/v1/auth/me/").json()
        for key in ("id", "username", "full_name", "preferred_language", "mfa_enabled", "requires_mfa", "restrictions",
                    "permissions", "features", "assignments"):
            self.assertIn(key, me)
        self.assertTrue({"personnel_export", "report_export"} <= set(me["features"]))
        self.assertIs(me["features"]["integrations"], False)  # off unless explicitly enabled
        dash = c.get("/api/v1/dashboard/").json()
        self.assertEqual(set(dash), {"scope", "ranks", "personnel", "reports"})  # no new blocks

    def test_exports_and_integrations_remain_off_by_default(self):
        self.assertFalse(settings.PERSONNEL_EXPORT_ENABLED)
        self.assertFalse(settings.REPORT_EXPORT_ENABLED)
        self.assertFalse(settings.INTEGRATIONS_ENABLED)


V2_ADDED_MIGRATIONS = {"organization": ["0004_structure_change"]}  # the only migration added to an existing app


class MigrationCompatibilityTests(BaseApiTest):
    def test_existing_apps_gained_only_the_documented_migration(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        for app, names in V14_MIGRATIONS.items():
            have = sorted(n for (a, n) in loader.disk_migrations if a == app)
            self.assertEqual(have, sorted(names + V2_ADDED_MIGRATIONS.get(app, [])), app)

    def test_new_apps_only_create_things(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        allowed = (ops.CreateModel, ops.AddIndex, ops.RunPython)
        for (app, name), migration in loader.disk_migrations.items():
            if app in ("analytics", "integrations") or (app, name) == ("organization", "0004_structure_change"):
                for op in migration.operations:
                    self.assertIsInstance(op, allowed, f"{app}.{name}: {type(op).__name__}")

    def test_new_tables_are_separate_from_v14_tables(self):
        from django.apps import apps
        names = {m._meta.db_table for m in apps.get_app_config("integrations").get_models()}
        self.assertEqual(names, {"integration_clients", "integration_calls"})
