"""Guard: a fresh database holds only the Army. The seed must never bring back the Navy, Police or Karkaar, or their leftovers."""
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import Permission, Role
from apps.organization.models import OrganizationalUnit as OU, ServiceBranch
from apps.ranks.models import Rank

FORBIDDEN = ("NAVY", "POLICE", "KARKAAR")


class ArmyOnlySeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference_data", verbosity=0)

    def test_the_only_branch_is_the_army(self):
        self.assertEqual(list(ServiceBranch.objects.values_list("code", flat=True)), ["ARMY"])

    def test_the_seeded_regions_are_bari_nugaal_and_mudug(self):
        self.assertEqual(set(OU.objects.filter(level="region").values_list("code", flat=True)), {"BARI", "NUGAAL", "MUDUG"})

    def test_every_branch_command_is_an_army_command(self):
        codes = set(OU.objects.filter(level="branch_command").values_list("branch__code", flat=True))
        self.assertEqual(codes, {"ARMY"})

    def test_applying_the_army_structure_adds_sanaag_and_nothing_foreign(self):
        call_command("apply_army_structure", "--apply", verbosity=0)
        self.assertEqual(set(OU.objects.filter(level="region").values_list("code", flat=True)), {"BARI", "NUGAAL", "MUDUG", "SANAAG"})
        self.assertEqual(list(ServiceBranch.objects.values_list("code", flat=True)), ["ARMY"])

    def test_no_unit_rank_role_or_permission_carries_a_removed_name(self):
        call_command("apply_army_structure", "--apply", verbosity=0)
        names = [*OU.objects.values_list("code", flat=True), *Rank.objects.values_list("branch__code", flat=True),
                 *Role.objects.values_list("code", flat=True), *Permission.objects.values_list("code", flat=True)]
        for value in names:
            for bad in FORBIDDEN:
                self.assertNotIn(bad, value.upper(), value)
        self.assertFalse(Permission.objects.filter(code__startswith="cid.").exists())

    def test_there_is_no_station_level_and_only_the_army_rank_categories(self):
        self.assertEqual(set(OU.Level.values), {"headquarters", "region", "branch_command", "unit"})
        self.assertEqual(set(Rank.Category.values), {"enlisted", "warrant", "officer", "unspecified"})
