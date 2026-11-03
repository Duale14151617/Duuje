from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU

URL = "/api/v1/organization/units/tree/"


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n["children"])


class TreeTests(BaseApiTest):
    def test_headquarters_sees_the_whole_tree_nested(self):
        r = self.client_for(self.make_user("hqr", "hq_reporting")).get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n["code"] for n in r.data["roots"]], ["HQ"])
        codes = {n["code"] for n in walk(r.data["roots"])}
        self.assertTrue({"BARI", "KARKAAR", "NUGAAL", "MUDUG", "BARI-ARMY"} <= codes)
        bari = next(n for n in walk(r.data["roots"]) if n["code"] == "BARI")
        self.assertIn("BARI-ARMY", [c["code"] for c in bari["children"]])

    def test_a_regional_user_only_sees_their_subtree(self):
        r = self.client_for(self.make_user("chief", "regional_chief", unit="BARI")).get(URL)
        self.assertEqual([n["code"] for n in r.data["roots"]], ["BARI"])
        self.assertFalse({n["code"] for n in walk(r.data["roots"])} & {"KARKAAR", "KARKAAR-ARMY", "HQ"})

    def test_inactive_units_are_hidden_unless_asked_for(self):
        OU.objects.filter(code="BARI-NAVY").update(active=False)
        c = self.client_for(self.make_user("hqr", "hq_reporting"))
        self.assertNotIn("BARI-NAVY", {n["code"] for n in walk(c.get(URL).data["roots"])})
        self.assertIn("BARI-NAVY", {n["code"] for n in walk(c.get(URL + "?include_inactive=1").data["roots"])})

    def test_unauthenticated_and_roleless_are_refused(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User
        from apps.core.testing import PASSWORD
        self.assertEqual(APIClient().get(URL).status_code, 403)
        user = User.objects.create_user("norole", password=PASSWORD, full_name="No Role")
        self.assertEqual(self.client_for(user).get(URL).status_code, 403)
