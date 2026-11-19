"""Work-area head roles: each sees and does only its own area. Synthetic data only."""
from apps.detention.tests.test_custody_units import FAC, OVR, UnitBase
from apps.detention.tests.test_detention import URL


class HeadRoleTests(UnitBase):
    def setUp(self):
        super().setUp()
        self.lead = self.client_for(self.make_user("cust_lead", "custody_commander", unit="BARI-ARMY"))
        self.taxhead = self.client_for(self.make_user("tax_head1", "tax_head", unit="HQ"))
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

    def test_the_tax_head_has_no_custody_access(self):
        self.assertEqual(self.taxhead.get(URL).status_code, 403)

    def test_the_ministry_viewer_reads_custody_but_changes_nothing(self):
        self.make()
        self.assertEqual(self.ministry.get(URL).status_code, 200)
        self.assertEqual(self.ministry.post(URL, {"org_unit": str(self.unit_a.pk), "detainee_name": "X", "reason": "Y"}, format="json").status_code, 403)
