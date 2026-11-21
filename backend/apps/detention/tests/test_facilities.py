import unittest

from django.conf import settings

if not settings.CUSTODY_ENABLED:  # custody is switched off for now; set CUSTODY_ENABLED=1 to run these tests
    raise unittest.SkipTest("custody is switched off (CUSTODY_ENABLED=0)")

"""Custody facilities: jail centers (army lock-ups) and prisons (outside the Army). Synthetic data only."""
from apps.detention.models import CustodyFacility
from apps.detention.tests.test_detention import URL, DetentionBase

FAC = "/api/v1/custody-facilities/"


class FacilityTests(DetentionBase):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("fac_adm", "hq_admin"))
        self.jail = CustodyFacility.objects.create(code="A-JAIL", kind="jail_center", org_unit=self.unit_a, name_en="Jail A", status="operational")
        self.jail_b = CustodyFacility.objects.create(code="B-JAIL", kind="jail_center", org_unit=self.unit_b, name_en="Jail B", status="operational")
        self.prison = CustodyFacility.objects.create(code="PRISON-X", kind="prison", name_en="X Prison", status="operational")

    def test_a_jail_center_needs_a_station_and_a_prison_must_have_none(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustodyFacility.objects.create(code="BAD1", kind="jail_center", name_en="No station")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustodyFacility.objects.create(code="BAD2", kind="prison", org_unit=self.unit_a, name_en="Prison with station")

    def test_list_is_scoped_but_prisons_are_visible_to_everyone_who_can_read(self):
        codes = {f["code"] for f in self.officer.get(FAC).data["results"]}
        self.assertEqual(codes, {"A-JAIL", "PRISON-X"})  # Bari officer: own jail center and the prisons, not Nugaal's jail
        self.assertEqual({f["code"] for f in self.officer.get(FAC + "?kind=prison").data["results"]}, {"PRISON-X"})
        self.assertEqual(self.member.get(FAC).status_code, 403)

    def test_booking_defaults_to_the_stations_only_jail_center(self):
        r = self.make()
        self.assertEqual(r["facility"]["code"], "A-JAIL")

    def test_booking_into_another_stations_jail_center_is_refused(self):
        self.assertEqual(self.book(facility=str(self.jail_b.pk)).status_code, 400)
        self.assertEqual(self.book(facility=str(self.prison.pk)).status_code, 400)

    def test_handing_over_to_a_prison_records_the_prison_and_fills_the_destination(self):
        r = self.make()
        out = self.act(r, "close", {"outcome": "transfer_prison", "destination_facility": str(self.prison.pk)})
        self.assertEqual((out.status_code, out.data["status"], out.data["destination"]), (200, "transferred", "X Prison"))
        self.assertEqual(out.data["destination_facility"]["code"], "PRISON-X")

    def test_only_a_prison_can_receive_and_only_on_a_prison_handover(self):
        r = self.make()
        self.assertEqual(self.act(r, "close", {"outcome": "transfer_prison", "destination_facility": str(self.jail.pk)}).status_code, 400)
        self.assertEqual(self.act(r, "close", {"outcome": "transfer_court", "destination": "Court", "destination_facility": str(self.prison.pk)}).status_code, 400)

    def test_create_and_edit_rules(self):
        body = {"kind": "jail_center", "org_unit": str(self.unit_a.pk), "code": "a-jail-2", "name_en": "Second cells", "capacity": 12}
        made = self.officer.post(FAC, body, format="json")
        self.assertEqual((made.status_code, made.data["code"], made.data["operated_by"]), (201, "A-JAIL-2", "Army"))
        self.assertEqual(self.officer.post(FAC, body, format="json").status_code, 400)  # code already used
        self.assertEqual(self.officer.post(FAC, {**body, "org_unit": str(self.unit_b.pk), "code": "N1"}, format="json").status_code, 404)  # not their station
        self.assertEqual(self.officer.post(FAC, {"kind": "prison", "code": "P2", "name_en": "P2"}, format="json").status_code, 404)  # prisons need a headquarters grant
        self.assertEqual(self.admin.post(FAC, {"kind": "prison", "code": "P2", "name_en": "P2"}, format="json").status_code, 201)

    def test_a_jail_center_with_people_in_it_cannot_be_switched_off(self):
        self.make()
        f = next(x for x in self.officer.get(FAC).data["results"] if x["code"] == "A-JAIL")
        self.assertEqual(self.officer.post(f"{FAC}{f['id']}/edit/", {"version": f["version"], "active": False}, format="json").status_code, 400)
        p = self.officer.post(f"{FAC}{f['id']}/edit/", {"version": f["version"], "capacity": 8}, format="json")
        self.assertEqual((p.status_code, p.data["capacity"], p.data["held_now"]), (200, 8, 1))

    def test_the_register_lists_the_facility(self):
        self.make()
        self.assertEqual(self.officer.get(URL).data["results"][0]["facility"]["kind"], "jail_center")
