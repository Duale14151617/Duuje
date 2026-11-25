from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.detention.models import CustodyFacility
from apps.organization import police_structure as ps, profiles
from apps.organization.models import OrganizationalUnit as OU, UnitDepartment


@override_settings(POLICEHQ_PROFILE="police")
class StationHierarchyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference_data", verbosity=0)
        call_command("apply_police_structure", "--apply", stdout=StringIO())

    def test_stations_and_districts_are_formations_of_the_chart(self):
        from apps.organization.models import UnitType
        self.assertEqual(UnitType.objects.get(code="POLICE_STATION").formation_role, "station")
        self.assertEqual(UnitType.objects.get(code="POLICE_DISTRICT").formation_role, "district")

    def test_every_station_has_the_policing_departments_and_a_jail(self):
        stations = OU.objects.filter(unit_type__code="POLICE_STATION")
        self.assertEqual(stations.count(), len(ps.REGIONS) * len(ps.STATIONS))
        for st in stations:
            got = set(UnitDepartment.objects.filter(unit=st, active=True).values_list("department__code", flat=True))
            self.assertEqual(got, set(profiles.STATION_DEPARTMENTS), st.code)
            self.assertTrue(CustodyFacility.objects.filter(org_unit=st, kind="jail_center").exists(), st.code)
