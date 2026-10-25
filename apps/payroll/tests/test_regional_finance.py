"""Regional finance pays salaries: headquarters prepares and approves the run, a regional command's finance accounts
authorize, send and reconcile only the SALARY payments of their own command. Synthetic data only."""
from apps.payroll.tests.test_payroll import P, TODAY
from apps.payroll.tests.test_policy_payments import PAY, PolicyBase


class RegionalBase(PolicyBase):
    def setUp(self):
        super().setUp()
        self.other = self.person("NUGAAL-ARMY-A", "Nugaal Soldier", service_number="S-200")
        self.approved_profile(self.other)  # no components: net 100.00
        self.line_bari, self.run = self.approved_line()  # soldier (Bari): net 115.00; the run holds both regions' lines
        lines = self.officer.get(f"{P}runs/{self.run['id']}/").json()["lines"]
        self.line_bari = next(l for l in lines if l["service_number"] == "S-100")
        self.line_nug = next(l for l in lines if l["service_number"] == "S-200")
        mk = lambda name, role, unit="BARI-ARMY": self.client_for(self.make_user(name, role, unit=unit))
        self.r_prep, self.r_auth = mk("bprep", "payroll_officer"), mk("bauth", "payroll_approver")
        self.r_pay, self.r_rec = mk("bpay", "payment_officer"), mk("brec", "payment_reconciler")


class RegionalFinanceTests(RegionalBase):
    def test_regional_reader_sees_only_its_own_lines_and_no_exceptions(self):
        r = self.r_prep.get(f"{P}runs/{self.run['id']}/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([l["service_number"] for l in body["lines"]], ["S-100"])
        self.assertEqual((body["exceptions"], body["actions"]), ([], []))
        self.assertEqual(len(self.officer.get(f"{P}runs/{self.run['id']}/").json()["lines"]), 2)  # headquarters unchanged
        self.assertEqual(self.r_prep.get(f"{P}runs/summary/").status_code, 200)

    def test_regional_reader_does_not_see_runs_that_are_not_approved_yet(self):
        draft = self.prepare_run(month=4)
        ids = [x["id"] for x in self.r_prep.get(f"{P}runs/").json()["results"]]
        self.assertIn(self.run["id"], ids)
        self.assertNotIn(draft["id"], ids)
        self.assertEqual(self.r_prep.get(f"{P}runs/{draft['id']}/").status_code, 404)

    def test_regional_finance_prepares_only_own_region_salary_payments(self):
        self.assertEqual(self.prep(self.line_bari, c=self.r_prep).status_code, 201)
        self.assertEqual(self.prep(self.line_nug, amount="100.00", c=self.r_prep).status_code, 404)  # another region's line
        r = self.post(self.r_prep, PAY, {"kind": "arrears", "claim": "00000000-0000-0000-0000-000000000000", "amount": "1",
                                         "method": "sahal", "recipient": {"mobile_number": "+252 61 555 1234"}})
        self.assertEqual(r.status_code, 404)  # arrears and survivor payments stay with headquarters

    def test_full_regional_chain_with_a_different_person_at_each_step(self):
        inst = self.prep(self.line_bari, c=self.r_prep).json()["id"]
        self.assertEqual(self.post(self.r_auth, f"{PAY}{inst}/authorize/").status_code, 200)
        self.assertEqual(self.post(self.r_pay, f"{PAY}{inst}/process/").status_code, 200)
        done = self.post(self.r_pay, f"{PAY}{inst}/complete/", {"transaction_reference": "TX-R1", "paid_on": TODAY})
        self.assertEqual(done.status_code, 200, done.content)
        rec = self.post(self.r_rec, f"{PAY}{inst}/reconcile/", {"statement_ref": "ST-1", "statement_amount": "115.00", "statement_date": TODAY})
        self.assertEqual(rec.status_code, 200, rec.content)

    def test_regional_finance_cannot_touch_another_regions_payment(self):
        inst = self.prep(self.line_nug, amount="100.00").json()["id"]  # prepared by headquarters
        self.assertEqual(self.post(self.r_auth, f"{PAY}{inst}/authorize/").status_code, 404)
        self.assertEqual(self.r_auth.get(f"{PAY}{inst}/").status_code, 404)
        self.assertEqual(self.r_auth.get(PAY).json()["results"], [])
        self.assertEqual(len(self.officer.get(PAY).json()["results"]), 1)  # headquarters still sees it

    def test_regional_finance_cannot_do_headquarters_only_work(self):
        self.assertEqual(self.profile(c=self.r_prep).status_code, 403)
        self.assertEqual(self.post(self.r_prep, P + "runs/prepare/", {"year": 2026, "month": 5}).status_code, 403)
        self.assertEqual(self.post(self.r_auth, f"{P}runs/{self.run['id']}/approve/").status_code, 403)


class BattalionAuditorTests(RegionalBase):
    def test_battalion_auditor_reads_only_its_own_people_and_acts_on_nothing(self):
        aud = self.client_for(self.make_user("aud3", "auditor", unit="BARI-ARMY-A"))
        self.prep(self.line_bari)
        self.prep(self.line_nug, amount="100.00")
        rows = aud.get(PAY).json()["results"]
        self.assertEqual([r["service_number"] for r in rows], ["S-100"])
        self.assertEqual(self.post(aud, PAY, {"kind": "salary", "line": self.line_bari["id"]}).status_code, 403)
        names = [p["service_number"] for p in aud.get(f"{P}profiles/").json()["results"]]
        self.assertEqual(names, ["S-100"])
