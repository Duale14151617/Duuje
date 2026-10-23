"""Ranks are changeable and swappable. Synthetic data only."""
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.ranks.models import Rank

URL = "/api/v1/ranks/"


@override_settings(POLICE_MODULE_ENABLED=True)
class RankSwapTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("rankmgr", "super_admin"))
        self.pol = {r.code: r for r in Rank.objects.filter(branch__code="POLICE")}
        self.army = Rank.objects.filter(branch__code="ARMY", active=True, approval_status="approved").order_by("sort_order").first()

    def swap(self, c, a, b):
        return c.post(URL + "swap/", {"first": str(a.pk), "second": str(b.pk)}, format="json")

    def test_two_ranks_exchange_positions_and_it_is_audited(self):
        a, b = self.pol["PL-03"], self.pol["PL-04"]
        r = self.swap(self.admin, a, b)
        self.assertEqual(r.status_code, 200, r.content)
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.sort_order, b.sort_order), (4, 3))
        self.assertEqual((a.version, b.version), (2, 2))
        self.assertTrue(AuditEvent.objects.filter(action="rank.swap").exists())

    def test_swapping_back_restores_the_order(self):
        a, b = self.pol["PL-03"], self.pol["PL-04"]
        self.swap(self.admin, a, b), self.swap(self.admin, a, b)
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.sort_order, b.sort_order), (3, 4))

    def test_only_the_same_branch_and_two_different_ranks(self):
        self.assertEqual(self.swap(self.admin, self.pol["PL-03"], self.army).status_code, 409)
        self.assertEqual(self.swap(self.admin, self.pol["PL-03"], self.pol["PL-03"]).status_code, 400)

    def test_needs_the_manage_permission(self):
        reader = self.client_for(self.make_user("reader", "read_only", unit="BARI"))
        self.assertEqual(self.swap(reader, self.pol["PL-03"], self.pol["PL-04"]).status_code, 403)

    def test_a_swap_that_breaks_a_reporting_line_is_refused_and_changes_nothing(self):
        from datetime import date

        from apps.personnel import services as svc
        from apps.organization.models import OrganizationalUnit as OU
        unit = OU.objects.get(code="BARI-POLICE-PERS")
        boss = svc.create_personnel(None, full_name="Boss One", phone="", service_number=None, org_unit=unit,
                                    rank=self.pol["PL-04"], status="active", effective_date=date.today())
        sub = svc.create_personnel(None, full_name="Sub One", phone="", service_number=None, org_unit=unit,
                                   rank=self.pol["PL-03"], status="active", effective_date=date.today())
        from apps.personnel.models import Personnel
        Personnel.objects.filter(pk=sub.pk).update(supervisor=boss)
        r = self.swap(self.admin, self.pol["PL-03"], self.pol["PL-04"])
        self.assertEqual((r.status_code, r.json()["code"]), (409, "breaks_reporting_lines"))
        self.assertEqual(Rank.objects.get(pk=self.pol["PL-03"].pk).sort_order, 3)

    def test_a_rank_can_be_renamed_and_reordered_through_the_normal_edit(self):
        r = self.pol["PL-12"]
        ok = self.admin.patch(f"{URL}{r.pk}/", {"name_en": "Gaashanle Cusub", "name_so": "Gaashanle Cusub", "version": r.version}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(Rank.objects.get(pk=r.pk).approval_status, "draft")  # renaming voids approval: re-approve after review

    def test_any_two_ranks_of_a_branch_can_swap_not_only_neighbours(self):
        a, b = self.pol["PL-02"], self.pol["PL-09"]
        self.assertEqual(self.swap(self.admin, a, b).status_code, 200)
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.sort_order, b.sort_order), (9, 2))

    def test_a_retired_rank_cannot_be_swapped(self):
        r = self.pol["PL-05"]
        Rank.objects.filter(pk=r.pk).update(active=False)
        res = self.swap(self.admin, r, self.pol["PL-06"])
        self.assertEqual((res.status_code, res.json()["code"]), (409, "rank_inactive"))

    def test_code_and_category_are_changeable(self):
        r = self.pol["PL-07"]
        ok = self.admin.patch(f"{URL}{r.pk}/", {"code": "PL-07A", "category": "junior_officer", "version": r.version}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        r.refresh_from_db()
        self.assertEqual((r.code, r.category), ("PL-07A", "junior_officer"))
        clash = self.admin.patch(f"{URL}{self.pol['PL-08'].pk}/", {"code": "PL-07A", "version": 1}, format="json")
        self.assertEqual(clash.status_code, 400)
