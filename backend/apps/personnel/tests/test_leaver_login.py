"""Retirement or discharge ends the person's login (the link to the record is kept); other status changes do not."""
from apps.accounts import access_review
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.organization.tests.test_change_requests import Base as ChangeRequestBase
from apps.personnel.models import Personnel

from .test_personnel import URL, PersonnelBase


class DirectStatusChangeTests(PersonnelBase):
    def linked(self, name="Soldier Login", username="sol.login", role="read_only", unit="HQ"):
        person = self.person("BARI-ARMY-A", name)
        user = self.make_user(username, role, unit=unit)
        Personnel.objects.filter(pk=person.pk).update(account=user)
        return Personnel.objects.get(pk=person.pk), user

    def change(self, person, status):
        return self.manager().post(f"{URL}{person.pk}/change-status/", {"status": status, "version": person.version}, format="json")

    def test_retiring_closes_the_login_signs_it_out_and_keeps_the_link(self):
        person, user = self.linked()
        uc = self.client_for(user)
        self.assertEqual(uc.get("/api/v1/ranks/").status_code, 200)
        self.assertEqual(self.change(person, "retired").status_code, 200)
        self.assertFalse(User.objects.get(pk=user.pk).is_active)
        self.assertEqual(uc.get("/api/v1/ranks/").status_code, 403)  # live session is gone
        self.assertEqual(Personnel.objects.get(pk=person.pk).account_id, user.pk)
        e = AuditEvent.objects.get(action="personnel.account_closed")
        self.assertEqual((e.outcome, e.metadata["result"], e.metadata["reason"]), ("success", "closed", "retired"))

    def test_discharge_closes_it_too(self):
        person, user = self.linked("Other Soldier", "other.sol")
        self.assertEqual(self.change(person, "discharged").status_code, 200)
        self.assertFalse(User.objects.get(pk=user.pk).is_active)

    def test_leave_and_suspension_do_not_close_the_login(self):
        person, user = self.linked("Leave Soldier", "leave.sol")
        self.assertEqual(self.change(person, "on_leave").status_code, 200)
        person = Personnel.objects.get(pk=person.pk)
        self.assertEqual(self.change(person, "suspended").status_code, 200)
        self.assertTrue(User.objects.get(pk=user.pk).is_active)
        self.assertFalse(AuditEvent.objects.filter(action="personnel.account_closed").exists())

    def test_person_without_a_login_is_unaffected(self):
        person = self.person("BARI-ARMY-A", "No Login")
        self.assertEqual(self.change(person, "retired").status_code, 200)
        self.assertFalse(AuditEvent.objects.filter(action__startswith="personnel.account_clos").exists())

    def test_the_only_user_administrator_is_not_locked_out_and_the_review_flags_it(self):
        person, admin = self.linked("Admin Person", "only.admin", role="hq_admin")
        self.assertEqual(self.change(person, "retired").status_code, 200)  # the status change itself still goes through
        self.assertTrue(User.objects.get(pk=admin.pk).is_active)
        e = AuditEvent.objects.get(action="personnel.account_close_blocked")
        self.assertEqual((e.outcome, e.metadata["result"]), ("denied", "blocked_last_admin"))
        flagged = access_review.review()["findings"]["leaver_active"]
        self.assertIn("only.admin: retired", flagged["items"])

    def test_an_administrator_is_closed_when_another_administrator_exists(self):
        self.make_user("second.admin", "hq_admin")
        person, admin = self.linked("Admin Two", "first.admin", role="hq_admin")
        self.assertEqual(self.change(person, "discharged").status_code, 200)
        self.assertFalse(User.objects.get(pk=admin.pk).is_active)


class ApprovedChangeRequestTests(ChangeRequestBase):
    def test_approved_retirement_closes_the_login(self):
        user = self.make_user("cr.soldier", "read_only")
        Personnel.objects.filter(pk=self.person_a.pk).update(account=user)
        body = {"kind": "status_change", "order_ref": "Order 90/2026", "issuing_officer": "Col. Example", "order_date": "2026-10-01",
                "payload": {"personnel": str(self.person_a.pk), "status": "retired", "effective_date": "2026-10-02", "reason": "Retired"}}
        row = self.hq.post("/api/v1/organization/change-requests/", body, format="json").json()
        self.assertEqual(self.act(row, "approve").status_code, 200)
        self.assertFalse(User.objects.get(pk=user.pk).is_active)
        self.assertTrue(AuditEvent.objects.filter(action="personnel.account_closed").exists())
