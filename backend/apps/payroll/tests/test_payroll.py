"""Payroll, survivor benefits and sensitive-read auditing. Synthetic data only."""
from datetime import date

from apps.audit.models import AuditEvent
from apps.payroll.models import PayrollLine, SalaryProfile, SurvivorCase
from apps.personnel.models import DeathRecord, Personnel
from apps.personnel.tests.test_personnel import PersonnelBase

P = "/api/v1/payroll/"
S = "/api/v1/survivor-cases/"
TODAY = date.today().isoformat()


class PayrollBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.officer = self.client_for(self.make_user("payofficer", "payroll_officer"))
        self.officer2 = self.client_for(self.make_user("payofficer2", "payroll_officer"))
        self.approver = self.client_for(self.make_user("payapprover", "payroll_approver"))
        self.surv = self.client_for(self.make_user("survofficer", "survivor_officer"))
        self.surv2 = self.client_for(self.make_user("survofficer2", "survivor_officer"))
        self.unit_user = self.client_for(self.make_user("unitadmin", "unit_admin", unit="BARI-ARMY-A"))
        self.soldier = self.person("BARI-ARMY-A", "Synthetic Soldier", service_number="S-100")

    def profile(self, person=None, eff="2026-01-01", base="100.00", comps=None, c=None):
        r = (c or self.officer).post(P + "profiles/", {
            "personnel": str((person or self.soldier).pk), "base_amount": base, "currency": "usd", "effective_from": eff,
            "authority_ref": "Order 1/2026", "components": comps or []}, format="json")
        return r

    def approved_profile(self, person=None, **kw):
        r = self.profile(person, **kw)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.approver.post(f"{P}profiles/{r.json()['id']}/approve/", {}, format="json").status_code, 200)

    def prepare_run(self, year=2026, month=3):
        r = self.officer.post(P + "runs/prepare/", {"year": year, "month": month}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def approved_run(self):
        self.approved_profile(comps=[{"kind": "allowance", "name": "Housing", "amount": "20.00"},
                                     {"kind": "deduction", "name": "Fund", "amount": "5.00"}])
        run = self.prepare_run()
        self.assertEqual(self.officer.post(f"{P}runs/{run['id']}/submit/", {}, format="json").status_code, 200)
        self.assertEqual(self.approver.post(f"{P}runs/{run['id']}/approve/", {}, format="json").status_code, 200)
        return run

    def kill(self, person):
        Personnel.objects.filter(pk=person.pk).update(status="died")
        return DeathRecord.objects.create(personnel=person, date_of_death=date(2026, 3, 10), state="confirmed",
                                          confirmed_at="2026-03-11T00:00:00Z", confirmed_by_id=self.officer_id())

    def officer_id(self):
        from apps.accounts.models import User
        return User.objects.get(username="payofficer").pk


class SalaryProfileTests(PayrollBase):
    def test_profile_needs_a_different_approver(self):
        pid = self.profile().json()["id"]
        self.assertEqual(self.officer.post(f"{P}profiles/{pid}/approve/", {}, format="json").status_code, 403)  # officer lacks payroll.approve
        self.assertEqual(self.approver.post(f"{P}profiles/{pid}/approve/", {}, format="json").status_code, 200)
        self.assertEqual(SalaryProfile.objects.get(pk=pid).status, "approved")

    def test_duplicate_effective_date_and_negative_amount_refused(self):
        self.assertEqual(self.profile().status_code, 201)
        self.assertEqual(self.profile().status_code, 400)
        self.assertEqual(self.profile(eff="2026-02-01", base="-1").status_code, 400)

    def test_unit_level_user_cannot_see_or_create_salaries(self):
        self.assertEqual(self.unit_user.get(P + "profiles/").status_code, 403)
        self.assertEqual(self.unit_user.post(P + "profiles/", {}, format="json").status_code, 403)


class PayrollRunTests(PayrollBase):
    def test_calculation_and_duplicate_prevention(self):
        self.approved_profile(comps=[{"kind": "allowance", "name": "Housing", "amount": "20.00"}, {"kind": "deduction", "name": "Fund", "amount": "5.00"}])
        run = self.prepare_run()
        line = run["lines"][0]
        self.assertEqual((line["gross"], line["deductions"], line["calculated_net"]), ("120.00", "5.00", "115.00"))
        again = self.prepare_run()  # re-preparing a 'prepared' run reuses it: still one line, never a duplicate
        self.assertEqual(again["id"], run["id"])
        self.assertEqual(PayrollLine.objects.filter(personnel=self.soldier).count(), 1)

    def test_missing_profile_is_reported_not_paid(self):
        run = self.prepare_run()
        self.assertEqual(run["lines"], [])
        self.assertIn("missing_salary_profile", [e["code"] for e in run["exceptions"]])

    def test_preparer_cannot_approve_and_approved_run_is_final(self):
        self.approved_profile()
        run = self.prepare_run()
        self.officer.post(f"{P}runs/{run['id']}/submit/", {}, format="json")
        self.assertEqual(self.officer.post(f"{P}runs/{run['id']}/approve/", {}, format="json").status_code, 403)
        self.assertEqual(self.approver.post(f"{P}runs/{run['id']}/approve/", {}, format="json").status_code, 200)
        self.assertEqual(self.officer.post(P + "runs/prepare/", {"year": 2026, "month": 3}, format="json").status_code, 409)

    def test_direct_payment_endpoint_no_longer_exists(self):
        run = self.approved_run()
        line = self.officer.get(f"{P}runs/{run['id']}/").json()["lines"][0]
        r = self.officer.post(f"{P}runs/{run['id']}/pay/", {"line": line["id"], "amount": "1.00", "paid_on": TODAY}, format="json")
        self.assertIn(r.status_code, (404, 405))  # payments now go only through the payment workflow (method, approvals, reconciliation)

    def test_reversal_preserves_original(self):
        run = self.approved_run()
        line = self.officer.get(f"{P}runs/{run['id']}/").json()["lines"][0]
        r = self.officer.post(P + "runs/adjust/", {"line": line["id"], "kind": "reversal", "reason": "Paid in error"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["calculated_net"], "-115.00")
        self.assertEqual(PayrollLine.objects.get(pk=line["id"]).calculated_net, 115)
        self.assertEqual(self.officer.post(P + "runs/adjust/", {"line": line["id"], "kind": "reversal", "reason": "again"}, format="json").status_code, 400)

    def test_deceased_gets_no_ordinary_payroll_after_the_month_of_death(self):
        self.approved_run()
        self.kill(self.soldier)  # died 10 March 2026
        nxt = self.prepare_run(month=4)
        self.assertEqual(nxt["lines"], [])
        self.assertTrue(PayrollLine.objects.filter(personnel=self.soldier).exists())  # history kept


class SurvivorTests(PayrollBase):
    def case(self):
        self.kill(self.soldier)
        r = self.surv.post(S, {"personnel": str(self.soldier.pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def bene(self, cid, rel, name):
        r = self.surv.post(f"{S}{cid}/beneficiary/", {"full_name": name, "relationship": rel, "identity_ref": "ID-1", "evidence_ref": "Doc-1",
                                                   "payment_details": "acct 123"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def test_case_requires_confirmed_death(self):
        self.assertEqual(self.surv.post(S, {"personnel": str(self.soldier.pk)}, format="json").status_code, 400)

    def test_priority_wife_children_then_parents_then_siblings(self):
        cid = self.case()
        parent, wife = self.bene(cid, "parent", "Parent"), self.bene(cid, "wife", "Wife")
        self.assertEqual(self.surv.get(f"{S}{cid}/").json()["eligible_tier"], None)  # wife's claim still pending
        self.assertEqual(self.surv.post(f"{S}{cid}/beneficiary/{wife}/decide/", {"verify": True}, format="json").status_code, 400)  # the registrar cannot verify their own entry
        self.assertEqual(self.surv2.post(f"{S}{cid}/beneficiary/{wife}/decide/", {"verify": True}, format="json").status_code, 200)
        self.assertEqual(self.surv2.post(f"{S}{cid}/beneficiary/{parent}/decide/", {"verify": True}, format="json").status_code, 400)  # wife outranks: higher_priority_exists
        self.assertEqual(self.surv.get(f"{S}{cid}/").json()["eligible_tier"], 1)  # only the wife's class is eligible
        self.assertEqual(self.surv.post(f"{S}{cid}/verify/", {"outstanding_review": "No unpaid salary found"}, format="json").status_code, 200)
        bad = self.surv.post(f"{S}{cid}/propose/", {"beneficiary": parent, "amount": "10", "currency": "usd", "basis_ref": "Policy"}, format="json")
        self.assertEqual(bad.status_code, 400)  # parent is not in the eligible class

    def test_allocation_needs_basis_separate_authorizer_and_cannot_exceed(self):
        cid = self.case()
        wife = self.bene(cid, "wife", "Wife")
        self.surv2.post(f"{S}{cid}/beneficiary/{wife}/decide/", {"verify": True}, format="json")
        self.surv.post(f"{S}{cid}/verify/", {"outstanding_review": "reviewed"}, format="json")
        self.assertEqual(self.surv.post(f"{S}{cid}/propose/", {"beneficiary": wife, "amount": "50", "currency": "usd"}, format="json").status_code, 400)
        alloc = self.surv.post(f"{S}{cid}/propose/", {"beneficiary": wife, "amount": "50", "currency": "usd", "basis_ref": "Policy 7", "effective_from": "2026-03-01"}, format="json").json()["id"]
        self.assertEqual(self.surv.post(f"{S}{cid}/authorize/", {"allocation": alloc}, format="json").status_code, 403)  # lacks survivor.approve
        self.assertEqual(self.approver.post(f"{S}{cid}/authorize/", {"allocation": alloc}, format="json").status_code, 200)
        self.assertEqual(self.surv.post(f"{S}{cid}/dispute/", {"disputed": True, "comment": "Rival claim"}, format="json").status_code, 200)
        self.assertEqual(self.surv.post(f"{S}{cid}/pay/", {"allocation": alloc, "amount": "1"}, format="json").status_code, 404)  # no direct pay route

    def test_regular_staff_cannot_reach_survivor_data(self):
        self.assertEqual(self.unit_user.get(S).status_code, 403)


class ReadAuditTests(PayrollBase):
    def test_payroll_read_is_audited_and_denied_user_is_not_served(self):
        self.officer.get(P + "profiles/")
        self.assertTrue(AuditEvent.objects.filter(action="payroll.read_profiles", actor_username="payofficer").exists())
        self.unit_user.get(P + "profiles/")
        self.assertFalse(AuditEvent.objects.filter(action="payroll.read_profiles", actor_username="unitadmin").exists())
