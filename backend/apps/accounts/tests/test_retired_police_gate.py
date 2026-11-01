"""Safety net: Police is retired, but any Police rows left in an old database must stay hidden from every scope (super_admin excepted).

The fixture builds its own minimal Police branch, command, unit and rank, because nothing in the Army-only build seeds them."""
from datetime import date

from django.test import override_settings

from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit, ServiceBranch
from apps.personnel import services as svc
from apps.ranks.models import Rank


@override_settings(POLICE_MODULE_ENABLED=True)
class RetiredPoliceGateTests(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        police = ServiceBranch.objects.create(code="POLICE", name_en="Police (legacy test data)")
        region = OrganizationalUnit.objects.get(code="BARI")
        command = OrganizationalUnit.objects.create(code="BARI-POLICE", name_en="Bari Police command", level="branch_command",
                                                    parent=region, branch=police)
        unit = OrganizationalUnit.objects.create(code="BARI-POLICE-PERS", name_en="Bari Police personnel", level="unit", parent=command)
        rank = Rank.objects.create(branch=police, category="inspector", code="PL-05", name_en="Legacy test rank", sort_order=5,
                                   approval_status="approved")
        svc.create_personnel(None, full_name="Police Pers One", phone="", service_number="PP-T1", org_unit=unit, rank=rank,
                             status="active", effective_date=date.today())

    def numbers(self, client):
        resp = client.get("/api/v1/personnel/")
        self.assertEqual(resp.status_code, 200)
        return {r["service_number"] for r in resp.data["results"]}

    def test_switching_the_module_off_hides_police_records_server_side(self):
        admin = self.client_for(self.make_user("polis3", "branch_admin", unit="BARI", branch="POLICE"))
        self.assertEqual(self.numbers(admin), {"PP-T1"})
        with override_settings(POLICE_MODULE_ENABLED=False):
            self.assertEqual(self.numbers(admin), set())

    def test_super_admin_reaches_everything_even_with_the_police_module_off(self):
        sup = self.client_for(self.make_user("sup3", "super_admin"))
        admin = self.client_for(self.make_user("polis4", "branch_admin", unit="BARI", branch="POLICE"))
        with override_settings(POLICE_MODULE_ENABLED=False):
            self.assertEqual(self.numbers(sup), {"PP-T1"})  # maintenance override: nothing is out of reach
            self.assertEqual(self.numbers(admin), set())    # every other role still obeys the switch
