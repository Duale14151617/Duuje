"""The signed-in user's avatar: a thumbnail of the official photo on their linked personnel record."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import UserAvatar
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.personnel import profile as profile_svc
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase

ME = "/api/v1/auth/me/"
PHOTO = "/api/v1/auth/me/photo/"


def _upload():
    buf = BytesIO()
    Image.new("RGB", (800, 1000), (30, 60, 120)).save(buf, "PNG")
    return SimpleUploadedFile("p.png", buf.getvalue(), content_type="image/png")


class MyPhotoTests(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("avatar.user", "member", unit="BARI-ARMY-A")
        self.person_row = self.person("BARI-ARMY-A", "Avatar Person")
        self.client = self.client_for(self.user)

    def link(self):
        Personnel.objects.filter(pk=self.person_row.pk).update(account_id=self.user.pk)

    def test_no_linked_record_means_no_avatar(self):
        self.assertIsNone(self.client.get(ME).json()["photo_v"])
        self.assertEqual(self.client.get(PHOTO).status_code, 404)

    def test_linked_record_without_photo_is_404(self):
        self.link()
        self.assertIsNone(self.client.get(ME).json()["photo_v"])
        self.assertEqual(self.client.get(PHOTO).status_code, 404)

    def test_thumbnail_is_small_private_and_versioned(self):
        self.link()
        profile_svc.save_photo(self.person_row, profile_svc.process_photo(_upload()))
        self.assertIsNotNone(self.client.get(ME).json()["photo_v"])
        r = self.client.get(PHOTO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertIn("private", r["Cache-Control"])
        img = Image.open(BytesIO(r.content))
        self.assertEqual(img.size, profile_svc.AVATAR_SIZE)

    def test_a_user_only_ever_gets_their_own_photo(self):
        other = self.person("BARI-ARMY-A", "Someone Else")
        profile_svc.save_photo(other, profile_svc.process_photo(_upload()))
        self.link()  # linked to a person WITHOUT a photo; the other person's photo must not leak
        self.assertEqual(self.client.get(PHOTO).status_code, 404)

    def test_requires_sign_in(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(PHOTO).status_code, (401, 403))


class AdminAvatarTests(BaseApiTest):
    """HQ administrators and super administrators set account pictures; nobody else does; HQ admins cannot touch a super admin's."""

    def setUp(self):
        super().setUp()
        self.sa = self.make_user("boss", "super_admin")
        self.adm = self.make_user("adm", "hq_admin")
        self.reader = self.make_user("reader", "read_only")
        self.sa_c, self.adm_c, self.reader_c = (self.client_for(u) for u in (self.sa, self.adm, self.reader))

    def up(self, c, user):
        return c.post(f"/api/v1/users/{user.pk}/avatar/upload/", {"photo": _upload()}, format="multipart")

    def test_hq_admin_sets_their_own_and_an_ordinary_users_picture(self):
        for target in (self.adm, self.reader):
            self.assertEqual(self.up(self.adm_c, target).status_code, 200, target.username)
        self.assertEqual(self.adm_c.get(f"/api/v1/users/{self.reader.pk}/avatar/")["Content-Type"], "image/jpeg")
        self.assertTrue(AuditEvent.objects.filter(action="user.avatar_set").exists())

    def test_super_admin_sets_anyones_picture(self):
        for target in (self.sa, self.adm, self.reader):
            self.assertEqual(self.up(self.sa_c, target).status_code, 200, target.username)

    def test_hq_admin_cannot_change_a_super_admins_picture(self):
        self.assertEqual(self.up(self.adm_c, self.sa).status_code, 403)
        self.assertEqual(self.adm_c.post(f"/api/v1/users/{self.sa.pk}/avatar/remove/").status_code, 403)
        self.assertFalse(UserAvatar.objects.filter(pk=self.sa.pk).exists())

    def test_ordinary_users_cannot_set_pictures(self):
        self.assertEqual(self.up(self.reader_c, self.reader).status_code, 403)
        self.assertEqual(self.up(self.reader_c, self.adm).status_code, 403)

    def test_bad_upload_is_refused(self):
        bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        r = self.adm_c.post(f"/api/v1/users/{self.reader.pk}/avatar/upload/", {"photo": bad}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_account_picture_beats_the_personnel_photo_and_remove_restores_it(self):
        self.assertEqual(self.client_for(self.adm).get(ME).json()["photo_v"], None)
        self.up(self.sa_c, self.adm)
        me = self.adm_c.get(ME).json()
        self.assertIsNotNone(me["photo_v"])
        self.assertEqual(self.adm_c.get(PHOTO).status_code, 200)  # an admin with no personnel record now has an avatar
        self.assertEqual(self.sa_c.post(f"/api/v1/users/{self.adm.pk}/avatar/remove/").status_code, 204)
        self.assertEqual(self.adm_c.get(PHOTO).status_code, 404)
        self.assertIsNone(self.adm_c.get(ME).json()["photo_v"])
