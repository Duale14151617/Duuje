from datetime import date, timedelta

from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import ServiceBranch
from apps.personnel import services as pers
from apps.personnel.models import Personnel
from apps.ranks.models import Rank
from apps.training.models import Course, TrainingRecord

T = "/api/v1/training/"


class TrainingBase(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, parent in (("BARI-ARMY-A", "BARI-ARMY"), ("NUGAAL-ARMY-A", "NUGAAL-ARMY")):
            OU.objects.create(code=code, name_en=code, level="unit", parent=OU.objects.get(code=parent))

    def who(self, name, role, unit):
        cache = self.__dict__.setdefault("_clients", {})
        if name not in cache:
            cache[name] = self.client_for(self.make_user(name, role, unit=unit))
        return cache[name]

    def trainer(self):
        return self.who("trainer", "training_admin", "BARI")

    def person(self, name="Bari Trainee", unit="BARI-ARMY-A", status="active"):
        p = pers.create_personnel(None, full_name=name, phone="", service_number=None, org_unit=self.unit(unit),
                                  rank=Rank.objects.get(branch__code="ARMY", code="PA-03"), status="active", effective_date=None)
        if status != "active":
            Personnel.objects.filter(pk=p.pk).update(status=status)
        return p

    def course(self, code="first_aid"):
        return Course.objects.get(code=code)

    def enroll(self, client, person, course=None, start="2026-03-01", **kw):
        return client.post(T + "records/", {"personnel": str(person.pk), "course": str((course or self.course()).pk),
                                            "start_date": start, **kw}, format="json")

    def to(self, client, rec, status, **kw):
        return client.post(f"{T}records/{rec['id']}/status/", {"status": status, "version": rec["version"], **kw}, format="json")


class CourseTests(TrainingBase):
    def test_catalogue_is_configured_at_headquarters_only(self):
        adm = self.who("adm", "hq_admin", "HQ")
        body = {"code": "Drill_Basics", "name_en": "Drill basics", "name_so": "Tababarka asaasiga", "duration_days": 4}
        r = adm.post(T + "courses/", body, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (201, "drill_basics"), r.data)
        self.assertEqual(self.trainer().post(T + "courses/", {**body, "code": "x2"}, format="json").status_code, 403)  # regional scope is not global
        self.assertEqual(len(self.trainer().get(T + "courses/").data), 4)
        upd = adm.patch(f"{T}courses/{r.data['id']}/", {"name_en": "Drill", "code": "changed", "version": 1}, format="json")
        self.assertEqual((upd.data["name_en"], upd.data["code"]), ("Drill", "drill_basics"))  # codes are permanent
        stale = adm.patch(f"{T}courses/{r.data['id']}/", {"name_en": "Again", "version": 1}, format="json")
        self.assertEqual((stale.status_code, stale.data["code"]), (409, "version_conflict"))
        self.assertEqual(self.who("ro", "read_only", "BARI").get(T + "courses/").status_code, 403)


class RecordTests(TrainingBase):
    def test_enrolment_rules(self):
        t, p = self.trainer(), self.person()
        r = self.enroll(t, p, status="completed", completed_on="2026-03-02", version=9)
        self.assertEqual((r.status_code, r.data["status"], r.data["completed_on"]), (201, "enrolled", None), r.data)
        self.assertEqual(r.data["created_by_username"], "trainer")
        self.assertIn("training_duplicate", self.codes(self.enroll(t, p), "start_date"))
        self.assertIn("person_not_eligible", self.codes(self.enroll(t, self.person("Retired Person", status="retired")), "personnel"))
        Course.objects.filter(code="leadership_basics").update(active=False)
        self.assertIn("course_inactive", self.codes(self.enroll(t, p, self.course("leadership_basics")), "course"))
        self.assertIn("period_invalid", self.codes(self.enroll(t, p, self.course("basic_administration"), end_date="2026-02-01"), "end_date"))

    def test_people_outside_scope_and_unknown_people_look_identical(self):
        far = self.person("Nugaal Person", "NUGAAL-ARMY-A")
        t = self.trainer()
        a = self.enroll(t, far)
        import uuid
        b = t.post(T + "records/", {"personnel": str(uuid.uuid4()), "course": str(self.course().pk), "start_date": "2026-03-01"}, format="json")
        self.assertEqual((a.status_code, self.codes(a, "personnel")), (b.status_code, self.codes(b, "personnel")))
        self.assertEqual(self.codes(a, "personnel"), ["person_not_found"])
        self.assertEqual(TrainingRecord.objects.count(), 0)

    def test_status_transitions_and_completion_rules(self):
        t = self.trainer()
        rec = self.enroll(t, self.person()).data
        self.assertEqual(self.to(t, rec, "completed", completed_on="2026-03-05").status_code, 409)  # must be in progress first
        rec = self.to(t, rec, "in_progress").data
        self.assertEqual(rec["status"], "in_progress")
        self.assertIn("completed_on_required", self.codes(self.to(t, rec, "completed"), "completed_on"))
        self.assertIn("completed_on_invalid", self.codes(self.to(t, rec, "completed", completed_on="2026-02-01"), "completed_on"))
        future = (date.today() + timedelta(days=3)).isoformat()
        self.assertIn("completed_on_invalid", self.codes(self.to(t, rec, "completed", completed_on=future), "completed_on"))
        done = self.to(t, rec, "completed", completed_on="2026-03-05")
        self.assertEqual((done.status_code, done.data["status"], done.data["completed_on"]), (200, "completed", "2026-03-05"))
        self.assertEqual(self.to(t, done.data, "failed").status_code, 409)  # terminal
        edit = t.patch(f"{T}records/{rec['id']}/", {"notes": "late", "version": done.data["version"]}, format="json")
        self.assertEqual(edit.status_code, 409)

    def test_open_records_can_be_edited_withdrawn_and_are_versioned(self):
        t = self.trainer()
        rec = self.enroll(t, self.person()).data
        ok = t.patch(f"{T}records/{rec['id']}/", {"notes": "Bring kit", "end_date": "2026-03-10", "version": rec["version"]}, format="json")
        self.assertEqual((ok.status_code, ok.data["notes"]), (200, "Bring kit"))
        bad = t.patch(f"{T}records/{rec['id']}/", {"end_date": "2026-01-01", "version": ok.data["version"]}, format="json")
        self.assertIn("period_invalid", self.codes(bad, "end_date"))
        stale = t.patch(f"{T}records/{rec['id']}/", {"notes": "x", "version": rec["version"]}, format="json")
        self.assertEqual((stale.status_code, stale.data["code"]), (409, "version_conflict"))
        w = self.to(t, ok.data, "withdrawn")
        self.assertEqual(w.data["status"], "withdrawn")

    def test_scope_and_role_boundaries(self):
        mine, far = self.person(), self.person("Nugaal Person", "NUGAAL-ARMY-A")
        t, n = self.trainer(), self.who("n-trainer", "training_admin", "NUGAAL")
        rec = self.enroll(t, mine).data
        nrec = self.enroll(n, far).data
        self.assertEqual(n.get(f"{T}records/{rec['id']}/").status_code, 404)
        self.assertEqual(self.to(n, rec, "in_progress").status_code, 404)
        self.assertEqual(n.patch(f"{T}records/{rec['id']}/", {"notes": "x", "version": 1}, format="json").status_code, 404)
        self.assertEqual(t.get(T + "records/").data["count"], 1)
        self.assertEqual(n.get(T + "records/").data["results"][0]["id"], nrec["id"])
        self.assertEqual(t.get(T + f"records/?org_unit={self.unit('NUGAAL').pk}").data["count"], 0)
        viewer = self.who("uadm", "unit_admin", "BARI-ARMY-A")  # may view but not change
        self.assertEqual(viewer.get(f"{T}records/{rec['id']}/").status_code, 200)
        self.assertEqual(self.to(viewer, rec, "in_progress").status_code, 403)
        self.assertEqual(self.enroll(viewer, mine, start="2026-04-01").status_code, 403)
        self.assertEqual(self.who("adm", "hq_admin", "HQ").get(T + "records/").status_code, 403)
        self.assertEqual(self.who("ro", "read_only", "BARI").get(T + "records/").status_code, 403)
        self.assertEqual(t.get(T + "records/?course=abc").status_code, 400)

    def test_training_staff_get_no_broad_personnel_access(self):
        self.person("Visible Name")
        t = self.trainer()
        self.assertEqual(t.get("/api/v1/personnel/").status_code, 403)  # no personnel.view
        people = t.get(T + "people/?q=visible").data["results"]
        self.assertEqual(len(people), 1)
        self.assertEqual(set(people[0]), {"id", "full_name", "org_unit"})  # nothing else about the person
        self.assertEqual(self.who("n-trainer", "training_admin", "NUGAAL").get(T + "people/").data["count"], 0)
        self.person("Retired Person", status="retired")
        self.assertEqual(t.get(T + "people/").data["count"], 1)  # only active / on-leave people can be enrolled
        rec = self.enroll(t, Personnel.objects.get(full_name="Visible Name")).data
        self.assertEqual(set(rec["personnel"]), {"id", "full_name", "org_unit"})


class SummaryTests(TrainingBase):
    def test_summary_counts_by_course_region_and_status(self):
        t, n = self.trainer(), self.who("n-trainer", "training_admin", "NUGAAL")
        a = self.enroll(t, self.person("A"), start="2026-03-01").data
        b = self.enroll(t, self.person("B"), start="2026-03-01").data
        self.to(t, self.to(t, b, "in_progress").data, "completed", completed_on="2026-03-05")
        self.enroll(n, self.person("C", "NUGAAL-ARMY-A"), start="2026-04-01")
        rows = lambda r: {(x["course"]["code"], x["region"]["code"]): x for x in r.data["rows"]}
        mine = rows(t.get(T + "summary/"))
        self.assertEqual(set(mine), {("first_aid", "BARI")})
        self.assertEqual((mine[("first_aid", "BARI")]["total"], mine[("first_aid", "BARI")]["counts"]), (2, {"enrolled": 1, "completed": 1}))
        hq = rows(self.who("hqr", "hq_reporting", "HQ").get(T + "summary/"))
        self.assertEqual({k[1] for k in hq}, {"BARI", "NUGAAL"})
        self.assertEqual(rows(t.get(T + "summary/?from=2026-03-15")).get(("first_aid", "BARI")), None)
        self.assertEqual(t.get(T + "summary/?from=nope").status_code, 400)
        self.assertEqual(self.who("uadm", "unit_admin", "BARI-ARMY-A").get(T + "summary/").status_code, 403)
        self.assertEqual(a["status"], "enrolled")
