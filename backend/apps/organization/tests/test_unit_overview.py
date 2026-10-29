"""Read-only unit overview (Guuto / Urur / section pages): counts once, aggregates for HQ admins. Synthetic data only."""
from django.core.management import call_command

from apps.audit.models import AuditEvent
from apps.organization.models import OrganizationalUnit as OU, UnitType
from apps.personnel.tests.test_personnel import PersonnelBase


class OverviewTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        call_command("apply_army_structure", "--apply", stdout=open("/dev/null", "w"))
        bari = OU.objects.get(code="BARI-ARMY")
        self.urur = OU.objects.create(code="BARI-ARMY-URUR1", name_en="Urur 1", level="unit", parent=bari, unit_type=UnitType.objects.get(code="URUR"))
        self.sec = OU.objects.create(code="BARI-ARMY-URUR1-OPS", name_en="Operations", level="unit", parent=self.urur)
        self.sec2 = OU.objects.create(code="BARI-ARMY-URUR1-ADM", name_en="Admin", level="unit", parent=self.urur)
        self.person("BARI-ARMY-URUR1", "Direct One")
        self.person("BARI-ARMY-URUR1-OPS", "Ops One")
        self.person("BARI-ARMY-URUR1-OPS", "Ops Two")
        self.person("BARI-ARMY-URUR1-ADM", "Admin One")
        gone = self.person("BARI-ARMY-URUR1-ADM", "Retired One")
        gone.status = "retired"
        gone.save()
        self.hq = self.client_for(self.make_user("hqadm", "hq_admin"))

    def get(self, unit, client=None):
        return (client or self.hq).get(f"/api/v1/organization/units/{unit.pk}/overview/")

    def test_totals_count_each_person_once_and_skip_people_no_longer_serving(self):
        r = self.get(self.urur)
        self.assertEqual(r.status_code, 200, r.content)
        s = r.json()["strength"]
        self.assertEqual((s["direct"], s["total"]), (1, 4))
        kids = {c["code"]: (c["direct"], c["total"]) for c in r.json()["children"]}
        self.assertEqual(kids, {"BARI-ARMY-URUR1-ADM": (1, 1), "BARI-ARMY-URUR1-OPS": (2, 2)})
        self.assertEqual(s["direct"] + sum(t for _, t in kids.values()), s["total"])

    def test_parent_total_includes_everything_below_once(self):
        self.assertEqual(self.get(OU.objects.get(code="BARI-ARMY")).json()["strength"]["total"], 4)

    def test_overview_is_audited_and_returns_a_breadcrumb(self):
        r = self.get(self.sec)
        self.assertEqual(r.json()["breadcrumb"][-1]["code"], "BARI-ARMY-URUR1")
        self.assertTrue(AuditEvent.objects.filter(action="org_unit.overview_view").exists())

    def test_a_role_that_may_not_count_people_sees_zero_and_no_names(self):
        auditor = self.client_for(self.make_user("aud2", "auditor"))
        r = self.get(self.urur, client=auditor)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["strength"]["total"], r.json()["counts_complete"]), (0, False))

    def test_out_of_scope_units_are_not_found(self):
        other = self.client_for(self.make_user("nug", "regional_chief", unit="NUGAAL"))
        self.assertEqual(self.get(self.urur, client=other).status_code, 404)

    def test_members_of_a_section_are_listed_for_hq_admins_only_with_narrow_fields(self):
        r = self.get(self.sec)
        names = sorted(m["full_name"] for m in r.json()["members"])
        self.assertEqual(names, ["Ops One", "Ops Two"])
        self.assertEqual(set(r.json()["members"][0]), {"id", "full_name", "rank", "service_number", "status"})
        auditor = self.client_for(self.make_user("aud3", "auditor"))
        self.assertEqual(self.get(self.sec, client=auditor).json()["members"], [])
