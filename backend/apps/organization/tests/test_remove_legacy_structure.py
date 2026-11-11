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

    def person_in_old_army(self, name):
        rank = Rank.objects.get(branch__code="ARMY", code="PA-03")
        Rank.objects.filter(pk=rank.pk).update(approval_status="approved", name_so="x")
        return pers.create_personnel(None, full_name=name, phone="", service_number=None, org_unit=self.old_army,
                                     rank=Rank.objects.get(pk=rank.pk), status="active", effective_date=None)

    def test_people_of_the_removed_region_move_to_bari_with_history_and_audit(self):
        from apps.audit.models import AuditEvent
        from apps.personnel.models import Personnel, PersonnelHistory
        person = self.person_in_old_army("Moved Person")
        self.assertIn("would move", self.run_cmd())          # dry run reports it
        self.assertEqual(Personnel.objects.get(pk=person.pk).org_unit.code, "KARKAAR-ARMY")
        self.run_cmd("--apply", "--purge")
        moved = Personnel.objects.get(pk=person.pk)
        self.assertEqual(moved.org_unit.code, "BARI-ARMY")
        self.assertEqual(moved.version, person.version + 1)
        self.assertTrue(PersonnelHistory.objects.filter(personnel=person, field="org_unit", new_label=moved.org_unit.name_en,
                                                         reason="Region merged into Bari").exists())
        self.assertTrue(AuditEvent.objects.filter(action="personnel.region_merge_transfer", entity_id=str(person.pk)).exists())
        self.assertFalse(OU.objects.filter(code__in=["KARKAAR", "KARKAAR-ARMY"]).exists())  # nobody left, so they are deleted

    def test_a_deceased_file_is_not_moved_and_keeps_its_unit_switched_off(self):
        from apps.personnel.models import Personnel
        person = self.person_in_old_army("Deceased Person")
        Personnel.objects.filter(pk=person.pk).update(status="died")
        text = self.run_cmd("--apply", "--purge")
        self.assertIn("still sit in switched-off units", text)
        self.assertEqual(Personnel.objects.get(pk=person.pk).org_unit.code, "KARKAAR-ARMY")
        self.assertFalse(OU.objects.get(code="KARKAAR-ARMY").active)
        self.assertTrue(OU.objects.filter(code="KARKAAR").exists())  # its parent cannot go while a child remains
