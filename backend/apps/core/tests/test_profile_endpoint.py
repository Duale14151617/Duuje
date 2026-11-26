from django.test import TestCase, override_settings


class ProfileEndpointTests(TestCase):
    def test_the_endpoint_is_public_and_reports_the_deployment_name(self):
        r = self.client.get("/api/v1/profile/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["profile"], "army")
        self.assertEqual((r.json()["name_en"], r.json()["short_name"]), ("Puntland Defence Forces HQ", "ARMY HQ"))

    @override_settings(ARMYHQ_PROFILE="something-else")
    def test_an_unknown_profile_falls_back_to_the_army_names(self):
        self.assertEqual(self.client.get("/api/v1/profile/").json()["name_en"], "Puntland Defence Forces HQ")
