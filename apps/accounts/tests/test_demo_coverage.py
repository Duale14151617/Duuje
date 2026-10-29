"""Every role has at least one synthetic demo account, so each can be tried out. Synthetic data only."""
from apps.accounts.management.commands.seed_demo_data import DEMO_USERS
from apps.accounts.models import Role
from apps.core.testing import BaseApiTest


class DemoCoverageTests(BaseApiTest):
    def test_every_role_has_a_demo_account(self):
        with_user = {spec[1] for spec in DEMO_USERS.values()}
        missing = set(Role.objects.values_list("code", flat=True)) - with_user
        self.assertEqual(missing, set())
