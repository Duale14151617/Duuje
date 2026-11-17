from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.organization import police_structure as ps
from apps.organization.models import OrganizationalUnit as OU, ServiceBranch, UnitType
from apps.personnel.models import AppointmentType


@override_settings(ARMYHQ_PROFILE="police")
class PoliceStructureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference_data", verbosity=0)
        call_command("apply_police_structure", "--apply", stdout=StringIO())

    def test_army_only_unit_types_are_retired_and_koox_is_the_only_team_level(self):
        from apps.organization.models import SpecialistDesignation
        for code in ("GUUTO", "URUR", "HORIN", "KOOX"):
            self.assertFalse(UnitType.objects.get(code=code).active, code)
        self.assertFalse(SpecialistDesignation.objects.get(code="SANCO").active)
        for code in ("TALIYE_GUUTO", "TALIYE_URUR"):
            self.assertFalse(AppointmentType.objects.get(code=code).active, code)
        self.assertTrue(UnitType.objects.get(code="POLICE_KOOX").active)
        out = StringIO()
        call_command("apply_police_structure", "--apply", stdout=out)  # a second run retires nothing more
        self.assertNotIn("retire_", out.getvalue())

    def test_the_police_profile_builds_no_army_regional_commands(self):
        self.assertFalse(OU.objects.filter(code__endswith="-ARMY").exists())

    def test_every_region_has_its_own_command_with_the_three_services(self):
        self.assertEqual(len(ps.REGIONS), 9)
        for code, _ in ps.REGIONS:
            cmd = OU.objects.get(code=f"{code}-POL")
            self.assertEqual((cmd.level, cmd.unit_type.code, cmd.branch.code), ("branch_command", "POLICE_REGION", "ARMY"))
            self.assertEqual(OU.objects.get(code=code).level, "region")
            self.assertEqual(sorted(c.code for c in cmd.children.all() if c.unit_type.code == "POLICE_SECTION"),
                             sorted(f"{code}-POL-{s}" for s, _, _ in ps.SERVICES))

    def test_headquarters_has_cid_traffic_and_tax_directorates(self):
        hq = OU.objects.get(code=ps.POLICE_HQ_CODE)
        self.assertEqual(hq.parent.level, "headquarters")
        self.assertEqual({c.code for c in hq.children.filter(unit_type__code="POLICE_DIRECTORATE")},
                         {f"{ps.POLICE_HQ_CODE}-{s}" for s, _, _ in ps.SERVICES})

    def test_the_branch_is_labelled_police_and_the_appointment_titles_exist(self):
        self.assertEqual(ServiceBranch.objects.get(code="ARMY").name_en, "Police")
        got = {t.code: (t.unit_type.code, t.role, t.exclusive) for t in AppointmentType.objects.filter(code__startswith="POLICE_")}
        self.assertEqual(got, {
            "POLICE_REGION_COMMANDER": ("POLICE_REGION", "commander", True), "POLICE_REGION_DEPUTY": ("POLICE_REGION", "deputy", True),
            "POLICE_DISTRICT_CHIEF": ("POLICE_DISTRICT", "commander", True), "POLICE_DISTRICT_DEPUTY": ("POLICE_DISTRICT", "deputy", True),
            "POLICE_STATION_COMMANDER": ("POLICE_STATION", "commander", True), "POLICE_STATION_DEPUTY": ("POLICE_STATION", "deputy", True)})

    def test_running_it_again_changes_nothing(self):
        before = OU.objects.count()
        out = StringIO()
        call_command("apply_police_structure", "--apply", stdout=out)
        self.assertEqual(OU.objects.count(), before)
        self.assertIn("Nothing to do", out.getvalue())

    def test_a_dry_run_reports_without_writing(self):
        OU.objects.filter(code="CAYN-POL-TAX").delete()
        out = StringIO()
        call_command("apply_police_structure", stdout=out)
        self.assertIn("WOULD create_unit: CAYN-POL-TAX", out.getvalue())
        self.assertFalse(OU.objects.filter(code="CAYN-POL-TAX").exists())

    def test_districts_stations_and_kooxo_nest_and_every_station_starts_with_two_kooxo(self):
        cmd = OU.objects.get(code="BARI-POL")
        types = {t.code: t for t in UnitType.objects.filter(code__startswith="POLICE_")}
        district = OU.objects.create(code="BARI-POL-D1", name_en="Bosaso District", level="unit", parent=cmd, unit_type=types["POLICE_DISTRICT"])
        station = OU.objects.create(code="BARI-POL-D1-S1", name_en="Bosaso Central Station", level="unit", parent=district,
                                    unit_type=types["POLICE_STATION"])
        self.assertEqual(sorted(c.code for c in station.children.all()), ["BARI-POL-D1-S1-K1", "BARI-POL-D1-S1-K2"])
        self.assertTrue(all(c.unit_type.code == "POLICE_KOOX" and c.branch_id == cmd.branch_id for c in station.children.all()))
        # a large city can have several stations: each gets its own pair
        second = OU.objects.create(code="BARI-POL-D1-S2", name_en="Bosaso Port Station", level="unit", parent=district,
                                   unit_type=types["POLICE_STATION"])
        self.assertEqual(second.children.count(), 2)
        self.assertEqual(OU.objects.filter(code__startswith="BARI-POL-D1-S").filter(unit_type__code="POLICE_KOOX").count(), 4)

    def test_the_tier_order_only_allows_the_police_hierarchy(self):
        t = {x.code: x.tier for x in UnitType.objects.filter(code__startswith="POLICE_")}
        self.assertTrue(t["POLICE_HQ"] < t["POLICE_REGION"] < t["POLICE_DISTRICT"] < t["POLICE_STATION"] < t["POLICE_KOOX"])


@override_settings(ARMYHQ_PROFILE="police")
class GenericStationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference_data", verbosity=0)
        call_command("apply_police_structure", "--apply", stdout=StringIO())

    def test_every_regional_command_has_station_one_and_station_two_with_two_kooxo_each(self):
        for rcode, _ in ps.REGIONS:
            cmd = OU.objects.get(code=f"{rcode}-POL")
            stations = {s.code: s for s in cmd.children.filter(unit_type__code="POLICE_STATION")}
            self.assertEqual(sorted(stations), [f"{rcode}-POL-S1", f"{rcode}-POL-S2"])
            self.assertEqual((stations[f"{rcode}-POL-S1"].name_en, stations[f"{rcode}-POL-S1"].name_so), ("Station one", "Jeelka kowaad"))
            self.assertEqual((stations[f"{rcode}-POL-S2"].name_en, stations[f"{rcode}-POL-S2"].name_so), ("Station two", "Jeelka labaad"))
            for st in stations.values():
                self.assertEqual(st.children.filter(unit_type__code="POLICE_KOOX").count(), 2)
                self.assertEqual(st.branch_id, cmd.branch_id)

    def test_the_stations_are_not_duplicated_on_a_second_run(self):
        before = OU.objects.count()
        call_command("apply_police_structure", "--apply", stdout=StringIO())
        self.assertEqual(OU.objects.count(), before)

    def test_every_station_has_a_jail_center_and_each_region_a_generic_prison(self):
        from apps.detention.models import CustodyFacility
        self.assertEqual(CustodyFacility.objects.filter(kind="jail_center").count(), 18)
        for st in OU.objects.filter(code__regex=r"-POL-S[12]$"):
            jail = CustodyFacility.objects.get(code=f"{st.code}-JAIL")
            self.assertEqual((jail.kind, jail.org_unit_id, jail.operated_by), ("jail_center", st.pk, "Police"))
        call_command("apply_custody_facilities", stdout=StringIO())
        self.assertEqual(CustodyFacility.objects.filter(kind="prison").count(), 9)
        again = StringIO()
        call_command("apply_custody_facilities", stdout=again)  # a second run adds nothing
        self.assertIn("0 jail centers and 0 prisons added", again.getvalue())
        self.assertEqual(CustodyFacility.objects.count(), 27)
