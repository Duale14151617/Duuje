"""Break-glass override of the different-person payroll rules. Synthetic data only."""
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.payroll.models import SalaryProfile
from apps.payroll.tests.test_payroll import P, PayrollBase

REASON = "Approver unreachable, month-end salaries due today"


class BreakGlassTests(PayrollBase):
    def setUp(self):
        super().setUp()
        self.boss = self.client_for(self.make_user("boss", "super_admin"))
        pid = self.profile(c=self.boss).json()["id"]
        self.pid = pid
        self.url = f"{P}profiles/{pid}/approve/"

    def approve(self, **headers):
        return self.boss.post(self.url, {}, format="json", **headers)

    def test_super_admin_cannot_approve_own_work_without_a_reason(self):
        self.assertEqual(self.approve().status_code, 400)
        self.assertEqual(SalaryProfile.objects.get(pk=self.pid).status, "pending")

    def test_a_short_reason_is_not_enough(self):
        self.assertEqual(self.approve(HTTP_X_OVERRIDE_REASON="urgent").status_code, 400)
        self.assertEqual(SalaryProfile.objects.get(pk=self.pid).status, "pending")

    def test_override_with_a_reason_works_and_is_audited(self):
        self.assertEqual(self.approve(HTTP_X_OVERRIDE_REASON=REASON).status_code, 200)
        self.assertEqual(SalaryProfile.objects.get(pk=self.pid).status, "approved")
        ev = AuditEvent.objects.get(action="breakglass.override")
        self.assertEqual((ev.actor_username, ev.metadata["check"], ev.metadata["reason"]), ("boss", "profile_approver", REASON))

    def test_the_reason_does_not_leak_into_the_next_request(self):
        self.approve(HTTP_X_OVERRIDE_REASON=REASON)
        pid2 = self.profile(c=self.boss, eff="2026-02-01").json()["id"]
        self.assertEqual(self.boss.post(f"{P}profiles/{pid2}/approve/", {}, format="json").status_code, 400)

    @override_settings(BREAK_GLASS_ENABLED=False)
    def test_switch_off_disables_the_override(self):
        self.assertEqual(self.approve(HTTP_X_OVERRIDE_REASON=REASON).status_code, 400)
        self.assertFalse(AuditEvent.objects.filter(action="breakglass.override").exists())

    def test_other_rules_still_apply_under_override(self):
        self.assertEqual(self.approve(HTTP_X_OVERRIDE_REASON=REASON).status_code, 200)
        # already approved: the state rule is not overridden
        self.assertEqual(self.approve(HTTP_X_OVERRIDE_REASON=REASON).status_code, 409)


class AuditorPayrollAccessTests(PayrollBase):
    def test_auditor_can_read_payroll_but_never_act(self):
        aud = self.client_for(self.make_user("aud2", "auditor"))
        pid = self.profile().json()["id"]
        self.assertEqual(aud.get(f"{P}profiles/").status_code, 200)
        self.assertEqual(aud.post(f"{P}profiles/{pid}/approve/", {}, format="json").status_code, 403)
        self.assertEqual(aud.post(f"{P}profiles/", {}, format="json").status_code, 403)
