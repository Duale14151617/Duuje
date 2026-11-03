"""Real parallel requests against PostgreSQL row locks. Skipped on SQLite (it ignores SELECT ... FOR UPDATE)."""
import unittest
from concurrent.futures import ThreadPoolExecutor

from django.core.management import call_command
from django.db import connection, connections
from rest_framework.test import APIClient, APITransactionTestCase

from apps.accounts.models import Role, RoleAssignment, User
from apps.core.testing import PASSWORD
from apps.logistics.models import InventoryCategory, StockLine, StockTransaction
from apps.organization.models import OrganizationalUnit as OU


@unittest.skipUnless(connection.vendor == "postgresql", "needs PostgreSQL row locks")
class StockConcurrencyTests(APITransactionTestCase):
    # Everything except the (trigger-protected) audit table is flushed after the test.
    available_apps = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "apps.core", "apps.organization",
                      "apps.accounts", "apps.ranks", "apps.personnel", "apps.workflows", "apps.logistics", "apps.training"]

    def client_for(self, user):
        import time
        c = APIClient()
        c.force_login(user)
        s = c.session
        s["auth_epoch"], s["login_at"] = user.auth_epoch, int(time.time())
        s.save()
        return c

    def test_parallel_issues_never_overdraw_the_balance(self):
        call_command("seed_reference_data", verbosity=0)
        InventoryCategory.objects.all().update(approval_status="approved")
        unit = OU.objects.create(code="BARI-ARMY-A", name_en="A", level="unit", parent=OU.objects.get(code="BARI-ARMY"))
        clients = []
        for i in range(2):
            u = User.objects.create_user(f"cust{i}", password=PASSWORD, full_name="C")
            RoleAssignment.objects.create(user=u, role=Role.objects.get(code="logistics_custodian"), org_unit=OU.objects.get(code="BARI-ARMY"))
            clients.append(self.client_for(User.objects.get(pk=u.pk)))
        line = StockLine.objects.create(category=InventoryCategory.objects.get(code="general_supplies"), org_unit=unit, quantity=10)
        url = f"/api/v1/logistics/stock/{line.pk}/transactions/"

        def worker(client):
            try:
                return [client.post(url, {"kind": "issue", "quantity": 1}, format="json").status_code for _ in range(8)]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [code for chunk in pool.map(worker, clients) for code in chunk]
        self.assertEqual(results.count(200), 10, results)
        self.assertEqual(results.count(400), 6, results)
        self.assertEqual(StockLine.objects.get(pk=line.pk).quantity, 0)
        ledger = list(StockTransaction.objects.filter(stock_line=line).values_list("delta", "balance_after"))
        self.assertEqual(sum(d for d, _ in ledger), -10)
        self.assertEqual(sorted(b for _, b in ledger), list(range(10)))  # every balance 0..9 recorded exactly once
