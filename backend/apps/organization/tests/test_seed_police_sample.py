"""seed_police_sample: synthetic officers, staff, department heads and detainees for every region and its two stations."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.detention.models import DetentionRecord
from apps.organization import police_structure as ps
from apps.organization.models import OrganizationalUnit as OU
from apps.personnel.models import CommandAppointment, Personnel


@override_settings(POLICEHQ_PROFILE="police", DEBUG=True)
class PoliceSampleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference_data", verbosity=0)
        call_command("apply_police_structure", "--apply", stdout=StringIO())
        call_command("seed_police_sample", "--officers", "2", "--detainees", "3", stdout=StringIO())

    def stations(self):
        return OU.objects.filter(code__regex=r"-POL-S[12]$")

    def test_every_station_has_commander_deputy_officers_staff_heads_and_detainees(self):
        self.assertEqual(self.stations().count(), 18)
        for st in self.stations():
            kinds = {a.appointment_type.code for a in CommandAppointment.objects.filter(org_unit=st, ended_at__isnull=True)}
            self.assertTrue({"POLICE_STATION_COMMANDER", "POLICE_STATION_DEPUTY", "DEPT_HEAD"} <= kinds, st.code)
            self.assertEqual(Personnel.objects.filter(org_unit__parent=st, service_number__startswith="SMP-").count(), 4, st.code)  # 2 Kooxo x 2
            self.assertEqual(CommandAppointment.objects.filter(org_unit=st, department__isnull=False).count(), 3, st.code)
            self.assertEqual(DetentionRecord.objects.filter(org_unit=st).count(), 3, st.code)
            self.assertEqual(DetentionRecord.objects.filter(org_unit=st, status="released").count(), 1, st.code)

    def test_detainees_are_held_in_the_jail_center_and_the_ob_has_an_entry_per_arrest(self):
        from apps.occurrence.models import OccurrenceEntry
        for st in self.stations():
            self.assertTrue(DetentionRecord.objects.filter(org_unit=st).exclude(facility__code=f"{st.code}-JAIL").count() == 0, st.code)
            self.assertEqual(OccurrenceEntry.objects.filter(org_unit=st, category="arrest").count(), 3, st.code)
            self.assertEqual(OccurrenceEntry.objects.filter(org_unit=st, category="custody").count(), 1, st.code)
            nums = list(OccurrenceEntry.objects.filter(org_unit=st).order_by("occurred_at").values_list("ob_seq", flat=True))
            self.assertEqual(nums, sorted(nums), st.code)  # numbers follow the clock

    def test_every_region_has_a_commander_and_a_head_for_each_standard_department(self):
        for code, _ in ps.REGIONS:
            cmd = OU.objects.get(code=f"{code}-POL")
            open_ = CommandAppointment.objects.filter(org_unit=cmd, ended_at__isnull=True)
            self.assertTrue(open_.filter(appointment_type__code="POLICE_REGION_COMMANDER").exists(), code)
            self.assertEqual(open_.filter(appointment_type__code="DEPT_HEAD").count(), 7, code)

    def test_running_it_again_adds_nothing(self):
        people, appts, dets = Personnel.objects.count(), CommandAppointment.objects.count(), DetentionRecord.objects.count()
        call_command("seed_police_sample", "--officers", "2", "--detainees", "3", stdout=StringIO())
        self.assertEqual((Personnel.objects.count(), CommandAppointment.objects.count(), DetentionRecord.objects.count()), (people, appts, dets))

    def test_sample_people_are_tagged_and_register_numbers_are_unique(self):
        self.assertFalse(Personnel.objects.filter(service_number__startswith="SMP-").exclude(phone__startswith="+252906").exists())
        nums = list(DetentionRecord.objects.values_list("register_no", flat=True))
        self.assertEqual(len(nums), len(set(nums)))

    @override_settings(DEBUG=False)
    def test_refused_outside_sample_mode(self):
        with self.assertRaises(CommandError):
            call_command("seed_police_sample", stdout=StringIO())

    def test_sample_stations_are_preapproved_with_cells_and_every_detainee_in_custody_has_a_cell(self):
        from apps.detention.models import CustodyCell, CustodyFacility
        for st in self.stations():
            fac = CustodyFacility.objects.get(org_unit=st, kind="jail_center")
            self.assertEqual(fac.status, "operational", st.code)
            self.assertIn("NOT verified on site", fac.status_note)  # honest about what it is
            self.assertEqual(CustodyCell.objects.filter(facility=fac).count(), 3, st.code)
            held = DetentionRecord.objects.filter(org_unit=st, status="in_custody")
            self.assertTrue(held.exists())
            self.assertFalse(held.filter(cell_ref__isnull=True).exists(), st.code)
            for r in held:
                self.assertEqual(r.cell, r.cell_ref.code)
                if r.sex == "female":
                    self.assertEqual(r.cell_ref.reserved_for, "women")
                self.assertLessEqual(DetentionRecord.objects.filter(cell_ref=r.cell_ref, status="in_custody").count(), r.cell_ref.capacity)

    def test_preapproval_is_idempotent_and_respects_closed_facilities(self):
        from apps.detention.models import CustodyCell, CustodyFacility
        st = self.stations().first()
        fac = CustodyFacility.objects.get(org_unit=st, kind="jail_center")
        before = (CustodyCell.objects.count(), DetentionRecord.objects.filter(cell_ref__isnull=False).count())
        call_command("preapprove_custody_demo", stdout=StringIO())
        self.assertEqual((CustodyCell.objects.count(), DetentionRecord.objects.filter(cell_ref__isnull=False).count()), before)
        CustodyFacility.objects.filter(pk=fac.pk).update(status="closed")
        call_command("preapprove_custody_demo", stdout=StringIO())
        self.assertEqual(CustodyFacility.objects.get(pk=fac.pk).status, "closed")  # a deliberate decision is never overridden
