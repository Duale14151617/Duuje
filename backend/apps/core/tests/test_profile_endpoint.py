from django.test import TestCase, override_settings


class ProfileEndpointTests(TestCase):
    def test_army_is_the_default_and_the_endpoint_is_public(self):
        r = self.client.get("/api/v1/profile/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["profile"], "army")
        self.assertEqual((r.json()["name_en"], r.json()["short_name"]), ("Puntland Defence Forces HQ", "ARMY HQ"))

    @override_settings(ARMYHQ_PROFILE="police")
    def test_the_police_deployment_reports_its_own_name(self):
        data = self.client.get("/api/v1/profile/").json()
        self.assertEqual((data["profile"], data["name_en"], data["short_name"]), ("police", "Puntland Police Force HQ", "POLICE HQ"))

    @override_settings(ARMYHQ_PROFILE="something-else")
    def test_an_unknown_profile_falls_back_to_the_army_names(self):
        self.assertEqual(self.client.get("/api/v1/profile/").json()["name_en"], "Puntland Defence Forces HQ")
