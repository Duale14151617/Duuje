"""Army organizational structure (requirements section 3). Army only: Police and Navy units are never touched."""
from io import StringIO

from django.core.management import call_command

from apps.accounts import scope
from apps.organization import army_structure as AS
from apps.organization.models import OrganizationalUnit as OU, PlacementError, ServiceBranch, check_placement

from .test_structure import TemplateBase


class ArmyStructureTests(TemplateBase):
    def run_cmd(self, apply=False, *extra):
        out = StringIO()
        call_command("apply_army_structure", *(["--apply"] if apply else []), *extra, stdout=out)
        return out.getvalue()

    def snapshot(self, branch_codes):
        return list(OU.objects.filter(branch__code__in=branch_codes).order_by("code")
                    .values_list("code", "name_en", "name_so", "unit_type_id", "active", "version"))

    def test_dry_run_reports_and_writes_nothing(self):
        before = OU.objects.count()
        text = self.run_cmd()
        self.assertIn("create_unit: ARMY-HQ", text)
        self.assertIn("create_unit: SANAAG-ARMY", text)
        self.assertEqual(OU.objects.count(), before)

    def test_apply_builds_headquarters_directorates_and_regional_commands(self):
        self.run_cmd(apply=True)
        hq = OU.objects.get(code="ARMY-HQ")
        self.assertEqual((hq.level, hq.branch.code, hq.parent.level, hq.unit_type.code, hq.name_so),
                         ("branch_command", "ARMY", "headquarters", "TALISKA_GUUD", "Taliska Guud"))
        dirs = OU.objects.filter(parent=hq).order_by("code")
        self.assertEqual({d.name_so for d in dirs}, {so for _, so, _ in AS.DIRECTORATES})
        self.assertEqual(len(dirs), 7)
        self.assertTrue(all(d.level == "unit" and d.unit_type.code == "HQ_DIRECTORATE" and d.branch.code == "ARMY" for d in dirs))
        cmds = {u.code: u for u in OU.objects.filter(code__in=[f"{r}-ARMY" for r, _, _ in AS.COMMANDS])}
        self.assertEqual({c.name_so for c in cmds.values()},
                         {"Qaybta Mudug & Cayn", "Qaybta Nugaal & Sool", "Qaybta Bari", "Qaybta Sanaag"})
        self.assertTrue(all(c.unit_type.code == "QAYB" and c.level == "branch_command" for c in cmds.values()))
        self.assertEqual(cmds["SANAAG-ARMY"].parent.code, "SANAAG")

    def test_urur_office_types_exist_below_urur(self):
        self.run_cmd(apply=True)
        from apps.organization.models import UnitType
        offices = UnitType.objects.filter(code__startswith="URUR_")
        self.assertEqual({o.name_so for o in offices},
                         {"Howlgelin", "Xafiiska Ururka", "Maamulka Lacagta", "Saadka", "Xubinta Caafimaadka"})
        self.assertTrue(all(o.parent_type.code == "URUR" for o in offices))

    def test_idempotent(self):
        self.run_cmd(apply=True)
        count = OU.objects.count()
        again = self.run_cmd(apply=True)
        self.assertIn("already matches", again)
        self.assertEqual(OU.objects.count(), count)

    def test_police_and_navy_are_untouched(self):
        before = self.snapshot(["POLICE", "NAVY"])
        regions_before = OU.objects.filter(level="region").exclude(code="SANAAG").count()
        self.run_cmd(apply=True)
        self.assertEqual(self.snapshot(["POLICE", "NAVY"]), before)
        self.assertEqual(OU.objects.filter(level="region").exclude(code="SANAAG").count(), regions_before)

    def test_karkaar_is_retired_only_when_empty(self):
        self.person("KARKAAR-ARMY", "Karkaar Soldier")
        text = self.run_cmd(apply=True)
        self.assertIn("KARKAAR-ARMY still holds 1", text)
        self.assertTrue(OU.objects.get(code="KARKAAR-ARMY").active)
        from apps.personnel.models import Personnel
        Personnel.objects.filter(org_unit__code="KARKAAR-ARMY").update(status="retired")
        self.run_cmd(apply=True)
        self.assertFalse(OU.objects.get(code="KARKAAR-ARMY").active)

    def test_only_the_army_may_have_a_command_directly_under_headquarters(self):
        hq = OU.objects.get(level="headquarters")
        army, police = ServiceBranch.objects.get(code="ARMY"), ServiceBranch.objects.get(code="POLICE")
        self.assertEqual(check_placement("branch_command", hq, army), army)
        for branch in (police, ServiceBranch.objects.get(code="NAVY")):
            with self.assertRaises(PlacementError) as cm:
                check_placement("branch_command", hq, branch)
            self.assertEqual(cm.exception.code, "branch_parent_must_be_region")

    def test_regional_roles_do_not_see_headquarters_directorates(self):
        self.run_cmd(apply=True)
        regional = self.make_user("bari.admin", "branch_admin", unit="BARI", branch="ARMY")
        visible = set(scope.scoped_units(regional, "org.view").values_list("code", flat=True))
        self.assertIn("BARI-ARMY", visible)
        self.assertNotIn("ARMY-HQ", visible)
        self.assertFalse(any(c.startswith("ARMY-HQ-") for c in visible))
        boss = self.make_user("hq.boss", "super_admin")
        self.assertIn("ARMY-HQ", set(scope.scoped_units(boss, "org.view").values_list("code", flat=True)))


    def test_every_regional_command_gets_one_guuto_and_one_urur_by_default(self):
        self.run_cmd(apply=True)
        for region in ("BARI", "SANAAG", "MUDUG", "NUGAAL"):
            guuto = OU.objects.get(code=f"{region}-ARMY-G1")
            urur = OU.objects.get(code=f"{region}-ARMY-G1-U1")
            self.assertEqual((guuto.unit_type.code, guuto.parent.code, guuto.branch.code, guuto.level), ("GUUTO", f"{region}-ARMY", "ARMY", "unit"))
            self.assertEqual((urur.unit_type.code, urur.parent.code, urur.branch.code), ("URUR", f"{region}-ARMY-G1", "ARMY"))
        self.assertFalse(OU.objects.filter(code__startswith="KARKAAR-ARMY-G").exists())  # Karkaar is within Bari

    def test_raising_the_numbers_later_only_adds_and_is_idempotent(self):
        self.run_cmd(apply=True)
        first = set(OU.objects.filter(code__contains="-ARMY-G").values_list("code", flat=True))
        self.assertEqual(len(first), 28)  # four regions; per region: 1 Guuto, 1 Urur, 5 battalion sections
        self.run_cmd(True, "--guuto-per-command", "2", "--urur-per-guuto", "2")
        both = set(OU.objects.filter(code__contains="-ARMY-G").values_list("code", flat=True))
        self.assertEqual(len(both), 104)  # four regions; per region: 2 Guuto, 4 Urur, 20 battalion sections
        self.assertTrue(first <= both)
        self.assertIn("already matches", self.run_cmd(True, "--guuto-per-command", "2", "--urur-per-guuto", "2"))
        self.run_cmd(True)  # running with the smaller default again removes nothing
        self.assertEqual(OU.objects.filter(code__contains="-ARMY-G").count(), 104)

    def test_out_of_range_numbers_are_refused(self):
        from django.core.management.base import CommandError
        for bad in ("0", "21"):
            with self.assertRaises(CommandError):
                self.run_cmd(True, "--guuto-per-command", bad)

    def test_every_urur_has_its_five_sections_as_real_units(self):
        self.run_cmd(apply=True)
        for region in ("BARI", "SANAAG", "MUDUG", "NUGAAL"):
            urur = OU.objects.get(code=f"{region}-ARMY-G1-U1")
            sections = {u.unit_type.code: u for u in OU.objects.filter(parent=urur)}
            self.assertEqual(set(sections), {"URUR_HOWLGELIN", "URUR_XAFIIS", "URUR_LACAG", "URUR_SAAD", "URUR_CAAFIMAAD"})
            self.assertTrue(all(u.level == "unit" and u.branch.code == "ARMY" and u.active for u in sections.values()))
            self.assertTrue(sections["URUR_LACAG"].name_en.startswith("Finance Section"))

    def test_battalion_commander_and_executive_officer_can_be_appointed_and_staff_assigned_to_a_section(self):
        from datetime import date

        from apps.personnel import appointments
        from apps.personnel.models import AppointmentType
        self.run_cmd(apply=True)
        boss = self.make_user("hq.boss", "super_admin")
        urur = OU.objects.get(code="BARI-ARMY-G1-U1")
        cmdr, xo = self.person("BARI-ARMY-G1-U1", "Battalion Commander"), self.person("BARI-ARMY-G1-U1", "Battalion XO")
        a = appointments.create(boss, cmdr, urur, AppointmentType.objects.get(code="TALIYE_URUR"), date.today())
        b = appointments.create(boss, xo, urur, AppointmentType.objects.get(code="ABAANDUULE"), date.today())
        self.assertEqual((a.org_unit_id, b.org_unit_id), (urur.pk, urur.pk))
        clerk = self.person("BARI-ARMY-G1-U1-FIN", "Finance Clerk")
        self.assertEqual(clerk.org_unit.code, "BARI-ARMY-G1-U1-FIN")

    def test_every_regional_command_gets_the_same_detail(self):
        """Guuto, Urur and the five battalion sections exist in all four regions, not just one."""
        self.run_cmd(apply=True)
        for region in ("BARI", "SANAAG", "MUDUG", "NUGAAL"):
            cmd = OU.objects.get(code=f"{region}-ARMY")
            guuto = OU.objects.get(code=f"{region}-ARMY-G1", parent=cmd)
            urur = OU.objects.get(code=f"{region}-ARMY-G1-U1", parent=guuto)
            self.assertEqual(OU.objects.filter(parent=urur).count(), len(AS.URUR_OFFICES), region)
