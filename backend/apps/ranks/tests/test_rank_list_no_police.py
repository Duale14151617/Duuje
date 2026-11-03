"""The Police service is gone from this build: its ranks never appear in the rank list. Synthetic data only."""
from apps.core.testing import BaseApiTest
from apps.organization.models import ServiceBranch
from apps.ranks.models import Rank

URL = "/api/v1/ranks/"


class RankListHidesPoliceTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("rankview", "super_admin"))
        police, _ = ServiceBranch.objects.get_or_create(code="POLICE", defaults={"name_en": "Police", "name_so": "Booliis"})
        Rank.objects.get_or_create(branch=police, code="P-1", defaults={"category": "inspector", "name_en": "Inspector", "sort_order": 1})

    def test_police_ranks_are_not_listed_but_army_ranks_are(self):
        r = self.admin.get(URL + "?page_size=100")
        self.assertEqual(r.status_code, 200, r.content)
        branches = {x["branch"] for x in r.json()["results"]}
        self.assertNotIn(str(ServiceBranch.objects.get(code="POLICE").pk), branches)
        self.assertIn(str(ServiceBranch.objects.get(code="ARMY").pk), branches)

    def test_police_ranks_are_not_kept_when_filtered_by_branch(self):
        pk = ServiceBranch.objects.get(code="POLICE").pk
        r = self.admin.get(URL + f"?branch={pk}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["results"], [])
