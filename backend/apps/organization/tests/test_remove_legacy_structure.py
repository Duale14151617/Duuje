"""Databases seeded before the Navy branch and the Karkaar region were dropped are cleaned by remove_legacy_structure."""
from io import StringIO

from django.core.management import call_command

from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU, ServiceBranch
from apps.personnel import services as pers
from apps.ranks.models import Rank


class RemoveLegacyStructureTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        hq = OU.objects.get(level="headquarters")
        self.old_branch = ServiceBranch.objects.create(code="NAVY", name_en="Legacy branch")
        self.old_region = OU.objects.create(code="KARKAAR", name_en="Karkaar", level="region", parent=hq)
        self.old_cmd = OU.objects.create(code="BARI-NAVY", name_en="Legacy command", level="branch_command",
                                         parent=OU.objects.get(code="BARI"), branch=self.old_branch)
        self.old_army = OU.objects.create(code="KARKAAR-ARMY", name_en="Karkaar Army", level="branch_command",
                                          parent=self.old_region, branch=ServiceBranch.objects.get(code="ARMY"))

    def run_cmd(self, *args):
        out = StringIO()
        call_command("remove_legacy_structure", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        self.assertIn("Dry run", self.run_cmd())
        self.assertTrue(OU.objects.get(code="KARKAAR").active)
        self.assertTrue(ServiceBranch.objects.get(code="NAVY").active)

    def test_apply_switches_them_off_and_leaves_the_army_alone(self):
        self.run_cmd("--apply")
        for code in ("KARKAAR", "KARKAAR-ARMY", "BARI-NAVY"):
            self.assertFalse(OU.objects.get(code=code).active, code)
        self.assertFalse(ServiceBranch.objects.get(code="NAVY").active)
        self.assertTrue(OU.objects.get(code="BARI-ARMY").active)
        self.assertTrue(OU.objects.get(code="BARI").active)

    def test_purge_deletes_what_nothing_refers_to_and_is_idempotent(self):
        self.run_cmd("--apply", "--purge")
        self.assertFalse(OU.objects.filter(code__in=["KARKAAR", "KARKAAR-ARMY", "BARI-NAVY"]).exists())
        self.assertFalse(ServiceBranch.objects.filter(code="NAVY").exists())
        self.assertIn("nothing to remove", self.run_cmd("--apply", "--purge"))

    def test_a_unit_that_still_holds_people_is_kept_switched_off(self):
        rank = Rank.objects.get(branch__code="ARMY", code="PA-03")
        Rank.objects.filter(pk=rank.pk).update(approval_status="approved", name_so="x")
        pers.create_personnel(None, full_name="Kept Person", phone="", service_number=None, org_unit=self.old_army,
                              rank=Rank.objects.get(pk=rank.pk), status="active", effective_date=None)
        text = self.run_cmd("--apply", "--purge")
        self.assertIn("still sit in switched-off units", text)
        kept = OU.objects.get(code="KARKAAR-ARMY")
        self.assertFalse(kept.active)
        self.assertTrue(OU.objects.filter(code="KARKAAR").exists())  # its parent cannot go while a child remains
