"""Fitness for duty and restricted medical records. Synthetic data only."""
from datetime import date, timedelta

from apps.audit.models import AuditEvent
from apps.core import crypto
from apps.core.appendonly import AppendOnlyError
from apps.medical.models import MedicalEntry
from apps.personnel.tests.test_personnel import PersonnelBase

F = "/api/v1/fitness/"
SECRET = "Fractured left tibia, surgery planned"


class MedicalBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.unit_a = self.unit("BARI-ARMY-A")
        self.doc = self.client_for(self.make_user("med.officer", "medical_officer", unit="BARI-ARMY-A"))
        self.cmdr = self.client_for(self.make_user("med.cmdr", "unit_commander", unit="BARI-ARMY-A"))
        self.other = self.client_for(self.make_user("med.other", "unit_commander", unit="BARI-ARMY-B"))
        self.p1 = self.person("BARI-ARMY-A", "Soldier One")
        self.p2 = self.person("BARI-ARMY-A", "Soldier Two")

    def add(self, p=None, c=None, **kw):
        body = {"personnel": str((p or self.p1).pk), "fitness_status": "limited", "restriction": "No night duty", "details": SECRET}
        body.update(kw)
        return (c or self.doc).post(F + "add/", body, format="json")

    def table(self, c=None, **params):
        r = (c or self.cmdr).get(F, {"org_unit": str(self.unit_a.pk), **params})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()


class RecordTests(MedicalBase):
    def test_the_medical_officer_records_an_entry_and_it_is_encrypted(self):
        r = self.add(review_due=(date.today() + timedelta(days=30)).isoformat())
        self.assertEqual(r.status_code, 201, r.content)
        row = MedicalEntry.objects.get()
        self.assertNotIn("tibia", row.details_enc + row.restriction_enc)  # nothing readable in the database
        self.assertEqual(crypto.decrypt(row.details_enc), SECRET)
        ev = AuditEvent.objects.get(action="medical.add")
        self.assertNotIn("tibia", str(ev.metadata))  # the audit trail never holds the text

    def test_a_commander_cannot_record(self):
        self.assertEqual(self.add(c=self.cmdr).status_code, 403)

    def test_values_are_validated(self):
        self.assertEqual(self.codes(self.add(fitness_status="sick"), "fitness_status"), ["invalid_status"])
        self.assertEqual(self.codes(self.add(review_due="2001-01-01"), "review_due"), ["due_invalid"])
        self.assertEqual(self.codes(self.add(review_due=(date.today() + timedelta(days=2000)).isoformat()), "review_due"), ["due_invalid"])
        self.assertEqual(self.codes(self.add(restriction="x" * 301), "details"), ["too_long"])
        self.assertEqual(self.codes(self.add(p=self.p1, personnel="nope"), "personnel"), ["person_unknown"])

    def test_a_person_out_of_scope_reads_as_unknown(self):
        far = self.person("BARI-ARMY-B", "Elsewhere")
        self.assertEqual(self.codes(self.add(p=far), "personnel"), ["person_unknown"])

    def test_entries_are_append_only_and_corrections_form_a_chain(self):
        first = self.add().json()["id"]
        row = MedicalEntry.objects.get(pk=first)
        with self.assertRaises(AppendOnlyError):
            row.fitness_status = "fit"
            row.save()
        with self.assertRaises(AppendOnlyError):
            MedicalEntry.objects.filter(pk=first).update(fitness_status="fit")
        fix = self.add(fitness_status="fit", corrects=first, details="Entered in error").json()["id"]
        self.assertEqual(self.codes(self.add(corrects=first), "corrects"), ["already_corrected"])  # correct the latest instead
        self.assertEqual(self.add(fitness_status="unfit", corrects=fix).status_code, 201)
        h = self.doc.get(F + "history/", {"personnel": str(self.p1.pk)}).json()["results"]
        self.assertEqual([x["superseded"] for x in h], [False, True, True])


class VisibilityTests(MedicalBase):
    def test_a_commander_sees_fitness_but_never_the_details(self):
        self.add(review_due=(date.today() + timedelta(days=30)).isoformat())
        row = {r["personnel"]["full_name"]: r for r in self.table()["results"]}["Soldier One"]
        self.assertEqual((row["fitness_status"], row["restriction"], row["overdue"]), ("limited", "No night duty", False))
        self.assertNotIn("tibia", str(row))
        h = self.cmdr.get(F + "history/", {"personnel": str(self.p1.pk)}).json()
        self.assertEqual((h["can_see_details"], h["results"][0]["details"]), (False, None))
        self.assertNotIn("tibia", str(h))

    def test_the_medical_officer_sees_the_details(self):
        self.add()
        h = self.doc.get(F + "history/", {"personnel": str(self.p1.pk)}).json()
        self.assertEqual((h["can_see_details"], h["results"][0]["details"]), (True, SECRET))

    def test_every_read_is_audited(self):
        self.add()
        self.table()
        self.cmdr.get(F + "history/", {"personnel": str(self.p1.pk)})
        self.doc.get(F + "history/", {"personnel": str(self.p1.pk)})
        actions = set(AuditEvent.objects.values_list("action", flat=True))
        self.assertTrue({"fitness.read", "fitness.view", "medical.view"} <= actions, actions)

    def test_scope_is_enforced_on_both_reads(self):
        self.add()
        r = self.other.get(F, {"org_unit": str(self.unit_a.pk)})
        self.assertEqual(r.status_code, 400)
        r = self.other.get(F + "history/", {"personnel": str(self.p1.pk)})
        self.assertEqual(self.codes(r, "personnel"), ["person_unknown"])

    def test_a_member_sees_nothing(self):
        m = self.client_for(self.make_user("med.member", "member", unit="BARI-ARMY-A"))
        self.assertEqual(m.get(F, {"org_unit": str(self.unit_a.pk)}).status_code, 403)
        self.assertEqual(m.get(F + "history/", {"personnel": str(self.p1.pk)}).status_code, 403)

    def test_the_headquarters_administrator_cannot_read_or_write_medical_details(self):
        hq = self.client_for(self.make_user("med.hq", "hq_admin"))
        self.add()
        self.assertEqual(hq.post(F + "add/", {"personnel": str(self.p1.pk), "fitness_status": "fit"}, format="json").status_code, 403)
        h = hq.get(F + "history/", {"personnel": str(self.p1.pk)}).json()
        self.assertEqual((h["can_see_details"], h["results"][0]["details"]), (False, None))


class OverviewTests(MedicalBase):
    def test_counts_current_status_and_unassessed(self):
        self.add(fitness_status="unfit")
        first = self.add(p=self.p2, fitness_status="fit").json()["id"]
        self.add(p=self.p2, fitness_status="limited", corrects=first)  # the correction is current now
        d = self.table()
        self.assertEqual({k: d["counts"][k] for k in ("unfit", "limited", "fit", "unassessed")}, {"unfit": 1, "limited": 1, "fit": 0, "unassessed": 0})
        self.person("BARI-ARMY-A", "Never Assessed")
        self.assertEqual(self.table()["counts"]["unassessed"], 1)
        self.assertEqual([r["personnel"]["full_name"] for r in self.table(state="unassessed")["results"]], ["Never Assessed"])

    def test_overdue_reviews_are_found(self):
        self.add(review_due=date.today().isoformat())
        self.assertEqual(self.table()["counts"]["overdue"], 0)
        e = MedicalEntry(personnel=self.p2, fitness_status="fit", review_due=date.today() - timedelta(days=3), recorded_by_username="t")
        e.save()  # an old entry whose review date has passed
        d = self.table(state="overdue")
        self.assertEqual((d["counts"]["overdue"], [r["personnel"]["full_name"] for r in d["results"]]), (1, ["Soldier Two"]))


class SuperAdministratorSeesEverythingTests(MedicalBase):
    """Nothing is hidden from the super administrator, including medical details and restricted units (for demonstrations)."""

    def setUp(self):
        super().setUp()
        self.sa = self.client_for(self.make_user("med.sa", "super_admin"))

    def test_sees_the_details_and_can_record_and_correct(self):
        first = self.add().json()["id"]
        h = self.sa.get(F + "history/", {"personnel": str(self.p1.pk)}).json()
        self.assertEqual((h["can_see_details"], h["results"][0]["details"]), (True, SECRET))
        r = self.add(c=self.sa, fitness_status="fit", corrects=first, details="Cleared after review")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.table(c=self.sa)["counts"]["fit"], 1)

    def test_sees_a_restricted_unit_that_an_ordinary_commander_cannot(self):
        from apps.organization.models import OrganizationalUnit
        self.add()
        OrganizationalUnit.objects.filter(pk=self.unit_a.pk).update(restricted=True)
        self.assertEqual(self.cmdr.get(F, {"org_unit": str(self.unit_a.pk)}).status_code, 400)  # no restricted access
        d = self.sa.get(F, {"org_unit": str(self.unit_a.pk)})
        self.assertEqual(d.status_code, 200, d.content)
        h = self.sa.get(F + "history/", {"personnel": str(self.p1.pk)}).json()
        self.assertEqual(h["results"][0]["details"], SECRET)
