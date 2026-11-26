import unittest

from django.conf import settings

if not settings.CUSTODY_ENABLED:  # custody is switched off for now; set CUSTODY_ENABLED=1 to run these tests
    raise unittest.SkipTest("custody is switched off (CUSTODY_ENABLED=0)")

"""Work-area head roles: each sees and does only its own area. Synthetic data only."""
from apps.detention.tests.test_custody_units import FAC, OVR, UnitBase
from apps.detention.tests.test_detention import URL


class HeadRoleTests(UnitBase):
    def setUp(self):
        super().setUp()
        self.lead = self.client_for(self.make_user("cust_lead", "custody_commander", unit="BARI-ARMY"))
        self.ministry = self.client_for(self.make_user("min_view", "ministry_viewer", unit="HQ"))

    def test_the_custody_lead_runs_custody_in_scope(self):
        self.assertEqual(self.lead.get(URL).status_code, 200)
        self.assertEqual(self.lead.get(OVR).status_code, 200)
        r = self.make()
        self.assertEqual(self.lead.get(f"{URL}{r['id']}/").status_code, 200)
        self.assertEqual(self.lead.post(URL, {"org_unit": str(self.unit_a.pk), "detainee_name": "Lead booking", "reason": "Test ground"}, format="json").status_code, 201)

    def test_the_custody_lead_does_not_see_other_regions(self):
        r = self.make(c=self.nugaal, unit=self.unit_b)
        self.assertEqual(self.lead.get(f"{URL}{r['id']}/").status_code, 404)


    def test_the_ministry_viewer_reads_custody_but_changes_nothing(self):
        self.make()
        self.assertEqual(self.ministry.get(URL).status_code, 200)
        self.assertEqual(self.ministry.post(URL, {"org_unit": str(self.unit_a.pk), "detainee_name": "X", "reason": "Y"}, format="json").status_code, 403)
