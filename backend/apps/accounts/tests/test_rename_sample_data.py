"""The stored DEMO labels are renamed to SAMPLE without deleting anything. Synthetic data only."""
from django.core.management import call_command

from apps.accounts.models import User
from apps.core.testing import BaseApiTest
from apps.logistics.models import Asset, InventoryCategory
from apps.organization.models import OrganizationalUnit as OU
from apps.personnel.models import Personnel
from apps.ranks.models import Rank


class RenameSampleDataTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        parent = OU.objects.get(code="BARI-ARMY")
        self.unit = OU.objects.create(code="BARI-ARMY-DEMO-A", name_en="Synthetic Unit A", name_so="Cutubka Tijaabada A",
                                      level=OU.Level.UNIT, parent=parent)
        self.person = Personnel.objects.create(full_name="Demo Person 01", service_number="DEMO-0001", org_unit=self.unit,
                                               rank=Rank.objects.get(code="PA-03"), status="active")
        cat = InventoryCategory.objects.filter(code__startswith="weapons_").first() or InventoryCategory.objects.first()
        self.asset = Asset.objects.create(category=cat, identifier="DEMO-RIFL-001", org_unit=self.unit, description="Synthetic demo weapon")
        self.user = self.make_user("sample.commander", "read_only")
        User.objects.filter(pk=self.user.pk).update(full_name="Bari Unit Commander (Demo)")

    def test_dry_run_changes_nothing(self):
        call_command("rename_sample_data")
        self.assertTrue(OU.objects.filter(code="BARI-ARMY-DEMO-A").exists())
        self.assertTrue(Personnel.objects.filter(service_number="DEMO-0001").exists())

    def test_apply_renames_and_is_idempotent(self):
        for _ in range(2):
            call_command("rename_sample_data", "--apply")
        self.assertTrue(OU.objects.filter(code="BARI-ARMY-SAMPLE-A").exists())
        self.assertFalse(OU.objects.filter(code="BARI-ARMY-DEMO-A").exists())
        p = Personnel.objects.get(pk=self.person.pk)
        self.assertEqual((p.service_number, p.full_name), ("SAMPLE-0001", "Sample Person 01"))
        a = Asset.objects.get(pk=self.asset.pk)
        self.assertEqual((a.identifier, a.description), ("SAMPLE-RIFL-001", "Synthetic sample weapon"))
        self.assertEqual(User.objects.get(pk=self.user.pk).full_name, "Bari Unit Commander (Sample)")

    def test_a_clash_is_skipped_not_overwritten(self):
        Personnel.objects.create(full_name="Existing", service_number="SAMPLE-0001", org_unit=self.unit,
                                 rank=Rank.objects.get(code="PA-03"), status="active")
        call_command("rename_sample_data", "--apply")
        self.assertEqual(Personnel.objects.get(pk=self.person.pk).service_number, "DEMO-0001")
