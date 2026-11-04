"""A new person is suggested the unit that fits their specialty: a medic a medical unit, never a general one. Advice only."""
from django.core.management import call_command

from apps.core.testing import BaseApiTest
from apps.organization import placement_hints as hints

URL = "/api/v1/organization/units/suggest/"


class SuggestionTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        call_command("apply_army_structure", "--apply", verbosity=0)
        self.client_hq = self.client_for(self.make_user("sug_hq", "hq_reporting"))
        self.bari = self.unit("BARI")

    def get(self, client=None, **params):
        return (client or self.client_hq).get(URL, params)

    def codes(self, r):
        return [u["code"] for u in r.data["suggestions"]]

    def test_a_medic_is_suggested_medical_units_only(self):
        r = self.get(specialty="medical", under=str(self.bari.pk))
        self.assertEqual(r.status_code, 200)
        codes = self.codes(r)
        self.assertIn("BARI-ARMY-HEALTH", codes)
        self.assertNotIn("BARI-ARMY", codes)       # the regional command is a general unit
        self.assertNotIn("BARI-ARMY-G1", codes)    # so is a Guuto
        self.assertNotIn("BARI-ARMY-FIN", codes)   # and another trade's unit
        functions, _ = hints.unit_functions()
        for u in r.data["suggestions"]:
            self.assertEqual(functions[self.unit(u["code"]).pk], "medical", u["code"])

    def test_a_finance_clerk_is_suggested_the_finance_department(self):
        codes = self.codes(self.get(specialty="finance", under=str(self.bari.pk)))
        self.assertIn("BARI-ARMY-FIN", codes)
        self.assertNotIn("BARI-ARMY-HEALTH", codes)

    def test_infantry_are_suggested_line_units_and_not_specialist_units(self):
        codes = self.codes(self.get(specialty="infantry", under=str(self.bari.pk)))
        self.assertIn("BARI-ARMY-G1", codes)
        self.assertNotIn("BARI-ARMY-HEALTH", codes)
        self.assertNotIn("BARI-ARMY-FIN", codes)

    def test_a_chosen_unit_is_judged(self):
        def chosen(code, specialty):
            return self.get(specialty=specialty, unit=str(self.unit(code).pk)).data["chosen"]["fit"]
        self.assertEqual(chosen("BARI-ARMY-HEALTH", "medical"), "match")
        self.assertEqual(chosen("BARI-ARMY-HEALTH", "infantry"), "mismatch")   # a medical unit is not for a soldier
        self.assertEqual(chosen("BARI-ARMY-FIN", "medical"), "mismatch")
        self.assertEqual(chosen("BARI-ARMY", "medical"), "general")            # a general unit is not a medical unit
        self.assertEqual(chosen("BARI-ARMY-G1", "infantry"), "match")

    def test_units_below_a_specialist_unit_inherit_its_function(self):
        functions, _ = hints.unit_functions()
        child = self.unit("BARI-ARMY-HEALTH")
        from apps.organization.models import OrganizationalUnit as OU
        sub = OU.objects.create(code="BARI-ARMY-HEALTH-WARD", name_en="Ward 1", level="unit", parent=child, branch=child.branch)
        self.assertEqual(hints.unit_functions()[0][sub.pk], "medical")
        self.assertEqual(functions[child.pk], "medical")

    def test_an_unknown_specialty_is_refused(self):
        self.assertEqual(self.get(specialty="pilot").status_code, 400)
        self.assertEqual(self.client_hq.get(URL).status_code, 400)

    def test_people_only_get_units_they_can_see(self):
        nugaal_chief = self.client_for(self.make_user("sug_nu", "regional_chief", unit="NUGAAL"))
        r = self.get(nugaal_chief, specialty="medical")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["suggestions"])
        self.assertTrue(all(c.startswith("NUGAAL") for c in self.codes(r)))
        self.assertEqual(self.codes(self.get(nugaal_chief, specialty="medical", under=str(self.bari.pk))), [])

    def test_a_user_without_org_view_is_refused(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(URL, {"specialty": "medical"}).status_code, 403)


class FunctionDetectionTests(BaseApiTest):
    def test_function_is_read_from_the_type_then_the_words(self):
        row = lambda **k: {"code": "X", "name_en": "", "name_so": "", "unit_type__code": None, **k}
        self.assertEqual(hints._own_function(row(unit_type__code="KOOX_MED")), "medical")
        self.assertEqual(hints._own_function(row(name_en="Transport Directorate")), "transport")
        self.assertEqual(hints._own_function(row(name_so="Hogganka Isgaarsiinta")), "communications")
        self.assertIsNone(hints._own_function(row(name_en="Guuto 1 (Brigade 1, Bari)")))

    def test_every_specialty_has_both_labels(self):
        for code, (en, so) in hints.SPECIALTIES.items():
            self.assertTrue(en and so, code)
