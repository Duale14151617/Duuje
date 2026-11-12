from datetime import timedelta
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import RoleAssignment, User
from apps.accounts.services import generate_temp_password
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase

U = "/api/v1/users/"
STRONG = "Abcdefghijk-123"


def csv_file(*lines, name="users.csv"):
    return SimpleUploadedFile(name, ("\n".join(lines) + "\n").encode(), content_type="text/csv")


class TempPasswordTests(PersonnelBase):
    def test_generator_makes_distinct_valid_passwords(self):
        seen = {generate_temp_password() for _ in range(30)}
        self.assertEqual(len(seen), 30)
        for pw in seen:
            self.assertGreaterEqual(len(pw), 12)
            self.assertTrue(any(c.isdigit() for c in pw) and any(c.islower() for c in pw) and any(c.isupper() for c in pw))
            self.assertFalse(set(pw) & set("ilIL0Oo1"))  # no look-alike characters

    def test_blank_password_generates_one_returned_once_and_it_works(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        r = c.post(U, {"username": "ali.warsame", "full_name": "Ali Warsame"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        pw = r.data["temporary_password"]
        self.assertTrue(r.data["must_change_password"])
        self.assertIsNotNone(r.data["temp_password_expires_at"])
        self.assertNotIn("temporary_password", c.get(f"{U}{r.data['id']}/").json())
        self.assertEqual(self.login(APIClient(), "ali.warsame", pw).status_code, 200)

    def test_typed_password_is_not_echoed_back(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        r = c.post(U, {"username": "typed.one", "full_name": "Typed One", "initial_password": STRONG}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("temporary_password", r.data)
        self.assertIsNotNone(r.data["temp_password_expires_at"])

    @override_settings(TEMP_PASSWORD_DAYS=3)
    def test_expiry_uses_the_configured_days(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        r = c.post(U, {"username": "three.days", "full_name": "Three Days"}, format="json")
        left = User.objects.get(username="three.days").temp_password_expires_at - timezone.now()
        self.assertTrue(timedelta(days=2, hours=23) < left <= timedelta(days=3))

    def test_expired_temporary_password_cannot_sign_in_and_reset_fixes_it(self):
        adm = self.client_for(self.make_user("adm", "hq_admin"))
        r = adm.post(U, {"username": "late.user", "full_name": "Late User"}, format="json")
        pw = r.data["temporary_password"]
        User.objects.filter(username="late.user").update(temp_password_expires_at=timezone.now() - timedelta(minutes=1))
        denied = self.login(APIClient(), "late.user", pw)
        self.assertEqual((denied.status_code, denied.data["code"]), (401, "temporary_password_expired"))
        self.assertTrue(AuditEvent.objects.filter(action="auth.login", outcome="denied").exists())
        fresh = adm.post(f"{U}{r.data['id']}/reset-password/", {}, format="json")
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(self.login(APIClient(), "late.user", fresh.data["temporary_password"]).status_code, 200)

    def test_wrong_password_on_expired_account_looks_like_any_wrong_password(self):
        self.make_user("old.temp", "read_only", must_change_password=True,
                       temp_password_expires_at=timezone.now() - timedelta(days=1))
        r = self.login(APIClient(), "old.temp", "wrong-password-123")
        self.assertEqual(r.data["code"], "invalid_credentials")

    def test_changing_password_clears_the_deadline(self):
        self.make_user("newbie", "read_only", must_change_password=True, temp_password_expires_at=timezone.now() + timedelta(days=2))
        c = APIClient()
        self.login(c, "newbie")
        ok = c.post("/api/v1/auth/password/change/", {"current_password": PASSWORD, "new_password": "Another-Strong-Pass-77"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertIsNone(User.objects.get(username="newbie").temp_password_expires_at)

    def test_reset_password_typed_still_returns_204(self):
        adm = self.client_for(self.make_user("adm", "hq_admin"))
        victim = self.make_user("victim", "read_only")
        r = adm.post(f"{U}{victim.pk}/reset-password/", {"temporary_password": STRONG}, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertIsNotNone(User.objects.get(pk=victim.pk).temp_password_expires_at)


class BulkCreateTests(PersonnelBase):
    HEADER = "full_name,username,email,role,unit,branch,service_number,language"

    def post(self, client, file, dry_run="true"):
        return client.post(f"{U}bulk/", {"file": file, "dry_run": dry_run}, format="multipart")

    def admin(self):
        return self.client_for(self.make_user("adm", "hq_admin"))

    def test_preview_writes_nothing_and_commit_creates_accounts_roles_and_links(self):
        p = self.person("BARI-ARMY-A", "Cabdi Nuur", service_number="A-100")
        c = self.admin()
        lines = (self.HEADER,
                 "Cabdi Nuur,,,read_only,BARI-ARMY-A,,A-100,so",
                 "Ali Warsame,,ali@example.com,read_only,HQ,,,en",
                 "Ali Warsame,,,read_only,HQ,,,")
        before = User.objects.count()
        r = self.post(c, csv_file(*lines))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["can_commit"])
        self.assertEqual([x["username"] for x in r.data["rows"]], ["cabdi.nuur", "ali.warsame", "ali.warsame2"])
        self.assertEqual(User.objects.count(), before)
        r = self.post(c, csv_file(*lines), "false")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([x["username"] for x in r.data["created"]], ["cabdi.nuur", "ali.warsame", "ali.warsame2"])
        self.assertEqual(len({x["temporary_password"] for x in r.data["created"]}), 3)
        u = User.objects.get(username="cabdi.nuur")
        self.assertTrue(u.must_change_password)
        self.assertIsNotNone(u.temp_password_expires_at)
        self.assertEqual(Personnel.objects.get(pk=p.pk).account_id, u.pk)
        self.assertTrue(RoleAssignment.objects.filter(user=u, role__code="read_only", org_unit__code="BARI-ARMY-A").exists())
        self.assertEqual(User.objects.get(username="ali.warsame").email, "ali@example.com")
        first = r.data["created"][0]
        self.assertEqual(self.login(APIClient(), first["username"], first["temporary_password"]).status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(action="user.create", metadata__via="bulk").count(), 3)

    def test_any_bad_row_blocks_the_whole_file(self):
        self.person("BARI-ARMY-A", "Linked Person", service_number="A-200")
        c = self.admin()
        taken = self.make_user("taken.name", "read_only")
        lines = (self.HEADER,
                 "Good Row,,,read_only,HQ,,,",
                 "Bad Role,,,no_such_role,HQ,,,",
                 "Bad Unit,,,read_only,NOWHERE,,,",
                 "Taken Name,taken.name,,read_only,HQ,,,",
                 "Upper Case,Upper.Case,,read_only,HQ,,,",
                 "Bad Mail,,not-an-email,read_only,HQ,,,",
                 "Ghost,,,read_only,HQ,,Z-999,",
                 "Super,,,super_admin,HQ,,,")
        before = User.objects.count()
        r = self.post(c, csv_file(*lines))
        self.assertFalse(r.data["can_commit"])
        errs = {x["row"]: x["errors"] for x in r.data["rows"]}
        self.assertEqual(errs[2], [])
        self.assertIn("role_unknown", errs[3])
        self.assertIn("unit_unknown", errs[4])
        self.assertIn("username_taken", errs[5])
        self.assertIn("invalid_username", errs[6])
        self.assertIn("email_invalid", errs[7])
        self.assertIn("person_unknown", errs[8])
        self.assertIn("role_exceeds_authority", errs[9])
        r = self.post(c, csv_file(*lines), "false")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(User.objects.count(), before)

    def test_person_already_linked_or_duplicated_in_file_is_refused(self):
        p = self.person("BARI-ARMY-A", "Has Login", service_number="A-300")
        Personnel.objects.filter(pk=p.pk).update(account=self.make_user("has.login", "read_only"))
        self.person("BARI-ARMY-A", "Twice Listed", service_number="A-301")
        c = self.admin()
        r = self.post(c, csv_file(self.HEADER, "Has Login,,,read_only,HQ,,A-300,",
                                  "Twice Listed,,,read_only,HQ,,A-301,", "Twice Listed,tw.two,,read_only,HQ,,A-301,"))
        errs = {x["row"]: x["errors"] for x in r.data["rows"]}
        self.assertIn("person_already_linked", errs[2])
        self.assertEqual(errs[3], [])
        self.assertIn("duplicate_row", errs[4])

    def test_file_rules(self):
        c = self.admin()
        self.assertEqual(self.post(c, csv_file("full_name,role", "A B,read_only", name="users.txt")).status_code, 400)
        self.assertEqual(self.post(c, csv_file("name,role,unit", "A B,read_only,HQ")).status_code, 400)
        self.assertEqual(self.post(c, csv_file(self.HEADER)).status_code, 400)
        many = [self.HEADER] + [f"Person{n} Test,,,read_only,HQ,,," for n in range(51)]
        r = self.post(c, csv_file(*many))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(c.post(f"{U}bulk/", {}, format="multipart").status_code, 400)

    def test_only_user_administrators_can_bulk_create(self):
        c = self.client_for(self.make_user("reader", "read_only"))
        before = User.objects.count()
        self.assertEqual(self.post(c, csv_file(self.HEADER, "A B,,,read_only,HQ,,,"), "false").status_code, 403)
        self.assertEqual(User.objects.count(), before)


class CheckEmailCommandTests(PersonnelBase):
    def test_reports_console_backend_as_a_problem(self):
        out, err = StringIO(), StringIO()
        call_command("check_email", stdout=out, stderr=err)
        self.assertIn("Backend:", out.getvalue())
        self.assertIn("EMAIL_VERIFICATION", out.getvalue())

    def test_sends_a_test_message(self):
        from django.core import mail
        out = StringIO()
        call_command("check_email", "someone@example.com", stdout=out, stderr=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["someone@example.com"])
