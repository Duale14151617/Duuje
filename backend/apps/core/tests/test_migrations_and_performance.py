from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.db.migrations import operations as ops
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.logistics.models import Asset, InventoryCategory, StockLine
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import ServiceBranch
from apps.personnel import services as pers
from apps.ranks.models import Rank
from apps.training.models import Course, TrainingRecord
from apps.workflows.models import Notification, ReportType, Submission

BANNED = (ops.RemoveField, ops.DeleteModel, ops.RenameField, ops.RenameModel)


class MigrationSafetyTests(TestCase):
    def test_models_and_migrations_agree(self):
        out = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail("Model changes without a migration. Run `makemigrations` and review:\n" + out.getvalue())

    def test_no_conflicting_migration_branches(self):
        self.assertEqual(MigrationLoader(None, ignore_no_migrations=True).detect_conflicts(), {})

    def test_project_migrations_are_non_destructive_and_reversible(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        checked = 0
        for (app, name), migration in loader.disk_migrations.items():
            if not type(migration).__module__.startswith("apps."):
                continue
            for op in migration.operations:
                checked += 1
                self.assertNotIsInstance(op, BANNED, f"{app}.{name}: destructive operation {type(op).__name__}")
                if isinstance(op, ops.RunPython):
                    self.assertIsNotNone(op.reverse_code, f"{app}.{name}: RunPython has no reverse")
                if isinstance(op, ops.RunSQL):
                    self.assertTrue(op.reverse_sql, f"{app}.{name}: RunSQL has no reverse")
        self.assertGreater(checked, 40)


class PaginationAndQueryCountTests(BaseApiTest):
    """Query counts must not grow with the number of rows on a page (no N+1), and page sizes are capped."""

    def queries(self, client, url):
        client.get(url)  # warm caches
        with CaptureQueriesContext(connection) as ctx:
            r = client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return len(ctx)

    def assertConstant(self, client, url, grow):
        small = self.queries(client, url)
        grow()
        large = self.queries(client, url)
        self.assertEqual(small, large, f"{url}: {small} queries for few rows, {large} for many")

    def test_users_list_is_capped_and_paginated(self):
        adm = self.client_for(self.make_user("adm", "hq_admin"))
        User.objects.bulk_create([User(username=f"bulk{i:03d}", full_name="B", password="!") for i in range(110)])
        r = adm.get("/api/v1/users/?page_size=1000")
        self.assertEqual((len(r.data["results"]), r.data["count"]), (100, 111))
        self.assertIsNotNone(r.data["next"])

    def test_personnel_list_has_no_n_plus_one(self):
        Rank.objects.filter(branch=ServiceBranch.objects.get(code="ARMY"), code="PA-03").update(approval_status="approved", name_so="x")
        OU.objects.create(code="BARI-ARMY-A", name_en="A", level="unit", parent=self.unit("BARI-ARMY"))
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        rank, unit = Rank.objects.get(branch__code="ARMY", code="PA-03"), self.unit("BARI-ARMY-A")
        make = lambda start, n: [pers.create_personnel(None, full_name=f"Person {i}", phone="", service_number=None, org_unit=unit,
                                                       rank=rank, status="active", effective_date=None) for i in range(start, start + n)]
        make(0, 2)
        self.assertConstant(chief, "/api/v1/personnel/", lambda: make(2, 15))

    def test_report_and_notification_lists_have_no_n_plus_one(self):
        OU.objects.create(code="BARI-ARMY-A", name_en="A", level="unit", parent=self.unit("BARI-ARMY"))
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        rtype, unit = ReportType.objects.get(code="transfer_request"), self.unit("BARI-ARMY-A")
        chief_user = User.objects.get(username="chief")

        def make(n):
            for i in range(n):
                s = Submission.objects.create(report_type=rtype, org_unit=unit, title=f"T{i}", period_start="2026-01-01",
                                              period_end="2026-01-02", submitter_username="x", body="b")
                Notification.objects.create(recipient=chief_user, kind="submitted", submission=s)
        make(2)
        self.assertConstant(chief, "/api/v1/reports/submissions/", lambda: make(15))
        self.assertConstant(chief, "/api/v1/notifications/", lambda: make(15))

    def test_logistics_and_training_lists_have_no_n_plus_one(self):
        InventoryCategory.objects.all().update(approval_status="approved")
        for code in ("BARI-ARMY-A", "BARI-ARMY-B"):
            OU.objects.create(code=code, name_en=code, level="unit", parent=self.unit("BARI-ARMY"))
        cust = self.client_for(self.make_user("cust", "logistics_custodian", unit="BARI-ARMY"))
        trainer = self.client_for(self.make_user("trainer", "training_admin", unit="BARI"))
        vehicles, stock_cat = InventoryCategory.objects.get(code="vehicles"), InventoryCategory.objects.get(code="general_supplies")
        unit = self.unit("BARI-ARMY-A")

        def assets(start, n):
            for i in range(start, start + n):
                Asset.objects.create(category=vehicles, org_unit=unit, identifier=f"V-{i:03d}")
        assets(0, 2)
        self.assertConstant(cust, "/api/v1/logistics/assets/", lambda: assets(2, 15))
        StockLine.objects.create(category=stock_cat, org_unit=unit, quantity=1)
        other = self.unit("BARI-ARMY-B")
        uniforms = InventoryCategory.objects.get(code="uniforms_clothing")

        def grow_stock():
            StockLine.objects.create(category=uniforms, org_unit=unit, quantity=2)
            StockLine.objects.create(category=stock_cat, org_unit=other, quantity=3)
            StockLine.objects.create(category=uniforms, org_unit=other, quantity=4)
        self.assertConstant(cust, "/api/v1/logistics/stock/", grow_stock)

        Rank.objects.filter(branch=ServiceBranch.objects.get(code="ARMY"), code="PA-03").update(approval_status="approved", name_so="x")
        person = pers.create_personnel(None, full_name="Trainee", phone="", service_number=None, org_unit=unit,
                                       rank=Rank.objects.get(branch__code="ARMY", code="PA-03"), status="active", effective_date=None)
        course = Course.objects.get(code="first_aid")

        def records(start, n):
            for i in range(start, start + n):
                TrainingRecord.objects.create(personnel=person, course=course, start_date=timezone.localdate().replace(day=1) - timedelta(days=i))
        records(0, 2)
        self.assertConstant(trainer, "/api/v1/training/records/", lambda: records(2, 15))

    def test_audit_list_is_paginated(self):
        aud = self.client_for(self.make_user("aud", "auditor"))
        AuditEvent.objects.bulk_create([AuditEvent(action="probe", outcome="success") for _ in range(60)])
        r = aud.get("/api/v1/audit-events/")
        self.assertEqual(len(r.data["results"]), 25)
