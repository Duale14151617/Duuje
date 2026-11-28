"""ID cards, official letters and the public QR check."""
import io

from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.issuance.models import IssuedDocument
from apps.personnel import profile as profile_svc
from apps.personnel.tests.test_personnel import PersonnelBase

URL = "/api/v1/credentials/"


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (40, 50), (120, 130, 140)).save(buf, "JPEG")
    return buf.getvalue()


class IssuanceBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.hq = self.client_for(self.make_user("hq_cred", "hq_admin"))
        self.member = self.client_for(self.make_user("member_cred", "member", unit="BARI-ARMY"))
        self.officer = self.person("BARI-ARMY-A", "Cred Officer", service_number="PA-123456")

    def with_photo(self, person=None):
        profile_svc.save_photo(person or self.officer, jpeg())


class IdCardTests(IssuanceBase):
    def test_card_needs_a_photo(self):
        r = self.hq.post(URL + "id-card/", {"personnel": str(self.officer.pk)}, format="json")
        self.assertEqual((r.status_code, self.codes(r, "personnel")), (400, ["photo_required"]))

    def test_issue_and_reissue_revokes_the_old_card(self):
        self.with_photo()
        a = self.hq.post(URL + "id-card/", {"personnel": str(self.officer.pk)}, format="json")
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(len(a.data["code"]), 12)
        self.assertTrue(a.data["verify_url"].endswith("/verify/" + a.data["code"]))
        b = self.hq.post(URL + "id-card/", {"personnel": str(self.officer.pk)}, format="json")
        self.assertEqual(b.status_code, 201)
        old = IssuedDocument.objects.get(pk=a.data["id"])
        self.assertEqual(old.status, "revoked")
        self.assertEqual(IssuedDocument.objects.filter(personnel=self.officer, status="valid").count(), 1)

    def test_member_cannot_issue(self):
        self.with_photo()
        r = self.member.post(URL + "id-card/", {"personnel": str(self.officer.pk)}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_public_check_shows_little_and_hides_service_number(self):
        self.with_photo()
        doc = self.hq.post(URL + "id-card/", {"personnel": str(self.officer.pk)}, format="json").data
        r = APIClient().get(f"/api/v1/verify/{doc['code']}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["state"], "valid")
        self.assertEqual(r.data["full_name"], "Cred Officer")
        self.assertTrue(r.data["service_number"].endswith("456") and "PA-" not in r.data["service_number"])
        for key in ("photo", "phone", "date_of_birth", "blood_type"):
            self.assertNotIn(key, r.data)

    def test_unknown_code_is_404_and_revoked_shows_only_the_state(self):
        self.assertEqual(APIClient().get("/api/v1/verify/AAAAAAAAAAAA/").status_code, 404)
        self.with_photo()
        doc = self.hq.post(URL + "id-card/", {"personnel": str(self.officer.pk)}, format="json").data
        r = self.hq.post(f"{URL}{doc['id']}/revoke/", {"reason": "Lost card"}, format="json")
        self.assertEqual(r.status_code, 200)
        pub = APIClient().get(f"/api/v1/verify/{doc['code']}/").data
        self.assertEqual(pub["state"], "revoked")
        self.assertNotIn("full_name", pub)

    def test_a_leaver_card_stops_verifying(self):
        self.with_photo()
        doc = self.hq.post(URL + "id-card/", {"personnel": str(self.officer.pk)}, format="json").data
        type(self.officer).objects.filter(pk=self.officer.pk).update(status="retired")
        self.assertEqual(APIClient().get(f"/api/v1/verify/{doc['code']}/").data["state"], "not_serving")


class LetterTests(IssuanceBase):
    def test_issue_letter_and_public_check_has_fingerprint(self):
        body = {"org_unit": str(self.unit("BARI-ARMY-A").pk), "subject": "Transfer notice", "body": "Please receive the bearer.",
                "recipient": "Commander, Bari", "signed_title": "Chief of Staff"}
        r = self.hq.post(URL + "letter/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["fingerprint"]), 10)
        pub = APIClient().get(f"/api/v1/verify/{r.data['code']}/").data
        self.assertEqual((pub["state"], pub["subject"], pub["fingerprint"]), ("valid", "Transfer notice", r.data["fingerprint"]))
        self.assertNotIn("body", pub)

    def test_letter_needs_subject_and_text(self):
        unit = str(self.unit("BARI-ARMY-A").pk)
        self.assertEqual(self.hq.post(URL + "letter/", {"org_unit": unit, "subject": "", "body": "x"}, format="json").status_code, 400)
        self.assertEqual(self.hq.post(URL + "letter/", {"org_unit": unit, "subject": "x", "body": ""}, format="json").status_code, 400)

    def test_list_is_scoped_and_audited(self):
        unit = str(self.unit("BARI-ARMY-A").pk)
        self.hq.post(URL + "letter/", {"org_unit": unit, "subject": "A", "body": "b"}, format="json")
        r = self.hq.get(URL)
        self.assertEqual((r.status_code, len(r.data["results"])), (200, 1))
        self.assertEqual(self.member.get(URL).status_code, 403)
