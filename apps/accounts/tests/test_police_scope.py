"""Police module: CID is restricted inside the Police branch, and the whole module can be switched off server-side."""
from datetime import date

from django.test import override_settings

from apps.core.testing import BaseApiTest
from apps.personnel import services as svc
from apps.ranks.models import Rank


@override_settings(POLICE_MODULE_ENABLED=True)
class PoliceScopeTests(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()  # seed_reference_data runs with the Police module ON
        Rank.objects.filter(branch__code="POLICE").update(approval_status="approved")  # draft ranks cannot be assigned
        rank = Rank.objects.get(branch__code="POLICE", code="PL-05")
        for number, name, unit in (("PP-T1", "Police Pers One", "BARI-POLICE-PERS"), ("PP-T2", "Police Cid One", "BARI-POLICE-CID")):
            svc.create_personnel(None, full_name=name, phone="", service_number=number, org_unit=cls.unit_by_code(unit),
                                 rank=rank, status="active", effective_date=date.today())

    @staticmethod
    def unit_by_code(code):
        from apps.organization.models import OrganizationalUnit
        return OrganizationalUnit.objects.get(code=code)

    def numbers(self, client):
        resp = client.get("/api/v1/personnel/")
        self.assertEqual(resp.status_code, 200)
        return {r["service_number"] for r in resp.data["results"]}

    def test_police_ranking_is_the_army_ranking_in_separate_rows(self):
        ranks = list(Rank.objects.filter(branch__code="POLICE", active=True).order_by("sort_order"))
        army = list(Rank.objects.filter(branch__code="ARMY", active=True, approval_status="approved").order_by("sort_order"))
        self.assertEqual(len(ranks), 18)
        self.assertEqual([r.name_en for r in ranks], [r.name_en for r in army])
        self.assertFalse({r.pk for r in ranks} & {r.pk for r in army})
        self.assertTrue(self.unit("BARI-POLICE-CID").restricted)

    def test_cid_records_need_cid_access_not_just_police_membership(self):
        admin = self.client_for(self.make_user("polis", "branch_admin", unit="BARI", branch="POLICE"))
        cid = self.client_for(self.make_user("cidoff", "cid_officer", unit="BARI-POLICE-CID", branch="POLICE"))
        self.assertEqual(self.numbers(admin), {"PP-T1"})   # Police branch admin: no CID records
        self.assertEqual(self.numbers(cid), {"PP-T2"})     # CID officer: CID records only

    def test_police_branch_users_do_not_see_army_records(self):
        admin = self.client_for(self.make_user("polis2", "branch_admin", unit="BARI", branch="POLICE"))
        self.assertTrue(all(n.startswith("PP-") for n in self.numbers(admin)))

    def test_army_roles_are_blocked_from_police_records_but_command_authority_is_not(self):
        army_chief = self.client_for(self.make_user("armychief", "regional_chief", unit="BARI"))   # branch-less regional role
        army_admin = self.client_for(self.make_user("armyadm", "branch_admin", unit="BARI", branch="ARMY"))
        hq_report = self.client_for(self.make_user("hqrep", "hq_reporting"))                       # branch-less HQ role
        president = self.client_for(self.make_user("pres", "command_authority"))
        superadmin = self.client_for(self.make_user("sup", "super_admin"))
        for army in (army_chief, army_admin, hq_report):
            self.assertFalse({n for n in self.numbers(army) if n.startswith("PP-")})
        self.assertEqual(self.numbers(president), {"PP-T1"})            # sees Police, but not CID (no cid.access)
        self.assertEqual(self.numbers(superadmin), {"PP-T1", "PP-T2"})  # owner role holds every permission

    def test_cross_service_search_needs_its_own_permission_and_respects_scope(self):
        president = self.client_for(self.make_user("pres2", "command_authority"))
        resp = president.get("/api/v1/personnel/search/", {"q": "Police"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({r["service_number"] for r in resp.data["results"]}, {"PP-T1"})   # CID hidden: no cid.access
        self.assertEqual(resp.data["counts"], {"POLICE": 1})
        self.assertEqual(president.get("/api/v1/personnel/search/", {"q": "P"}).status_code, 400)   # too short
        no_perm = self.client_for(self.make_user("polis9", "branch_admin", unit="BARI", branch="POLICE"))
        self.assertEqual(no_perm.get("/api/v1/personnel/search/", {"q": "Police"}).status_code, 403)
        sup = self.client_for(self.make_user("sup2", "super_admin"))
        self.assertEqual({r["service_number"] for r in sup.get("/api/v1/personnel/search/", {"q": "Police"}).data["results"]},
                         {"PP-T1", "PP-T2"})

    def test_super_admin_reaches_everything_even_with_the_police_module_off(self):
        sup = self.client_for(self.make_user("sup3", "super_admin"))
        admin = self.client_for(self.make_user("polis4", "branch_admin", unit="BARI", branch="POLICE"))
        with override_settings(POLICE_MODULE_ENABLED=False):
            self.assertEqual(self.numbers(sup), {"PP-T1", "PP-T2"})  # maintenance override: nothing is out of reach
            self.assertEqual(self.numbers(admin), set())              # every other role still obeys the switch

    def test_switching_the_module_off_hides_police_records_server_side(self):
        admin = self.client_for(self.make_user("polis3", "branch_admin", unit="BARI", branch="POLICE"))
        self.assertEqual(self.numbers(admin), {"PP-T1"})
        with override_settings(POLICE_MODULE_ENABLED=False):
            self.assertEqual(self.numbers(admin), set())
