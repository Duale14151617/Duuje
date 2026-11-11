"""Confirmed payroll and survivor policy: month of death, arrears, suspended/jailed flags, indefinite survivor benefits,
Sahal / bank payments with separated duties and reconciliation. Synthetic data only."""
from datetime import date

from apps.audit.models import AuditEvent
from apps.payroll.models import (ArrearsClaim, BenefitAllocation, PayrollLine, PaymentInstruction, PolicySetting, SurvivorCase,
                                 SurvivorPayment)
from apps.payroll.tests.test_payroll import PayrollBase, P, S, TODAY
from apps.personnel.models import Personnel

PAY = P + "payments/"
RECIP_SAHAL = {"mobile_number": "+252 61 555 1234"}
RECIP_BANK = {"bank_name": "Example Bank", "account_number": "0012345678"}


class PolicyBase(PayrollBase):
    def setUp(self):
        super().setUp()
        self.payer = self.client_for(self.make_user("payexec", "payment_officer"))
        self.payer2 = self.client_for(self.make_user("payexec2", "payment_officer"))
        self.recon = self.client_for(self.make_user("payrecon", "payment_reconciler"))

    # -- helpers
    def post(self, c, url, body=None):
        return c.post(url, body or {}, format="json")

    def approved_line(self, month=3, comps=None):
        self.approved_profile(comps=comps or [{"kind": "allowance", "name": "Housing", "amount": "20.00"},
                                              {"kind": "deduction", "name": "Fund", "amount": "5.00"}])
        run = self.prepare_run(month=month)
        self.assertEqual(self.post(self.officer, f"{P}runs/{run['id']}/submit/").status_code, 200)
        self.assertEqual(self.post(self.approver, f"{P}runs/{run['id']}/approve/").status_code, 200)
        return self.officer.get(f"{P}runs/{run['id']}/").json()["lines"][0], run

    def prep(self, line, amount="115.00", method="sahal", recipient=None, c=None, **extra):
        body = {"kind": "salary", "line": line["id"], "amount": amount, "method": method,
                "recipient": recipient or (RECIP_SAHAL if method == "sahal" else RECIP_BANK)}
        body.update(extra)
        return self.post(c or self.officer, PAY, body)

    def run_to_paid(self, inst_id, ref="TX-1"):
        self.assertEqual(self.post(self.approver, f"{PAY}{inst_id}/authorize/").status_code, 200)
        self.assertEqual(self.post(self.payer, f"{PAY}{inst_id}/process/").status_code, 200)
        r = self.post(self.payer, f"{PAY}{inst_id}/complete/", {"transaction_reference": ref, "paid_on": TODAY})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def survivor_case_with_wife(self):
        r = self.surv.post(S, {"personnel": str(self.soldier.pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        wife = self.surv.post(f"{S}{cid}/beneficiary/", {"full_name": "Wife", "relationship": "wife", "identity_ref": "ID-1",
                                                         "evidence_ref": "Doc-1"}, format="json").json()["id"]
        self.assertEqual(self.surv2.post(f"{S}{cid}/beneficiary/{wife}/decide/", {"verify": True}, format="json").status_code, 200)
        return cid, wife

    def standing_benefit(self, cid, wife, amount="50", eff="2026-04-01"):
        self.assertEqual(self.surv.post(f"{S}{cid}/verify/", {"outstanding_review": "reviewed"}, format="json").status_code, 200)
        alloc = self.surv.post(f"{S}{cid}/propose/", {"beneficiary": wife, "amount": amount, "currency": "usd", "basis_ref": "Decision 12/2026",
                                                      "effective_from": eff}, format="json")
        self.assertEqual(alloc.status_code, 201, alloc.content)
        aid = alloc.json()["id"]
        self.assertEqual(self.approver.post(f"{S}{cid}/authorize/", {"allocation": aid}, format="json").status_code, 200)
        return aid


class DeceasedRetainedTests(PolicyBase):
    def test_1_deceased_remain_with_history(self):
        self.approved_line()
        self.kill(self.soldier)
        p = Personnel.objects.get(pk=self.soldier.pk)
        self.assertEqual(p.status, "died")
        self.assertTrue(PayrollLine.objects.filter(personnel=p).exists())
        self.assertTrue(self.officer.get(f"{P}personnel/{p.pk}/").json()["lines"])  # payroll history still readable


class SurvivorPriorityTests(PolicyBase):
    def setUp(self):
        super().setUp()
        self.kill(self.soldier)
        self.cid = self.surv.post(S, {"personnel": str(self.soldier.pk)}, format="json").json()["id"]

    def bene(self, rel, name):
        return self.surv.post(f"{S}{self.cid}/beneficiary/", {"full_name": name, "relationship": rel, "identity_ref": "ID", "evidence_ref": "Doc"}, format="json")

    def decide(self, bid, verify=True):
        return self.surv2.post(f"{S}{self.cid}/beneficiary/{bid}/decide/", {"verify": verify, "comment": "not eligible"}, format="json")

    def test_2_parents_cannot_be_verified_while_a_wife_claim_is_pending(self):
        parent = self.bene("parent", "Parent").json()["id"]
        wife = self.bene("wife", "Wife").json()["id"]
        self.assertEqual(self.decide(parent).status_code, 400)       # higher class still undecided
        self.assertEqual(self.decide(wife).status_code, 200)
        self.assertEqual(self.decide(parent).status_code, 400)       # higher class verified: parents are not eligible

    def test_2_lower_class_cannot_register_once_a_higher_one_is_verified(self):
        wife = self.bene("wife", "Wife").json()["id"]
        self.decide(wife)
        self.assertEqual(self.bene("parent", "Parent").status_code, 400)
        self.assertEqual(self.bene("sibling", "Brother").status_code, 400)

    def test_2_parents_then_siblings_when_higher_classes_rejected(self):
        wife = self.bene("wife", "Wife").json()["id"]
        self.assertEqual(self.decide(wife, verify=False).status_code, 200)
        parent = self.bene("parent", "Parent").json()["id"]
        sibling = self.bene("sibling", "Sibling").json()["id"]
        self.assertEqual(self.decide(sibling).status_code, 400)      # parent undecided
        self.assertEqual(self.decide(parent).status_code, 200)
        case = self.surv.get(f"{S}{self.cid}/").json()
        self.assertEqual(case["eligible_tier"], 2)

    def test_2_wife_and_children_share_the_first_class_and_amounts_are_decisions(self):
        wife = self.bene("wife", "Wife").json()["id"]
        child = self.bene("child", "Child").json()["id"]
        self.decide(wife), self.decide(child)
        self.surv.post(f"{S}{self.cid}/verify/", {"outstanding_review": "ok"}, format="json")
        no_basis = self.surv.post(f"{S}{self.cid}/propose/", {"beneficiary": wife, "amount": "10", "currency": "usd",
                                                              "effective_from": "2026-04-01"}, format="json")
        self.assertEqual(no_basis.status_code, 400)  # the system never invents an allocation: a cited decision is required
        self.assertEqual(self.surv.get(f"{S}{self.cid}/").json()["eligible_tier"], 1)


class IndefiniteBenefitTests(PolicyBase):
    def setUp(self):
        super().setUp()
        self.kill(self.soldier)
        self.cid, self.wife = self.survivor_case_with_wife()
        self.aid = self.standing_benefit(self.cid, self.wife)

    def alloc(self):
        return BenefitAllocation.objects.get(pk=self.aid)

    def test_3_no_end_date_expiry_or_duration(self):
        a = self.alloc()
        self.assertIsNone(a.ended_on)
        self.assertIsNone(a.held_from)
        names = {f.name for f in BenefitAllocation._meta.get_fields()}
        self.assertFalse({n for n in names if "expir" in n or "duration" in n or "months" in n or "years" in n})
        self.assertEqual(self.surv.get(f"{S}{self.cid}/").json()["duration"], "indefinite")

    def test_3_a_payment_many_years_later_is_still_allowed(self):
        r = self.post(self.officer, PAY, {"kind": "survivor", "allocation": self.aid, "period_year": 2056, "period_month": 7, "amount": "50",
                                          "method": "bank_transfer", "recipient": RECIP_BANK})
        self.assertEqual(r.status_code, 201, r.content)

    def test_3_termination_needs_documented_decision_and_a_different_approver(self):
        base = {"allocation": self.aid, "kind": "terminate", "reason": "Beneficiary remarried: decision 44/2027", "effective_date": "2027-01-01",
                "supporting_ref": "Order 44/2027"}
        self.assertEqual(self.post(self.surv, f"{S}{self.cid}/decision/", {**base, "reason": ""}).status_code, 400)
        self.assertEqual(self.post(self.surv, f"{S}{self.cid}/decision/", {**base, "supporting_ref": ""}).status_code, 400)
        dec = self.post(self.surv, f"{S}{self.cid}/decision/", base)
        self.assertEqual(dec.status_code, 201, dec.content)
        self.assertIsNone(self.alloc().ended_on)  # nothing ends before the decision is approved
        did = dec.json()["id"]
        self.assertEqual(self.post(self.surv, f"{S}{self.cid}/decision/{did}/decide/", {"approve": True}).status_code, 403)  # no survivor.approve
        self.assertEqual(self.post(self.approver, f"{S}{self.cid}/decision/{did}/decide/", {"approve": True}).status_code, 200)
        a = self.alloc()
        self.assertEqual((a.status, str(a.ended_on)), ("terminated", "2027-01-01"))
        late = self.post(self.officer, PAY, {"kind": "survivor", "allocation": self.aid, "period_year": 2027, "period_month": 6, "amount": "50",
                                             "method": "sahal", "recipient": RECIP_SAHAL})
        self.assertEqual(late.status_code, 409)  # terminated (status), by decision only
        self.assertTrue(AuditEvent.objects.filter(action="allocation.decision_approve").exists())

    def test_3_history_of_decisions_is_kept_and_visible(self):
        dec = self.post(self.surv, f"{S}{self.cid}/decision/", {"allocation": self.aid, "kind": "change_amount", "new_amount": "60",
                                                               "reason": "Revised by order", "effective_date": "2026-09-01", "supporting_ref": "Order 9"})
        self.post(self.approver, f"{S}{self.cid}/decision/{dec.json()['id']}/decide/", {"approve": True})
        self.assertEqual(str(self.alloc().amount), "60.00")
        beneficiary = self.surv.get(f"{S}{self.cid}/").json()["beneficiaries"][0]
        decision = beneficiary["allocations"][0]["decisions"][0]
        self.assertEqual((decision["previous_amount"], decision["new_amount"], decision["state"]), ("50.00", "60.00", "approved"))

    def test_3_case_cannot_close_while_a_benefit_is_live_and_closing_needs_a_decision(self):
        body = {"reason": "Closed by order", "effective_date": "2027-01-01", "supporting_ref": "Order 1"}
        self.assertEqual(self.post(self.approver, f"{S}{self.cid}/close/", body).status_code, 400)  # live benefit remains
        self.assertEqual(self.post(self.approver, f"{S}{self.cid}/close/", {}).status_code, 400)


class MonthOfDeathTests(PolicyBase):
    def test_4_full_month_of_death_salary_not_prorated_and_paid_to_a_verified_beneficiary(self):
        self.approved_profile(comps=[{"kind": "allowance", "name": "Housing", "amount": "20.00"}, {"kind": "deduction", "name": "Fund", "amount": "5.00"}])
        self.kill(self.soldier)  # died 10 March 2026
        run = self.prepare_run(month=3)
        line = run["lines"][0]
        self.assertEqual(line["calculated_net"], "115.00")  # the full month, not 10/31 of it
        self.assertTrue(line["death_month"])
        self.assertIn("death_month_full_salary", [e["code"] for e in run["exceptions"]])
        self.assertEqual(self.post(self.officer, f"{P}runs/{run['id']}/submit/").status_code, 200)
        self.assertEqual(self.post(self.approver, f"{P}runs/{run['id']}/approve/").status_code, 200)  # normal approval still required
        no_ben = self.prep(line)
        self.assertEqual(no_ben.status_code, 400)  # no verified beneficiary yet
        _, wife = self.survivor_case_with_wife()
        inst = self.prep(line, beneficiary=wife, method="bank_transfer")
        self.assertEqual(inst.status_code, 201, inst.content)
        self.run_to_paid(inst.json()["id"])
        self.assertEqual(self.officer.get(f"{P}runs/{run['id']}/").json()["lines"][0]["paid"], "115.00")

    def test_4_the_month_after_death_is_not_paid_through_payroll(self):
        self.approved_profile()
        self.kill(self.soldier)
        self.assertEqual(self.prepare_run(month=4)["lines"], [])


class ArrearsTests(PolicyBase):
    def test_5_earlier_unpaid_salary_is_arrears_not_ordinary_payment(self):
        line, run_ = self.approved_line(month=2)  # February approved, never paid
        self.kill(self.soldier)                # died in March
        self.assertEqual(self.prep(line).status_code, 400)  # not payable as salary: it is arrears
        summary = self.officer.get(f"{P}personnel/{self.soldier.pk}/").json()
        self.assertEqual([u["period"] for u in summary["unpaid_approved_lines"]], ["2026-02"])  # reported, never forfeited
        cid, wife = self.survivor_case_with_wife()
        claim = self.post(self.officer, P + "arrears/", {"personnel": str(self.soldier.pk), "periods": ["2026-02"], "amount": "115.00",
                                                          "currency": "usd", "evidence_ref": "Payslip Feb", "source_lines": [line["id"]]})
        self.assertEqual(claim.status_code, 201, claim.content)
        cid_ = claim.json()["id"]
        early = self.post(self.officer, PAY, {"kind": "arrears", "claim": cid_, "amount": "115.00", "method": "sahal", "recipient": RECIP_SAHAL,
                                              "beneficiary": wife})
        self.assertEqual(early.status_code, 409)                                                # unverified/unapproved
        self.assertEqual(self.post(self.officer, f"{P}arrears/{cid_}/verify/", {}).status_code, 400)  # recorder cannot verify
        self.assertEqual(self.post(self.officer2, f"{P}arrears/{cid_}/verify/", {}).status_code, 200)
        self.assertEqual(self.post(self.officer, f"{P}arrears/{cid_}/approve/", {}).status_code, 403)   # approval is a separate authority
        self.assertEqual(self.post(self.approver, f"{P}arrears/{cid_}/approve/", {}).status_code, 200)
        ok = self.post(self.officer, PAY, {"kind": "arrears", "claim": cid_, "amount": "115.00", "method": "sahal", "recipient": RECIP_SAHAL,
                                           "beneficiary": wife})
        self.assertEqual(ok.status_code, 201, ok.content)
        too_much = self.post(self.officer, PAY, {"kind": "arrears", "claim": cid_, "amount": "1.00", "method": "sahal", "recipient": RECIP_SAHAL,
                                                 "beneficiary": wife})
        self.assertEqual(too_much.status_code, 400)  # the open instruction already reserves the whole claim
        self.run_to_paid(ok.json()["id"], ref="AR-1")
        self.assertEqual(ArrearsClaim.objects.get(pk=cid_).payments.count(), 1)
        self.assertFalse(SurvivorPayment.objects.exists())   # never mixed with survivor-benefit payments
        self.assertEqual(self.officer.get(f"{P}runs/{run_['id']}/").json()["lines"][0]["paid"], "0.00")  # and kept apart from the run


class SuspendedJailedTests(PolicyBase):
    def test_6_flagged_and_still_paid_in_full(self):
        Personnel.objects.filter(pk=self.soldier.pk).update(status="suspended")
        self.approved_profile(comps=[{"kind": "allowance", "name": "Housing", "amount": "20.00"}])
        run = self.prepare_run()
        line = run["lines"][0]
        self.assertEqual(line["status_flag"], "suspended")
        self.assertEqual(line["calculated_net"], "120.00")  # no stop, cut or withholding
        self.assertIn("status_needs_decision", [e["code"] for e in run["exceptions"]])
        queue = self.officer.get(P + "personnel/").json()["results"]
        self.assertEqual([q["personnel"] for q in queue], [str(self.soldier.pk)])
        self.assertTrue(queue[0]["needs_decision"])

    def test_6_decision_is_recorded_approved_by_someone_else_and_changes_no_pay(self):
        Personnel.objects.filter(pk=self.soldier.pk).update(status="jailed")
        self.approved_profile()
        run = self.prepare_run()
        url = f"{P}personnel/{self.soldier.pk}/decisions/"
        self.assertEqual(self.post(self.officer, url, {"kind": "formal_decision", "reason": "Court order", "effective_date": "2026-03-01"}).status_code, 400)
        rec = self.post(self.officer, url, {"kind": "retain_existing", "reason": "No official rule yet", "effective_date": "2026-03-01"})
        self.assertEqual(rec.status_code, 201, rec.content)
        did = rec.json()["id"]
        self.assertEqual(self.post(self.officer, f"{url}{did}/decide/", {"approve": True}).status_code, 403)  # needs payroll.decide
        self.assertEqual(self.post(self.approver, f"{url}{did}/decide/", {"approve": True}).status_code, 200)
        self.assertEqual(PayrollLine.objects.get(pk=run["lines"][0]["id"]).calculated_net, 100)
        self.assertTrue(AuditEvent.objects.filter(action="pay_decision.approve").exists())
        self.assertEqual(self.unit_user.get(P + "personnel/").status_code, 403)

    def test_6_an_active_person_is_not_in_the_review_queue_and_cannot_get_a_decision(self):
        r = self.post(self.officer, f"{P}personnel/{self.soldier.pk}/decisions/", {"kind": "retain_existing", "reason": "x", "effective_date": "2026-03-01"})
        self.assertEqual(r.status_code, 400)


class PaymentMethodTests(PolicyBase):
    def test_7_sahal_and_bank_are_available_and_nothing_claims_integration(self):
        r = self.officer.get(PAY + "methods/").json()
        self.assertEqual({m["code"] for m in r["methods"]}, {"sahal", "bank_transfer"})
        self.assertTrue(all(m["integration"] == "none" for m in r["methods"]))
        self.assertIn("No direct integration", r["integration_note"])
        policy = {p["key"]: p for p in self.officer.get(P + "policy/").json()["results"]}
        self.assertEqual(policy["payment_provider_integration"]["value"], "none_manual_recording")

    def test_7_recipient_validation_per_method(self):
        line, _ = self.approved_line()
        self.assertEqual(self.prep(line, method="sahal", recipient={"mobile_number": "abc"}).status_code, 400)
        self.assertEqual(self.prep(line, method="bank_transfer", recipient={"bank_name": "", "account_number": "123456"}).status_code, 400)
        self.assertEqual(self.prep(line, method="cheque", recipient={}).status_code, 400)
        ok = self.prep(line, method="sahal")
        self.assertEqual(ok.status_code, 201, ok.content)
        body = ok.json()
        self.assertEqual((body["method"], body["currency"], body["period"], body["status"], body["reconciliation_status"]),
                         ("sahal", "USD", "2026-03", "prepared", "unreconciled"))
        self.assertEqual(body["recipient_display"], "Sahal ••••1234")
        self.assertNotIn("252615551234", str(body))  # the number is not in the normal response

    def test_7_amount_cannot_exceed_what_is_approved_less_what_is_already_in_flight(self):
        line, _ = self.approved_line()
        self.assertEqual(self.prep(line, amount="200.00").status_code, 400)
        self.assertEqual(self.prep(line, amount="100.00").status_code, 201)
        self.assertEqual(self.prep(line, amount="20.00").status_code, 400)  # only 15.00 left
        self.assertEqual(self.prep(line, amount="15.00", method="bank_transfer").status_code, 201)


class PaymentWorkflowTests(PolicyBase):
    def setUp(self):
        super().setUp()
        self.line, self.run_ = self.approved_line()
        self.iid = self.prep(self.line).json()["id"]

    def test_8_separation_of_duties_at_every_step(self):
        self.assertEqual(self.post(self.officer, f"{PAY}{self.iid}/authorize/").status_code, 403)       # preparer lacks payment.authorize
        self.assertEqual(self.post(self.approver, f"{PAY}{self.iid}/process/").status_code, 403)         # authorizer lacks payment.execute
        self.assertEqual(self.post(self.approver, f"{PAY}{self.iid}/authorize/").status_code, 200)
        self.assertEqual(self.post(self.payer, f"{PAY}{self.iid}/process/").status_code, 200)
        self.assertEqual(self.post(self.payer2, f"{PAY}{self.iid}/complete/", {"transaction_reference": "X", "paid_on": TODAY}).status_code, 400)
        self.assertEqual(self.post(self.payer, f"{PAY}{self.iid}/complete/", {"paid_on": TODAY}).status_code, 400)  # reference mandatory
        self.assertEqual(self.post(self.payer, f"{PAY}{self.iid}/complete/", {"transaction_reference": "TX-9", "paid_on": TODAY}).status_code, 200)
        self.assertEqual(self.post(self.payer, f"{PAY}{self.iid}/reconcile/", {"statement_ref": "TX-9", "statement_amount": "115.00",
                                                                                "statement_date": TODAY}).status_code, 403)  # executor lacks payment.reconcile

    def test_8_the_service_refuses_self_authorization_even_if_one_person_held_both_roles(self):
        from rest_framework.exceptions import ValidationError
        from apps.accounts.models import User
        from apps.payroll import payments as pay
        preparer = User.objects.get(username="payofficer")
        with self.assertRaises(ValidationError):
            pay.authorize_payment(preparer, PaymentInstruction.objects.get(pk=self.iid))
        self.assertEqual(PaymentInstruction.objects.get(pk=self.iid).status, "prepared")
        self.assertTrue(AuditEvent.objects.filter(action="payment.authorize", outcome="denied", actor_username="payofficer").exists())

    def test_8_full_lifecycle_posts_to_the_ledger_and_is_reconciled_by_a_third_person(self):
        self.run_to_paid(self.iid, ref="BANK-77")
        inst = PaymentInstruction.objects.get(pk=self.iid)
        self.assertEqual((inst.status, inst.transaction_reference), ("paid", "BANK-77"))
        self.assertEqual(self.officer.get(f"{P}runs/{self.run_['id']}/").json()["status"], "paid")
        bad = self.post(self.recon, f"{PAY}{self.iid}/reconcile/", {"statement_ref": "BANK-77", "statement_amount": "110.00", "statement_date": TODAY})
        self.assertEqual(bad.status_code, 400)  # a mismatch must be explained
        d = self.post(self.recon, f"{PAY}{self.iid}/reconcile/", {"statement_ref": "BANK-77", "statement_amount": "110.00", "statement_date": TODAY,
                                                                   "note": "Bank fee deducted"})
        self.assertEqual(d.json()["reconciliation_status"], "discrepancy")
        ok = self.post(self.recon, f"{PAY}{self.iid}/reconcile/", {"statement_ref": "BANK-77", "statement_amount": "115.00", "statement_date": TODAY})
        self.assertEqual(ok.json()["reconciliation_status"], "reconciled")
        self.assertEqual(self.post(self.recon, f"{PAY}{self.iid}/reconcile/", {"statement_ref": "BANK-77", "statement_amount": "115.00",
                                                                                "statement_date": TODAY}).status_code, 409)  # already reconciled

    def test_8_failed_payment_releases_the_amount_and_can_be_retried(self):
        self.post(self.approver, f"{PAY}{self.iid}/authorize/")
        self.post(self.payer, f"{PAY}{self.iid}/process/")
        self.assertEqual(self.post(self.payer, f"{PAY}{self.iid}/pending/", {"comment": "Awaiting Sahal confirmation"}).status_code, 200)
        self.assertEqual(self.post(self.payer, f"{PAY}{self.iid}/fail/", {}).status_code, 400)  # reason required
        self.assertEqual(self.post(self.payer, f"{PAY}{self.iid}/fail/", {"reason": "Wrong number"}).status_code, 200)
        retry = self.prep(self.line, retry_of=self.iid, recipient={"mobile_number": "615551235"})
        self.assertEqual(retry.status_code, 201, retry.content)
        detail = self.officer.get(f"{PAY}{self.iid}/").json()
        self.assertEqual([e["action"] for e in detail["events"]], ["prepare", "authorize", "process", "pending", "fail"])  # full history

    def test_8_every_sensitive_step_is_audited_without_recipient_details(self):
        self.run_to_paid(self.iid, ref="AUD-1")
        actions = set(AuditEvent.objects.filter(entity_id=self.iid).values_list("action", flat=True))
        self.assertTrue({"payment.prepare", "payment.authorize", "payment.process", "payment.complete"} <= actions)
        blob = " ".join(str(m) for m in AuditEvent.objects.values_list("metadata", flat=True))
        self.assertNotIn("5551234", blob)
        self.assertNotIn("0012345678", blob)

    def test_8_reveal_needs_payment_details_and_is_audited(self):
        self.assertEqual(self.officer.get(f"{PAY}{self.iid}/reveal/").status_code, 403)
        self.assertEqual(self.approver.get(f"{PAY}{self.iid}/reveal/").status_code, 403)
        r = self.payer.get(f"{PAY}{self.iid}/reveal/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["recipient"]["mobile_number"], "252615551234")
        self.assertTrue(AuditEvent.objects.filter(action="payment.reveal_details", actor_username="payexec").exists())

    def test_8_a_dispute_after_preparation_stops_the_survivor_payment_at_each_step(self):
        self.kill(self.soldier)
        cid, wife = self.survivor_case_with_wife()
        aid = self.standing_benefit(cid, wife)
        inst = self.post(self.officer, PAY, {"kind": "survivor", "allocation": aid, "period_year": 2026, "period_month": 5, "amount": "50",
                                             "method": "sahal", "recipient": RECIP_SAHAL}).json()["id"]
        self.assertEqual(self.post(self.surv, f"{S}{cid}/dispute/", {"disputed": True, "comment": "Rival claim"}).status_code, 200)
        self.assertEqual(self.post(self.approver, f"{PAY}{inst}/authorize/").status_code, 409)


class ReferenceReuseTests(PolicyBase):
    def test_a_transaction_reference_cannot_be_recorded_twice_for_the_same_method(self):
        second = self.person("BARI-ARMY-A", "Second Soldier", service_number="S-101")
        self.approved_profile()
        self.approved_profile(second)
        run = self.prepare_run()
        self.post(self.officer, f"{P}runs/{run['id']}/submit/")
        self.post(self.approver, f"{P}runs/{run['id']}/approve/")
        lines = self.officer.get(f"{P}runs/{run['id']}/").json()["lines"]
        self.assertEqual(len(lines), 2)
        ids = [self.prep(l, amount="100.00").json()["id"] for l in lines]
        self.run_to_paid(ids[0], ref="SAME-REF")
        self.post(self.approver, f"{PAY}{ids[1]}/authorize/")
        self.post(self.payer, f"{PAY}{ids[1]}/process/")
        r = self.post(self.payer, f"{PAY}{ids[1]}/complete/", {"transaction_reference": "SAME-REF", "paid_on": TODAY})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(PaymentInstruction.objects.get(pk=ids[1]).status, "processing")


class AccessControlTests(PolicyBase):
    def test_9_unauthorized_users_cannot_read_or_change_sensitive_data(self):
        line, _ = self.approved_line()
        iid = self.prep(line).json()["id"]
        outsiders = [("unit", self.unit_user), ("surv", self.surv)]
        for name, c in outsiders:
            for url in (PAY, P + "arrears/", P + "personnel/", f"{PAY}{iid}/"):
                self.assertEqual(c.get(url).status_code, 403, f"{name} {url}")
            self.assertEqual(self.post(c, PAY, {}).status_code, 403, name)
            self.assertEqual(self.post(c, P + "arrears/", {}).status_code, 403, name)
        self.assertEqual(self.unit_user.get(f"{PAY}{iid}/reveal/").status_code, 403)
        denied = AuditEvent.objects.filter(action="access.denied", actor_username="unitadmin").count()
        self.assertGreater(denied, 0)  # refusals are audited

    def test_9_read_access_is_not_edit_approve_or_pay_access(self):
        line, _ = self.approved_line()
        iid = self.prep(line).json()["id"]
        viewer = self.recon  # payroll.view + payment.reconcile only
        self.assertEqual(viewer.get(PAY).status_code, 200)
        self.assertEqual(self.post(viewer, PAY, {}).status_code, 403)
        self.assertEqual(self.post(viewer, f"{PAY}{iid}/authorize/").status_code, 403)
        self.assertEqual(self.post(viewer, f"{PAY}{iid}/process/").status_code, 403)
        self.assertEqual(self.post(viewer, P + "arrears/", {}).status_code, 403)
        self.assertEqual(self.post(viewer, P + "policy/payroll_currency/confirm/", {"value": "USD", "authority_ref": "x"}).status_code, 403)

    def test_9_list_reads_are_audited_and_hide_recipient_numbers(self):
        line, _ = self.approved_line()
        self.prep(line)
        r = self.officer.get(PAY)
        self.assertNotIn("252615551234", r.content.decode())
        self.assertTrue(AuditEvent.objects.filter(action="payment.read_list", actor_username="payofficer").exists())


class PolicyConfigTests(PolicyBase):
    def test_every_item_is_confirmed_with_the_institutions_answers(self):
        items = {p["key"]: p for p in self.officer.get(P + "policy/").json()["results"]}
        self.assertEqual(items["month_of_death_salary"]["status"], "confirmed")
        self.assertEqual(items["survivor_benefit_duration"]["value"], "indefinite")
        self.assertEqual(items["payroll_currency"]["value"], "USD")
        self.assertEqual(items["suspended_jailed_deduction_tiers"]["value"], "5,10,20")
        for key in ("survivor_allocation_rule", "deceased_salary_recipient"):
            self.assertEqual(items[key]["value"], "priority_order_then_sharia_division", key)
        for key in ("survivor_eligibility_conditions", "survivor_priority_after_loss"):
            self.assertEqual(items[key]["value"], "wife_children>parents>siblings", key)
        self.assertEqual(items["arrears_entitlement_rules"]["value"], "finance_decides")
        self.assertEqual(PolicySetting.objects.filter(status="unconfirmed").count(), 0)

    def test_only_the_policy_authority_can_revise_and_every_change_is_audited(self):
        url = P + "policy/payroll_currency/revise/"
        body = {"value": "EUR", "authority_ref": "Decree 1", "reason": "Currency change"}
        self.assertEqual(self.post(self.approver, url, body).status_code, 403)
        super_admin = self.client_for(self.make_user("boss", "super_admin"))
        self.assertEqual(self.post(super_admin, url, {"value": "EUR", "authority_ref": "Decree 1"}).status_code, 400)  # reason required
        self.assertEqual(self.post(super_admin, url, body).status_code, 200)
        self.assertEqual(PolicySetting.objects.get(key="payroll_currency").value, "EUR")
        ev = AuditEvent.objects.get(action="policy.revise")
        self.assertEqual((ev.metadata["old_value"], ev.metadata["new_value"]), ("USD", "EUR"))
        self.assertEqual(self.post(super_admin, P + "policy/suspended_jailed_deduction_tiers/revise/",
                                   {"value": "5,150", "authority_ref": "x", "reason": "y"}).status_code, 400)  # tiers must be 1-99
        self.assertEqual(self.post(super_admin, P + "policy/suspended_jailed_deduction_tiers/revise/",
                                   {"value": "5,10,25", "authority_ref": "x", "reason": "y"}).status_code, 200)


class DeductionTierTests(PolicyBase):
    def _decide(self, pct, approve=True):
        url = f"{P}personnel/{self.soldier.pk}/decisions/"
        rec = self.post(self.officer, url, {"kind": "formal_decision", "decision_text": "Finance tier", "supporting_ref": "FIN-1",
                                            "reason": "Severity assessed by Finance", "effective_date": "2026-01-01", "deduction_percent": pct})
        if rec.status_code != 201:
            return rec
        if approve:
            self.assertEqual(self.post(self.approver, f"{url}{rec.json()['id']}/decide/", {"approve": True}).status_code, 200)
        return rec

    def test_only_policy_tiers_are_accepted(self):
        Personnel.objects.filter(pk=self.soldier.pk).update(status="suspended")
        self.assertEqual(self._decide(15).status_code, 400)
        self.assertEqual(self._decide(10, approve=False).status_code, 201)

    def test_approved_tier_is_deducted_from_gross_and_unapproved_is_not(self):
        Personnel.objects.filter(pk=self.soldier.pk).update(status="jailed")
        self.approved_profile(comps=[{"kind": "allowance", "name": "Housing", "amount": "20.00"}])  # gross 120
        self._decide(20, approve=False)
        self.assertEqual(self.prepare_run()["lines"][0]["calculated_net"], "120.00")  # not approved yet: nothing deducted
        self._decide(10)
        run = self.prepare_run()
        self.assertEqual(run["lines"][0]["calculated_net"], "108.00")  # 120 - 10%
        self.assertEqual(run["lines"][0]["status_flag"], "jailed")


class BeneficiaryChangeTests(PolicyBase):
    def test_changes_need_a_reason_and_are_logged_without_values(self):
        self.kill(self.soldier)
        cid, wife = self.survivor_case_with_wife()
        url = f"{S}{cid}/beneficiary/{wife}/update/"
        self.assertEqual(self.post(self.surv, url, {"identity_ref": "ID-NEW"}).status_code, 400)  # reason required
        self.assertEqual(self.post(self.surv, url, {"identity_ref": "ID-NEW", "reason": "Corrected document number"}).status_code, 200)
        self.assertEqual(self.post(self.officer, url, {"identity_ref": "X", "reason": "r"}).status_code, 403)
        ev = AuditEvent.objects.get(action="beneficiary.update")
        self.assertEqual(ev.metadata, {"fields": ["identity_ref"]})
        self.assertNotIn("ID-NEW", str(ev.metadata))

    def test_beneficiary_record_access_is_audited(self):
        self.kill(self.soldier)
        cid, _ = self.survivor_case_with_wife()
        self.surv.get(f"{S}{cid}/")
        self.assertTrue(AuditEvent.objects.filter(action="survivor.read_case", actor_username="survofficer").exists())


class MigrationDefaultsTests(PolicyBase):
    def test_clean_install_has_policy_rows_and_new_allocations_default_to_standing(self):
        self.assertTrue(PolicySetting.objects.filter(key="survivor_benefit_duration", status="confirmed").exists())
        self.assertEqual(BenefitAllocation._meta.get_field("basis_kind").default, "per_period")
        self.assertEqual(SurvivorCase.objects.count(), 0)
