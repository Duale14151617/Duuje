"""Command appointments: separate from rank, assignment and application role. Synthetic data only."""
from datetime import date, timedelta

from django.core.management import call_command

from apps.accounts.models import RoleAssignment
from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.organization.models import OrganizationalUnit as OU, UnitType
from apps.personnel.models import AppointmentType, CommandAppointment, Personnel

from .test_personnel import URL, PersonnelBase


class AppointmentBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        call_command("apply_army_structure", "--apply", stdout=open("/dev/null", "w"))  # Bari Army becomes a Qayb
        self.urur = OU.objects.create(code="BARI-ARMY-URUR1", name_en="Urur 1", level="unit",
                                      parent=OU.objects.get(code="BARI-ARMY"), unit_type=UnitType.objects.get(code="URUR"))
        self.boss = self.manager()                       # branch_admin, Bari Army: may appoint
        self.col = self.person("BARI-ARMY-A", "Colonel One", rank="PA-12")
        self.maj = self.person("BARI-ARMY-A", "Major One", rank="PA-10")

    def t(self, code):
        return str(AppointmentType.objects.get(code=code).pk)

    def appoint(self, person=None, type_code="TALIYE_QAYBEED", unit="BARI-ARMY", c=None, **kw):
        unit_obj = self.urur if unit == "URUR" else OU.objects.get(code=unit)
        body = {"org_unit": str(unit_obj.pk), "appointment_type": self.t(type_code),
                "effective_from": date.today().isoformat(), "authority_ref": "Order 12/2026", **kw}
        return (c or self.boss).post(f"{URL}{(person or self.col).pk}/appointments/add/", body, format="json")


class AppointmentTests(AppointmentBase):
    def test_types_are_seeded_and_tied_to_unit_types(self):
        got = {t.code: (t.unit_type.code, t.exclusive) for t in AppointmentType.objects.all()}
        self.assertEqual(got, {"TALIYE_QAYBEED": ("QAYB", True), "TALIYE_GUUTO": ("GUUTO", True),
                               "TALIYE_URUR": ("URUR", True), "ABAANDUULE": ("URUR", False)})

    def test_appoint_a_regional_commander_and_audit_it(self):
        r = self.appoint()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["current"])
        self.assertEqual(r.json()["appointment_type"]["name_so"], "Taliye Qaybeed")
        self.assertTrue(AuditEvent.objects.filter(action="personnel.appointment_created").exists())

    def test_appointment_changes_neither_rank_nor_assignment_nor_role(self):
        before = Personnel.objects.filter(pk=self.col.pk).values("rank_id", "org_unit_id", "version").get()
        self.appoint()
        self.assertEqual(Personnel.objects.filter(pk=self.col.pk).values("rank_id", "org_unit_id", "version").get(), before)
        self.assertFalse(RoleAssignment.objects.filter(user__personnel_record=self.col).exists())

    def test_only_authorized_officers_can_appoint(self):
        self.assertEqual(self.appoint(c=self._cached("uadm", "unit_admin", "BARI-ARMY-A")).status_code, 403)
        m = self.client_for(self.make_user("mem", "member", unit="BARI-ARMY"))
        self.assertEqual(self.appoint(c=m).status_code, 403)

    def test_type_must_fit_the_unit(self):
        r = self.appoint(type_code="TALIYE_URUR", unit="BARI-ARMY")
        self.assertEqual(self.codes(r, "org_unit"), ["appointment_unit_mismatch"])
        self.assertEqual(self.appoint(type_code="TALIYE_URUR", unit="URUR").status_code, 201)

    def test_one_current_commander_per_unit_but_abaanduule_can_be_shared(self):
        self.assertEqual(self.appoint().status_code, 201)
        self.assertEqual(self.codes(self.appoint(person=self.maj), "appointment_type"), ["appointment_exists"])
        self.assertEqual(self.appoint(person=self.col, type_code="ABAANDUULE", unit="URUR").status_code, 201)
        self.assertEqual(self.appoint(person=self.maj, type_code="ABAANDUULE", unit="URUR").status_code, 201)

    def test_unit_outside_the_officers_scope_reads_like_an_invalid_unit(self):
        far = OU.objects.get(code="NUGAAL-ARMY")
        r = self.boss.post(f"{URL}{self.col.pk}/appointments/add/", {
            "org_unit": str(far.pk), "appointment_type": self.t("TALIYE_QAYBEED"), "effective_from": date.today().isoformat()}, format="json")
        self.assertEqual(self.codes(r, "org_unit"), ["org_unit_invalid"])

    def test_bad_dates_and_non_serving_people_are_refused(self):
        r = self.appoint(effective_to=(date.today() - timedelta(days=1)).isoformat())
        self.assertEqual(self.codes(r, "effective_to"), ["appointment_dates"])
        Personnel.objects.filter(pk=self.maj.pk).update(status="retired")
        self.assertEqual(self.codes(self.appoint(person=self.maj), "personnel"), ["person_not_serving"])

    def test_ending_keeps_history_and_cannot_be_repeated(self):
        a = self.appoint().json()
        end = lambda: self.boss.post(f"{URL}{self.col.pk}/appointments/{a['id']}/end/", {"reason": "Rotated"}, format="json")
        r = end()
        self.assertEqual((r.status_code, r.json()["current"]), (200, False))
        self.assertEqual(CommandAppointment.objects.filter(personnel=self.col).count(), 1)  # the row stays
        self.assertEqual(self.codes(end(), "appointment"), ["appointment_ended"])
        self.assertEqual(self.appoint(person=self.maj).status_code, 201)  # the office is free again

    def test_rows_cannot_be_deleted(self):
        a = CommandAppointment.objects.get(pk=self.appoint().json()["id"])
        with self.assertRaises(AppendOnlyError):
            a.delete()


class AccessFollowsAuthorityTests(AppointmentBase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("col.user", "unit_admin", unit="BARI-ARMY-A")
        Personnel.objects.filter(pk=self.col.pk).update(account=self.user)
        self.grant = RoleAssignment.objects.get(user=self.user)

    def test_ending_the_appointment_revokes_the_linked_access(self):
        a = self.appoint(role_assignment=str(self.grant.pk)).json()
        self.boss.post(f"{URL}{self.col.pk}/appointments/{a['id']}/end/", {"reason": "Term ended"}, format="json")
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)
        self.assertTrue(AuditEvent.objects.filter(action="personnel.appointment_ended", metadata__access_revoked=True).exists())

    def test_an_appointment_without_a_link_never_touches_access(self):
        a = self.appoint().json()
        self.boss.post(f"{URL}{self.col.pk}/appointments/{a['id']}/end/", {"reason": "x"}, format="json")
        self.grant.refresh_from_db()
        self.assertIsNone(self.grant.revoked_at)

    def test_only_the_persons_own_access_can_be_linked(self):
        other = self.make_user("other.user", "unit_admin", unit="BARI-ARMY-A")
        theirs = RoleAssignment.objects.get(user=other)
        self.assertEqual(self.codes(self.appoint(role_assignment=str(theirs.pk)), "role_assignment"), ["assignment_mismatch"])

    def test_retiring_the_officer_ends_appointments_and_access(self):
        self.appoint(role_assignment=str(self.grant.pk))
        self.col.refresh_from_db()
        r = self.boss.post(f"{URL}{self.col.pk}/change-status/", {"status": "retired", "version": self.col.version}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(CommandAppointment.objects.filter(personnel=self.col, ended_at__isnull=True).exists())
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)

    def test_confirmed_death_ends_appointments(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.appoint(role_assignment=str(self.grant.pk))
        rep = self._cached("rep", "unit_admin", "BARI-ARMY-A")
        self.assertEqual(rep.post(f"{URL}{self.col.pk}/death/report/", {"date_of_death": date.today().isoformat()}, format="json").status_code, 201)
        form = {"title": "Certificate", "category": "death_evidence", "file": SimpleUploadedFile("c.pdf", b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF")}
        self.assertEqual(rep.post(f"{URL}{self.col.pk}/documents/upload/", form, format="multipart").status_code, 201)
        self.col.refresh_from_db()
        self.assertEqual(self.boss.post(f"{URL}{self.col.pk}/death/confirm/", {"version": self.col.version}, format="json").status_code, 200)
        self.assertFalse(CommandAppointment.objects.filter(personnel=self.col, ended_at__isnull=True).exists())
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)


class AppointmentReadTests(AppointmentBase):
    def test_unit_listing_and_person_view(self):
        self.appoint()
        r = self.boss.get(f"{URL}appointments/", {"org_unit": str(OU.objects.get(code="BARI-ARMY").pk), "current": "1"})
        rows = r.json()["results"]
        self.assertEqual([x["personnel"]["full_name"] for x in rows], ["Colonel One"])
        self.assertEqual(self.boss.get(f"{URL}{self.col.pk}/appointments/").json()["results"][0]["appointment_type"]["code"], "TALIYE_QAYBEED")

    def test_catalogue_lists_active_types(self):
        r = self.boss.get(f"{URL}appointment-types/")
        self.assertEqual({t["code"] for t in r.json()["results"]}, {"TALIYE_QAYBEED", "TALIYE_GUUTO", "TALIYE_URUR", "ABAANDUULE"})

    def test_a_member_may_read_their_own_appointments_only(self):
        self.appoint()
        user = self.make_user("colm", "member", unit="BARI-ARMY")
        Personnel.objects.filter(pk=self.col.pk).update(account=user)
        c = self.client_for(user)
        self.assertEqual(c.get(f"{URL}{self.col.pk}/appointments/").status_code, 200)
        self.assertEqual(c.get(f"{URL}{self.maj.pk}/appointments/").status_code, 404)
