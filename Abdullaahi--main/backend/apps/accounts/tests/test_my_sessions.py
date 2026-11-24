"""Users can see and end their own sign-ins, and only their own."""
from rest_framework.test import APIClient

from apps.core.testing import BaseApiTest

URL = "/api/v1/auth/sessions/"


class MySessionsTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("walker", "read_only", mfa=False)

    def signed_in_twice(self):
        a, b = APIClient(), APIClient()
        for c, ua in ((a, "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"), (b, "Mozilla/5.0 (Linux; Android 13) Chrome/120.0 Mobile")):
            r = c.post("/api/v1/auth/login/", {"username": "walker", "password": "Correct-Horse-Battery-9"}, format="json",
                       HTTP_USER_AGENT=ua)
            self.assertEqual(r.status_code, 200)
        return a, b

    def test_lists_both_sessions_with_the_current_one_first(self):
        a, b = self.signed_in_twice()
        rows = a.get(URL).json()["results"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["current"])
        self.assertIn("Windows", rows[0]["ua"])
        self.assertNotIn("session_key", rows[0])

    def test_end_one_other_session(self):
        a, b = self.signed_in_twice()
        other = [r for r in a.get(URL).json()["results"] if not r["current"]][0]
        self.assertEqual(a.delete(f"{URL}{other['id']}/").status_code, 204)
        self.assertIn(b.get("/api/v1/auth/me/").status_code, (401, 403))  # the other device is signed out

    def test_cannot_end_the_current_session_this_way_and_end_others_keeps_it(self):
        a, b = self.signed_in_twice()
        cur = a.get(URL).json()["results"][0]
        self.assertEqual(a.delete(f"{URL}{cur['id']}/").status_code, 409)
        self.assertEqual(a.post(URL).json()["ended"], 1)
        self.assertEqual(a.get("/api/v1/auth/me/").status_code, 200)

    def test_never_shows_or_ends_another_users_session(self):
        other = self.make_user("other.person", "read_only", mfa=False)
        theirs = self.client_for(other)
        mine = self.client_for(self.user)
        self.assertEqual(len(mine.get(URL).json()["results"]), 1)
        their_id = theirs.get(URL).json()["results"][0]["id"]
        self.assertEqual(mine.delete(f"{URL}{their_id}/").status_code, 404)
