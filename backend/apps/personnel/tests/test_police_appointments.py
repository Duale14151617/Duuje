"""Chief of Police (per regional Police command) and Station Commander (per station), and the chain between them. Synthetic data only."""
from datetime import date

from django.core.management import call_command
from django.test import override_settings

from apps.organization.models import OrganizationalUnit as OU
from apps.personnel.models import AppointmentType, Personnel

from .test_personnel import URL, PersonnelBase


@override_settings(POLICE_MODULE_ENABLED=True)
class PoliceAppointmentTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        call_command("apply_police_structure", "--apply", "--stations-per-command", "2", stdout=open("/dev/null", "w"))
        self.admin = self.client_for(self.make_user("polsa", "super_admin"))
        self.bari_cmd = OU.objects.get(code="BARI-POLICE")
        self.st1, self.st2 = OU.objects.get(code="BARI-POLICE-ST1"), OU.objects.get(code="BARI-POLICE-ST2")

    def officer(self, name, rank, unit="BARI-POLICE-PERS"):
        return self.person(unit, name, rank=rank, branch="POLICE")

    def appoint(self, person, type_code, unit):
        t = AppointmentType.objects.get(code=type_code)
        body = {"org_unit": str(unit.pk), "appointment_type": str(t.pk), "effective_from": date.today().isoformat(),
                "authority_ref": "Order 1/2026"}
        return self.admin.post(f"{URL}{person.pk}/appointments/add/", body, format="json")

    def test_both_titles_exist_after_the_structure_is_applied(self):
        got = {t.code: t.exclusive for t in AppointmentType.objects.filter(code__in=["CHIEF_OF_POLICE", "STATION_COMMANDER"])}
        self.assertEqual(got, {"CHIEF_OF_POLICE": True, "STATION_COMMANDER": True})

    def test_every_region_has_stations(self):
        for region in ("BARI", "KARKAAR", "NUGAAL", "MUDUG", "SANAAG"):
            self.assertEqual(OU.objects.filter(parent__code=f"{region}-POLICE", level="station").count(), 2, region)

    def test_chief_goes_on_the_regional_police_command_only(self):
        chief = self.officer("Chief One", "PL-14")
        self.assertEqual(self.appoint(chief, "CHIEF_OF_POLICE", self.bari_cmd).status_code, 201)
        self.assertEqual(self.appoint(chief, "CHIEF_OF_POLICE", self.st1).status_code, 400)
        self.assertEqual(self.appoint(self.officer("Chief Two", "PL-14"), "CHIEF_OF_POLICE", self.bari_cmd).status_code, 400)  # one holder

    def test_station_commander_goes_on_a_police_station_only(self):
        lead = self.officer("Lead One", "PL-10")
        self.assertEqual(self.appoint(lead, "STATION_COMMANDER", self.bari_cmd).status_code, 400)
        self.assertEqual(self.appoint(lead, "STATION_COMMANDER", self.st1).status_code, 201)
        self.assertEqual(self.appoint(self.officer("Lead Two", "PL-10"), "STATION_COMMANDER", self.st1).status_code, 400)
        self.assertEqual(self.appoint(self.officer("Lead Three", "PL-10"), "STATION_COMMANDER", self.st2).status_code, 201)

    def test_an_army_officer_cannot_hold_a_police_appointment(self):
        r = self.appoint(self.person("BARI-ARMY-A", "Army Man", rank="PA-12"), "CHIEF_OF_POLICE", self.bari_cmd)
        self.assertEqual(r.status_code, 400)

    def test_station_commander_reports_to_the_chief_whichever_is_appointed_first(self):
        lead1, lead2 = self.officer("Lead One", "PL-10"), self.officer("Lead Two", "PL-10")
        chief = self.officer("Chief One", "PL-14")
        self.appoint(lead1, "STATION_COMMANDER", self.st1)          # no chief yet: nothing to link
        self.assertIsNone(Personnel.objects.get(pk=lead1.pk).supervisor_id)
        self.appoint(chief, "CHIEF_OF_POLICE", self.bari_cmd)       # chief arrives: existing leads are linked
        self.assertEqual(Personnel.objects.get(pk=lead1.pk).supervisor_id, chief.pk)
        self.appoint(lead2, "STATION_COMMANDER", self.st2)          # lead arrives after the chief
        self.assertEqual(Personnel.objects.get(pk=lead2.pk).supervisor_id, chief.pk)

    def test_the_link_never_breaks_the_rank_rule_or_replaces_a_line_set_by_hand(self):
        chief = self.officer("Chief One", "PL-14")
        self.appoint(chief, "CHIEF_OF_POLICE", self.bari_cmd)
        equal = self.officer("Equal Rank", "PL-14")                  # not below the chief: no link
        self.appoint(equal, "STATION_COMMANDER", self.st1)
        self.assertIsNone(Personnel.objects.get(pk=equal.pk).supervisor_id)
        boss = self.officer("Other Boss", "PL-16")
        lead = self.officer("Lead Two", "PL-10")
        Personnel.objects.filter(pk=lead.pk).update(supervisor=boss)  # set by hand
        self.appoint(lead, "STATION_COMMANDER", self.st2)
        self.assertEqual(Personnel.objects.get(pk=lead.pk).supervisor_id, boss.pk)
