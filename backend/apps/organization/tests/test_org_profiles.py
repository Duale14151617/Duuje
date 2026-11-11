"""Organizational structure upgrade: departments, unit and department profiles, chart, analytics, restricted rosters, audit.

Synthetic data only: every unit, person and appointment below is created by the test itself.
"""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from apps.audit.models import AuditEvent
from apps.organization.models import Department, OrganizationalUnit as OU, UnitDepartment, UnitType
from apps.personnel import appointments as appt_svc
from apps.personnel.models import AppointmentType, Personnel
from apps.personnel.services import RuleError
from apps.personnel.tests.test_personnel import PersonnelBase

UNITS = "/api/v1/organization/units/"
PEOPLE = "/api/v1/personnel/"


class OrgStructureBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        call_command("apply_army_structure", "--apply", stdout=open("/dev/null", "w"))
        bari = OU.objects.get(code="BARI-ARMY")
        self.urur = OU.objects.create(code="BARI-ARMY-U9", name_en="Test Urur", level="unit", parent=bari,
                                      unit_type=UnitType.objects.get(code="URUR"))
        UnitDepartment.objects.filter(unit=self.urur).delete()  # new formations are set up automatically; start these tests blank
        self.admin_user = self.make_user("org_hq", "hq_admin")
        self.hq = self.client_for(self.admin_user)
        self.medical = Department.objects.get(code="MEDICAL")
        self.finance = Department.objects.get(code="FINANCE")
        self.since = date.today() - timedelta(days=1)

    def person_in(self, unit, name, department=None, status="active", rank="PA-03"):
        p = self.person(unit, name, rank=rank)
        Personnel.objects.filter(pk=p.pk).update(department=department, status=status)
        return Personnel.objects.get(pk=p.pk)

    def establish(self, unit, dept):
        return UnitDepartment.objects.get_or_create(unit=unit, department=dept)[0]

    def appoint(self, person, unit, code, department=None):
        return appt_svc.create(self.admin_user, person, unit, AppointmentType.objects.get(code=code), self.since, department=department)


class ReferenceTests(OrgStructureBase):
    def test_the_seven_standard_departments_exist_and_are_established_at_general_headquarters(self):
        codes = set(Department.objects.values_list("code", flat=True))
        self.assertTrue({"COMMAND_ADMIN", "HR", "MEDICAL", "FINANCE", "LOGISTICS", "COMMUNICATIONS", "TRAINING"} <= codes)
        ghq = OU.objects.get(code="ARMY-HQ")
        self.assertEqual(UnitDepartment.objects.filter(unit=ghq, active=True).count(), 7)
        for code in ("BARI-ARMY", "BARI-ARMY-G1", "BARI-ARMY-U1"):  # regional command, brigade and battalion are ready too
            unit = OU.objects.filter(code=code).first()
            if unit is not None:
                self.assertEqual(UnitDepartment.objects.filter(unit=unit, active=True).count(), 7, code)
        self.assertFalse(Personnel.objects.filter(org_unit=ghq).exists())  # nobody is created or assigned
        self.assertFalse(appt_svc.CommandAppointment.objects.exists())     # and nobody is appointed

    def test_standard_unit_types_carry_their_formation_role(self):
        roles = dict(UnitType.objects.exclude(formation_role="").values_list("code", "formation_role"))
        self.assertEqual(roles, {"TALISKA_GUUD": "ghq", "QAYB": "regional", "GUUTO": "brigade", "URUR": "battalion"})

    def test_finance_and_medical_rosters_are_restricted_by_default(self):
        self.assertEqual(set(Department.objects.filter(restricted_roster=True).values_list("code", flat=True)), {"MEDICAL", "FINANCE"})


class UnitProfileTests(OrgStructureBase):
    def test_profile_counts_each_person_once_with_active_and_inactive(self):
        self.person_in("BARI-ARMY-U9", "Active One")
        self.person_in("BARI-ARMY-U9", "Leave One", status="on_leave")
        self.person_in("BARI-ARMY-U9", "Retired One", status="retired")
        r = self.hq.get(f"{UNITS}{self.urur.pk}/profile/")
        self.assertEqual(r.status_code, 200, r.content)
        s = r.json()["stats"]
        self.assertEqual((s["total"], s["active"], s["inactive"]), (3, 1, 2))
        self.assertEqual(s["by_status"], {"active": 1, "on_leave": 1, "retired": 1})
        self.assertEqual(sum(x["count"] for x in r.json()["by_rank"]), 3)
        self.assertTrue(AuditEvent.objects.filter(action="org_unit.profile_view").exists())

    def test_leadership_shows_only_real_appointments(self):
        r = self.hq.get(f"{UNITS}{self.urur.pk}/profile/").json()
        self.assertEqual((r["leadership"]["commander"], r["leadership"]["deputy"], r["leadership"]["administrative"]), ([], [], []))
        boss = self.person_in("BARI-ARMY-U9", "Commander Test")
        dep = self.person_in("BARI-ARMY-U9", "Deputy Test")
        self.appoint(boss, self.urur, "TALIYE_URUR")
        self.appoint(dep, self.urur, "UNIT_DEPUTY")
        r = self.hq.get(f"{UNITS}{self.urur.pk}/profile/").json()
        self.assertEqual(r["leadership"]["commander"][0]["holder"]["full_name"], "Commander Test")
        self.assertEqual(r["leadership"]["deputy"][0]["holder"]["full_name"], "Deputy Test")

    def test_department_head_needs_an_established_department(self):
        p = self.person_in("BARI-ARMY-U9", "Head Test")
        with self.assertRaises(RuleError) as ctx:
            self.appoint(p, self.urur, "DEPT_HEAD", department=self.medical)
        self.assertEqual(ctx.exception.code, "department_not_established")
        with self.assertRaises(RuleError) as ctx:
            self.appoint(p, self.urur, "DEPT_HEAD")
        self.assertEqual(ctx.exception.code, "department_required")
        self.establish(self.urur, self.medical)
        self.appoint(p, self.urur, "DEPT_HEAD", department=self.medical)
        with self.assertRaises(RuleError) as ctx:  # one head per department and unit
            self.appoint(self.person_in("BARI-ARMY-U9", "Other"), self.urur, "DEPT_HEAD", department=self.medical)
        self.assertEqual(ctx.exception.code, "appointment_exists")
        with self.assertRaises(RuleError) as ctx:  # an ordinary office never carries a department
            self.appoint(p, self.urur, "TALIYE_URUR", department=self.medical)
        self.assertEqual(ctx.exception.code, "department_not_allowed")

    def test_two_departments_may_each_have_a_head_in_the_same_unit(self):
        self.establish(self.urur, self.medical)
        self.establish(self.urur, self.finance)
        self.appoint(self.person_in("BARI-ARMY-U9", "H1"), self.urur, "DEPT_HEAD", department=self.medical)
        self.appoint(self.person_in("BARI-ARMY-U9", "H2"), self.urur, "DEPT_HEAD", department=self.finance)

    def test_department_profile_lists_leadership_staff_and_assigned_people(self):
        sec = OU.objects.create(code="BARI-ARMY-U9-LOG", name_en="Log", level="unit", parent=self.urur)
        from apps.organization.models import Department as D
        logistics = D.objects.get(code="LOGISTICS")
        self.establish(self.urur, logistics)
        head = self.person_in("BARI-ARMY-U9", "Log Head", department=logistics)
        self.person_in("BARI-ARMY-U9", "Log Clerk", department=logistics)
        self.person_in("BARI-ARMY-U9-LOG", "Log Below", department=logistics)
        self.appoint(head, self.urur, "DEPT_HEAD", department=logistics)
        r = self.hq.get(f"{UNITS}{self.urur.pk}/departments/{logistics.pk}/")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["head"]["holder"]["full_name"], "Log Head")
        self.assertEqual(sorted(p["full_name"] for p in d["staff"]), ["Log Clerk", "Log Head"])
        self.assertEqual([p["full_name"] for p in d["assigned"]], ["Log Below"])
        self.assertEqual((d["staff_total"], d["assigned_total"]), (2, 1))
        self.assertTrue(AuditEvent.objects.filter(action="org_unit.department_view").exists())
        self.assertEqual(self.hq.get(f"{UNITS}{self.urur.pk}/departments/not-a-department-uuid-at-all-1234567/").status_code, 404)
        self.assertIsNotNone(sec)

    def test_a_role_that_may_not_count_people_sees_zero_and_no_names(self):
        self.person_in("BARI-ARMY-U9", "Hidden")
        aud = self.client_for(self.make_user("org_aud", "auditor"))
        r = aud.get(f"{UNITS}{self.urur.pk}/profile/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["stats"]["total"], r.json()["counts_complete"], r.json()["can"]["name"]), (0, False, False))

    def test_out_of_scope_units_are_not_found(self):
        other = self.client_for(self.make_user("org_nug", "regional_chief", unit="NUGAAL"))
        self.assertEqual(other.get(f"{UNITS}{self.urur.pk}/profile/").status_code, 404)


class RestrictedRosterTests(OrgStructureBase):
    def setUp(self):
        super().setUp()
        self.establish(self.urur, self.finance)
        self.clerk = self.person_in("BARI-ARMY-U9", "Finance Clerk", department=self.finance)
        self.person_in("BARI-ARMY-U9", "Plain Soldier")
        self.mgr = self.manager()  # branch administrator for Bari: no departments.view_restricted

    def names(self, client, **params):
        return sorted(p["full_name"] for p in client.get(PEOPLE, {"org_unit": str(self.urur.pk), **params}).json()["results"])

    def test_directory_hides_named_finance_staff_from_roles_without_the_restricted_permission(self):
        self.assertEqual(self.names(self.mgr), ["Plain Soldier"])
        self.assertEqual(self.names(self.hq), ["Finance Clerk", "Plain Soldier"])

    def test_the_person_still_sees_their_own_record(self):
        owner = self.make_user("org_clerk", "member")
        Personnel.objects.filter(pk=self.clerk.pk).update(account=owner)
        self.assertEqual(self.client_for(owner).get(f"{PEOPLE}{self.clerk.pk}/").status_code, 200)

    def test_profile_shows_counts_but_not_names_of_a_restricted_department(self):
        r = self.mgr.get(f"{UNITS}{self.urur.pk}/profile/").json()
        self.assertEqual(r["finance"]["count"], 1)
        self.assertTrue(r["finance"]["roster_hidden"])
        self.assertIsNone(r["finance"]["people"])
        full = self.hq.get(f"{UNITS}{self.urur.pk}/profile/").json()
        self.assertEqual([p["full_name"] for p in full["finance"]["people"]], ["Finance Clerk"])
        d = self.mgr.get(f"{UNITS}{self.urur.pk}/departments/{self.finance.pk}/").json()
        self.assertTrue(d["roster_hidden"])
        self.assertIsNone(d["staff"])
        self.assertEqual(d["staff_total"], 1)


class DirectoryTests(OrgStructureBase):
    def test_filter_by_department_unassigned_direct_and_sorting(self):
        self.person_in("BARI-ARMY-U9", "Bravo", department=self.medical, rank="PA-03")
        self.person_in("BARI-ARMY-U9", "Alpha", rank="PA-03")
        sec = OU.objects.create(code="BARI-ARMY-U9-S", name_en="S", level="unit", parent=self.urur)
        self.person_in("BARI-ARMY-U9-S", "Charlie")
        base = {"org_unit": str(self.urur.pk)}
        get = lambda **kw: [p["full_name"] for p in self.hq.get(PEOPLE, {**base, **kw}).json()["results"]]  # noqa: E731
        self.assertEqual(get(department=str(self.medical.pk)), ["Bravo"])
        self.assertEqual(get(no_department="1", ordering="name"), ["Alpha", "Charlie"])
        self.assertEqual(get(direct="1", ordering="-name"), ["Bravo", "Alpha"])
        self.assertEqual(get(ordering="-name"), ["Charlie", "Bravo", "Alpha"])
        self.assertEqual(self.hq.get(f"{PEOPLE}{Personnel.objects.get(full_name='Bravo').pk}/").json()["department"]["code"], "MEDICAL")
        self.assertIsNotNone(sec)

    def test_changing_a_department_is_audited_and_written_to_history(self):
        p = self.person_in("BARI-ARMY-U9", "Move Dept")
        r = self.hq.patch(f"{PEOPLE}{p.pk}/", {"department": str(self.medical.pk), "version": p.version}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["department"]["code"], "MEDICAL")
        h = p.history.filter(field="department")
        self.assertEqual([x.new_label for x in h], ["Medical Services"])
        self.assertTrue(AuditEvent.objects.filter(action="personnel.update", entity_id=str(p.pk)).exists())

    def test_create_with_a_department(self):
        r = self.hq.post(PEOPLE, self.body(unit="BARI-ARMY-A", full_name="New Medic", department=str(self.medical.pk)), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["department"]["code"], "MEDICAL")


class ChartAndAnalyticsTests(OrgStructureBase):
    def test_chart_nests_formations_with_their_strength(self):
        self.person_in("BARI-ARMY-U9", "One")
        self.person_in("BARI-ARMY-U9", "Two", status="suspended")
        r = self.hq.get(f"{UNITS}chart/")
        self.assertEqual(r.status_code, 200, r.content)

        def find(nodes, code):
            for n in nodes:
                if n["code"] == code:
                    return n
                hit = find(n["children"], code)
                if hit:
                    return hit
        roots = r.json()["roots"]
        self.assertEqual([n["formation_role"] for n in roots], ["ghq"])  # General Headquarters first, on top
        kids = roots[0]["children"]
        self.assertTrue(kids and all(k["formation_role"] == "regional" for k in kids))  # then the regional commands
        node = find(r.json()["roots"], "BARI-ARMY-U9")
        self.assertIsNotNone(node)
        self.assertEqual((node["total"], node["active"], node["inactive"]), (2, 1, 1))
        region = find(r.json()["roots"], "BARI-ARMY")
        self.assertEqual(region["formation_role"], "regional")
        self.assertGreaterEqual(region["total"], 2)  # the regional command counts everyone below it once

    def test_analytics_totals_formations_departments_and_leadership(self):
        self.establish(self.urur, self.medical)
        self.person_in("BARI-ARMY-U9", "One", department=self.medical)
        self.person_in("BARI-ARMY-U9", "Two")
        self.person_in("BARI-ARMY-U9", "Three", status="retired")
        self.appoint(self.person_in("BARI-ARMY-U9", "Boss"), self.urur, "TALIYE_URUR")
        r = self.hq.get("/api/v1/organization/analytics/")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["totals"]["total"], 4)
        self.assertEqual(d["totals"]["active"], 3)
        self.assertEqual(d["totals"]["inactive"], 1)
        bat = {u["code"]: u for u in d["by_formation"]["battalion"]}["BARI-ARMY-U9"]
        self.assertEqual((bat["total"], bat["active"], bat["inactive"]), (4, 3, 1))
        med = next(x for x in d["departments"] if x["department"]["code"] == "MEDICAL")
        self.assertEqual((med["total"], med["established_in"], med["with_head"]), (1, 1, 0))
        self.assertEqual(d["unassigned_department"]["total"], 3)
        self.assertGreaterEqual(d["leadership"]["with_commander"], 1)
        self.assertTrue(any(v["code"] == "BARI-ARMY-U9" and v["missing"] == ["deputy"] for v in d["leadership"]["vacancies"]))
        self.assertTrue(AuditEvent.objects.filter(action="org_analytics.view").exists())

    def test_analytics_needs_the_analytics_permission_and_respects_scope(self):
        member = self.client_for(self.make_user("org_member", "member"))
        self.assertEqual(member.get("/api/v1/organization/analytics/").status_code, 403)
        self.person_in("BARI-ARMY-U9", "Bari person")
        nug = self.client_for(self.make_user("org_nug_chief", "regional_chief", unit="NUGAAL"))
        self.assertEqual(nug.get("/api/v1/organization/analytics/").json()["totals"]["total"], 0)
        self.assertEqual(nug.get(f"/api/v1/organization/analytics/?unit={self.urur.pk}").status_code, 404)


class ConfigurationTests(OrgStructureBase):
    def test_catalogue_changes_need_the_configure_permission(self):
        body = {"code": "legal", "name_en": "Legal Affairs", "name_so": "Arrimaha Sharciga"}
        self.assertEqual(self.manager().post("/api/v1/organization/departments/", body, format="json").status_code, 403)
        r = self.hq.post("/api/v1/organization/departments/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["code"], "LEGAL")
        self.assertTrue(AuditEvent.objects.filter(action="department.create").exists())
        r2 = self.hq.patch(f"/api/v1/organization/departments/{r.json()['id']}/", {"restricted_roster": True, "version": 1}, format="json")
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertTrue(r2.json()["restricted_roster"])
        self.assertEqual(self.hq.post("/api/v1/organization/departments/", body, format="json").status_code, 400)  # duplicate code

    def test_formation_roles_are_configurable_data(self):
        row = next(x for x in self.hq.get("/api/v1/organization/formation-roles/").json() if x["code"] == "GUUTO")
        self.assertEqual(row["formation_role"], "brigade")
        r = self.hq.patch(f"/api/v1/organization/formation-roles/{row['id']}/", {"formation_role": "", "version": row["version"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(UnitType.objects.get(code="GUUTO").formation_role, "")
        self.assertEqual(self.manager().patch(f"/api/v1/organization/formation-roles/{row['id']}/", {"formation_role": "brigade", "version": 99},
                                              format="json").status_code, 403)

    def test_a_unit_establishes_and_retires_a_department_within_its_scope(self):
        mgr = self.manager()
        r = mgr.post("/api/v1/organization/unit-departments/", {"unit": str(self.urur.pk), "department": str(self.medical.pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(mgr.post("/api/v1/organization/unit-departments/", {"unit": str(self.urur.pk), "department": str(self.medical.pk)},
                                  format="json").status_code, 400)  # already established
        far = OU.objects.get(code="NUGAAL-ARMY")
        self.assertEqual(mgr.post("/api/v1/organization/unit-departments/", {"unit": str(far.pk), "department": str(self.medical.pk)},
                                  format="json").status_code, 400)  # out of scope reads like an unknown unit
        row = r.json()
        self.appoint(self.person_in("BARI-ARMY-U9", "Med Head"), self.urur, "DEPT_HEAD", department=self.medical)
        blocked = mgr.patch(f"/api/v1/organization/unit-departments/{row['id']}/", {"active": False, "version": row["version"]}, format="json")
        self.assertEqual(blocked.status_code, 400)  # end the head's appointment first
        self.assertTrue(AuditEvent.objects.filter(action="unit_department.establish").exists())


class AutomaticAndBulkTests(OrgStructureBase):
    def test_a_new_formation_gets_the_standard_departments_and_a_retired_one_stays_retired(self):
        new = OU.objects.create(code="BARI-ARMY-U10", name_en="New Urur", level="unit", parent=OU.objects.get(code="BARI-ARMY"),
                                unit_type=UnitType.objects.get(code="URUR"))
        self.assertEqual(UnitDepartment.objects.filter(unit=new, active=True).count(), 7)
        row = UnitDepartment.objects.get(unit=new, department__code="HR")
        UnitDepartment.objects.filter(pk=row.pk).update(active=False)
        new.name_en = "Renamed"
        new.save()  # saving again must not bring a retired department back
        self.assertFalse(UnitDepartment.objects.get(pk=row.pk).active)
        plain = OU.objects.create(code="BARI-ARMY-U10-X", name_en="Section", level="unit", parent=new)
        self.assertFalse(UnitDepartment.objects.filter(unit=plain).exists())  # ordinary units below a battalion are not formations

    def test_bulk_assign_and_clear_a_department(self):
        a = self.person_in("BARI-ARMY-U9", "Bulk A")
        b = self.person_in("BARI-ARMY-U9", "Bulk B", department=self.medical)
        dead = self.person_in("BARI-ARMY-U9", "Bulk C", status="retired")
        r = self.hq.post(f"{PEOPLE}bulk-department/", {"ids": [str(a.pk), str(b.pk), str(dead.pk)], "department": str(self.medical.pk)}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json(), {"updated": 2, "skipped": 1})  # b already had it
        self.assertEqual(Personnel.objects.get(pk=a.pk).department, self.medical)
        self.assertEqual([h.new_label for h in a.history.filter(field="department")], ["Medical Services"])
        r = self.hq.post(f"{PEOPLE}bulk-department/", {"ids": [str(a.pk)], "department": None}, format="json")
        self.assertEqual(r.json()["updated"], 1)
        self.assertIsNone(Personnel.objects.get(pk=a.pk).department)
        self.assertTrue(AuditEvent.objects.filter(action="personnel.bulk_department").exists())

    def test_bulk_assign_respects_scope_and_input_limits(self):
        far = self.person_in("BARI-ARMY-U9", "Bulk Far")
        nug = self.client_for(self.make_user("org_nug_mgr", "branch_admin", unit="NUGAAL-ARMY", branch="ARMY"))
        r = nug.post(f"{PEOPLE}bulk-department/", {"ids": [str(far.pk)], "department": str(self.medical.pk)}, format="json")
        self.assertEqual((r.status_code, r.json()["updated"]), (200, 0))  # out-of-scope people are skipped, never changed
        self.assertEqual(self.hq.post(f"{PEOPLE}bulk-department/", {"ids": [], "department": None}, format="json").status_code, 400)
        self.assertEqual(self.hq.post(f"{PEOPLE}bulk-department/", {"ids": ["nope"], "department": None}, format="json").status_code, 400)
        self.assertEqual(self.client_for(self.make_user("org_mem2", "member")).post(f"{PEOPLE}bulk-department/", {"ids": [str(far.pk)]}, format="json").status_code, 403)

    def test_csv_import_with_an_optional_department_column(self):
        def upload(text):
            return self.hq.post(f"{PEOPLE}import/preview", {"file": SimpleUploadedFile("p.csv", text.encode(), content_type="text/csv")}, format="multipart")
        ok = upload("full_name,unit_code,rank_code,department_code\nCsv Medic,BARI-ARMY-U9,PA-03,medical\nCsv Plain,BARI-ARMY-U9,PA-03,\n")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertTrue(ok.json()["can_commit"], ok.json())
        done = self.hq.post(f"{PEOPLE}import/commit", {"batch_id": ok.json()["batch_id"]}, format="json")
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(Personnel.objects.get(full_name="Csv Medic").department, self.medical)
        self.assertIsNone(Personnel.objects.get(full_name="Csv Plain").department)
        bad = upload("full_name,unit_code,rank_code,department_code\nCsv Bad,BARI-ARMY-U9,PA-03,NOPE\n")
        self.assertFalse(bad.json()["can_commit"])
        self.assertEqual(bad.json()["rows"][0]["errors"], ["department_unknown"])
        old = upload("full_name,unit_code,rank_code\nCsv Old,BARI-ARMY-U9,PA-03\n")  # files without the column still work
        self.assertTrue(old.json()["can_commit"])
