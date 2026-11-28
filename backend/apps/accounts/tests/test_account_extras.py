"""Recent activity, password age, new-address notice for every account, and bulk profile pictures."""
import zipfile
from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User, UserAvatar
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, BaseApiTest
from apps.workflows.models import Notification

ME = "/api/v1/auth/me/"


def _png():
    buf = BytesIO()
    Image.new("RGB", (400, 500), (10, 90, 60)).save(buf, "PNG")
    return buf.getvalue()


def _zip(files):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return SimpleUploadedFile("photos.zip", buf.getvalue(), content_type="application/zip")


class ActivityTests(BaseApiTest):
    def test_shows_only_my_own_events_and_marks_admin_actions(self):
        me = self.make_user("walker", "member", mfa=False)
        other = self.make_user("other", "member", mfa=False)
        adm = self.make_user("adm", "hq_admin")
        c = APIClient()
        self.assertEqual(c.post("/api/v1/auth/login/", {"username": "walker", "password": PASSWORD}, format="json").status_code, 200)
        APIClient().post("/api/v1/auth/login/", {"username": "other", "password": PASSWORD}, format="json")
        self.client_for(adm).post(f"/api/v1/users/{me.pk}/avatar/upload/", {"photo": SimpleUploadedFile("p.png", _png(), content_type="image/png")},
                                  format="multipart")
        rows = c.get("/api/v1/auth/activity/").json()["results"]
        actions = [r["action"] for r in rows]
        self.assertIn("auth.login", actions)
        self.assertIn("user.avatar_set", actions)
        self.assertTrue(next(r for r in rows if r["action"] == "user.avatar_set")["by_admin"])
        self.assertFalse(next(r for r in rows if r["action"] == "auth.login")["by_admin"])
        self.assertEqual(AuditEvent.objects.filter(actor_id=other.pk, action="auth.login").count(), 1)  # the other user's login is not in my list
        self.assertEqual(sum(1 for r in rows if r["action"] == "auth.login"), 1)

    def test_requires_sign_in(self):
        self.assertIn(APIClient().get("/api/v1/auth/activity/").status_code, (401, 403))


class PasswordAgeTests(BaseApiTest):
    def _age(self, user, days):
        User.objects.filter(pk=user.pk).update(password_changed_at=timezone.now() - timedelta(days=days))

    def test_off_by_default(self):
        u = self.make_user("walker", "member", mfa=False)
        self._age(u, 4000)
        me = self.client_for(u).get(ME).json()
        self.assertNotIn("password_change", me["restrictions"])
        self.assertIsNone(me["password_expires_at"])

    @override_settings(PASSWORD_MAX_AGE_DAYS=90, PASSWORD_WARN_DAYS=14)
    def test_warns_before_and_forces_change_after(self):
        u = self.make_user("walker", "member", mfa=False)
        self._age(u, 50)
        me = self.client_for(u).get(ME).json()
        self.assertFalse(me["password_warn"])
        self._age(u, 80)
        me = self.client_for(u).get(ME).json()
        self.assertTrue(me["password_warn"])
        self.assertNotIn("password_change", me["restrictions"])
        self._age(u, 95)
        me = self.client_for(u).get(ME).json()
        self.assertIn("password_change", me["restrictions"])

    @override_settings(PASSWORD_MAX_AGE_DAYS=90)
    def test_changing_the_password_restarts_the_clock(self):
        u = self.make_user("walker", "member", mfa=False)
        self._age(u, 95)
        c = self.client_for(u)
        r = c.post("/api/v1/auth/password/change/", {"current_password": PASSWORD, "new_password": "A-brand-new-Passphrase-42"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        me = c.get(ME).json()
        self.assertNotIn("password_change", me["restrictions"])
        self.assertGreater(me["password_days_left"], 80)


class NewAddressTests(BaseApiTest):
    def _login(self, username, ip):
        return APIClient().post("/api/v1/auth/login/", {"username": username, "password": PASSWORD}, format="json", REMOTE_ADDR=ip)

    def test_ordinary_user_is_told_about_a_new_address_but_not_the_first_or_a_repeat(self):
        u = self.make_user("walker", "member", mfa=False)
        self.assertEqual(self._login("walker", "10.0.0.1").status_code, 200)   # first ever sign-in: nothing to compare with
        self.assertFalse(Notification.objects.filter(recipient=u, kind="new_address").exists())
        self._login("walker", "10.0.0.1")                                      # same address again
        self.assertFalse(Notification.objects.filter(recipient=u, kind="new_address").exists())
        self._login("walker", "10.0.0.2")                                      # a new address
        self.assertEqual(Notification.objects.filter(recipient=u, kind="new_address").count(), 1)
        self._login("walker", "10.0.0.2")                                      # now known
        self.assertEqual(Notification.objects.filter(recipient=u, kind="new_address").count(), 1)


class BulkAvatarTests(BaseApiTest):
    URL = "/api/v1/users/avatars/bulk/"

    def setUp(self):
        super().setUp()
        self.adm = self.make_user("adm", "hq_admin")
        self.adm2 = self.make_user("adm2", "hq_admin")
        self.walker = self.make_user("walker", "member", mfa=False)
        self.c = self.client_for(self.adm)

    def _post(self, files, dry=True, client=None):
        return (client or self.c).post(self.URL, {"file": _zip(files), "dry_run": "true" if dry else "false"}, format="multipart")

    def test_preview_reports_each_file_and_changes_nothing(self):
        r = self._post({"walker.png": _png(), "nobody.png": _png(), "adm2.png": _png(), "notes.txt": b"hi", "bad.png": b"not an image", "adm.PNG": _png()})
        self.assertEqual(r.status_code, 200, r.content)
        by = {row["file"]: row["status"] for row in r.json()["rows"]}
        self.assertEqual(by, {"walker.png": "ok", "nobody.png": "unknown_user", "adm2.png": "not_allowed", "notes.txt": "not_image",
                              "bad.png": "unknown_user", "adm.PNG": "ok"})
        self.assertEqual(UserAvatar.objects.count(), 0)

    def test_apply_sets_valid_pictures_and_audits(self):
        r = self._post({"walker.png": _png(), "nobody.png": _png()}, dry=False)
        self.assertEqual(r.json()["applied"], 1)
        self.assertTrue(UserAvatar.objects.filter(user=self.walker).exists())
        self.assertTrue(AuditEvent.objects.filter(action="user.avatar_bulk").exists())

    def test_super_admin_may_set_another_hq_admins_picture(self):
        sa = self.make_user("boss", "super_admin")
        r = self._post({"adm2.png": _png()}, dry=False, client=self.client_for(sa))
        self.assertEqual(r.json()["applied"], 1)

    def test_corrupt_zip_and_ordinary_users_are_refused(self):
        bad = self.c.post(self.URL, {"file": SimpleUploadedFile("x.zip", b"nope"), "dry_run": "true"}, format="multipart")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self._post({"walker.png": _png()}, client=self.client_for(self.walker)).status_code, 403)
