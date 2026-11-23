"""Promotion eligibility by rank and time in rank. Synthetic data only."""
from datetime import date, timedelta

from apps.audit.models import AuditEvent
from apps.personnel import services as svc
from apps.personnel.models import PersonnelHistory
from apps.personnel.tests.test_personnel import PersonnelBase
from apps.promotion.models import PromotionRule
from apps.promotion.views import months_between

P = "/api/v1/promotion/"


class PromotionBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.unit_a = self.unit("BARI-ARMY-A")
        self.cmdr = self.client_for(self.make_user("promo.cmdr", "unit_commander", unit="BARI-ARMY-A"))
        self.other = self.client_for(self.make_user("promo.other", "unit_commander", unit="BARI-ARMY-B"))
        self.sa = self.client_for(self.make_user("promo.sa", "super_admin"))
        self.base_rank = self.rank("PA-02")  # its next rank, PA-03, is approved (PA-04 is a draft in the fixture)

    def set_rule(self, months=24, c=None, **kw):
        return (c or self.sa).post(P + "rules/set/", {"rank": str(self.base_rank.pk), "min_months": months, **kw}, format="json")

    def served(self, name, months, status="active", rank=None):
        """A person whose rank was entered this many months ago (the effective date of their first rank entry)."""
        return svc.create_personnel(None, full_name=name, phone="", service_number=None, org_unit=self.unit_a, rank=rank or self.base_rank,
                                    status=status, effective_date=date.today() - timedelta(days=int(months * 30.5) + 2))

    def table(self, c=None, **params):
        r = (c or self.cmdr).get(P + "eligibility/", {"org_unit": str(self.unit_a.pk), **params})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()


class MonthsTests(PromotionBase):
    def test_whole_months_only(self):
        self.assertEqual(months_between(date(2024, 1, 31), date(2024, 3, 30)), 1)
        self.assertEqual(months_between(date(2024, 1, 15), date(2024, 3, 15)), 2)
        self.assertEqual(months_between(date(2024, 5, 1), date(2024, 4, 1)), 0)


class RuleTests(PromotionBase):
    def test_only_the_super_administrator_sets_rules(self):
        self.assertEqual(self.set_rule(c=self.cmdr).status_code, 403)
        self.assertEqual(self.client_for(self.make_user("promo.hq", "hq_admin")).post(
            P + "rules/set/", {"rank": str(self.base_rank.pk), "min_months": 12}, format="json").status_code, 403)
        r = self.set_rule()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(AuditEvent.objects.filter(action="promotion.rule_set").exists())

    def test_rule_values_are_validated(self):
        for bad in (0, 601, "12", True):
            self.assertEqual(self.set_rule(months=bad).status_code, 400, bad)
        self.assertEqual(self.set_rule(next_rank=str(self.base_rank.pk)).status_code, 400)  # must be more senior

    def test_a_rule_can_be_changed_and_removed(self):
        self.set_rule(24)
        self.set_rule(36)
        self.assertEqual(PromotionRule.objects.get(rank=self.base_rank).min_months, 36)
        r = self.sa.post(P + "rules/set/", {"rank": str(self.base_rank.pk), "remove": True}, format="json")
        self.assertEqual((r.status_code, PromotionRule.objects.count()), (204, 0))

    def test_rules_list_shows_ranks_with_and_without_a_rule(self):
        self.set_rule(18)
        rows = self.cmdr.get(P + "rules/").json()["results"]
        mine = next(x for x in rows if x["code"] == "PA-02")
        self.assertEqual(mine["rule"]["min_months"], 18)
        self.assertTrue(any(x["rule"] is None for x in rows))


class EligibilityTests(PromotionBase):
    def test_time_in_rank_against_the_rule(self):
        self.set_rule(24)
        old, new = self.served("Long Served", 40), self.served("Recent", 6)
        d = self.table()
        by = {r["personnel"]["id"]: r for r in d["results"]}
        self.assertEqual(by[str(old.pk)]["state"], "eligible")
        self.assertIsNotNone(by[str(old.pk)]["next_rank"])
        self.assertEqual((by[str(new.pk)]["state"], by[str(new.pk)]["required"]), ("not_yet", 24))
        self.assertTrue(0 < by[str(new.pk)]["months_left"] <= 24)
        self.assertEqual(by[str(old.pk)]["since_source"], "record")
        self.assertEqual({k: d["counts"][k] for k in ("eligible", "not_yet")}, {"eligible": 1, "not_yet": 1})

    def test_the_last_rank_change_decides_not_the_first_record(self):
        self.set_rule(24)
        p = self.served("Promoted Recently", 60)
        PersonnelHistory.objects.create(personnel=p, field="rank", old_ref="previous", new_ref=str(self.base_rank.pk), new_label="PA-03",
                                        effective_date=date.today() - timedelta(days=90), recorded_by_username="t")
        row = self.table()["results"][0]
        self.assertEqual((row["state"], row["since_source"]), ("not_yet", "history"))
        self.assertIn(row["months"], (2, 3))  # about 90 days

    def test_no_rule_means_no_verdict(self):
        self.served("Anyone", 100)
        d = self.table()
        self.assertEqual((d["results"][0]["state"], d["results"][0]["required"], d["counts"]["no_rule"]), ("no_rule", None, 1))

    def test_suspended_and_jailed_people_are_blocked_and_gone_people_are_left_out(self):
        self.set_rule(12)
        self.served("Suspended", 40, status="suspended")
        self.served("Retired", 40, status="retired")
        self.served("Fine", 40)
        d = self.table()
        self.assertEqual({r["personnel"]["full_name"]: r["state"] for r in d["results"]}, {"Suspended": "blocked", "Fine": "eligible"})

    def test_state_filter(self):
        self.set_rule(24)
        self.served("Long Served", 40)
        self.served("Recent", 6)
        self.assertEqual([r["personnel"]["full_name"] for r in self.table(state="eligible")["results"]], ["Long Served"])

    def test_scope_and_audit(self):
        self.set_rule(24)
        self.served("Long Served", 40)
        r = self.other.get(P + "eligibility/", {"org_unit": str(self.unit_a.pk)})
        self.assertEqual((r.status_code, r.json()["errors"]["org_unit"][0]["code"]), (400, "out_of_scope"))
        self.table()
        self.assertTrue(AuditEvent.objects.filter(action="promotion.read").exists())

    def test_a_member_cannot_see_eligibility(self):
        m = self.client_for(self.make_user("promo.member", "member", unit="BARI-ARMY-A"))
        self.assertEqual(m.get(P + "eligibility/", {"org_unit": str(self.unit_a.pk)}).status_code, 403)


class SuperAdministratorTests(PromotionBase):
    def test_sees_every_unit_and_can_set_the_rules(self):
        self.set_rule(12)
        self.served("Long Served", 40)
        d = self.table(c=self.sa)
        self.assertEqual(d["counts"]["eligible"], 1)
        far = self.client_for(self.make_user("promo.far", "unit_commander", unit="NUGAAL-ARMY-A"))
        self.assertEqual(far.get(P + "eligibility/", {"org_unit": str(self.unit_a.pk)}).status_code, 400)  # others stay in their scope


class NextRankTests(PromotionBase):
    def test_nobody_is_eligible_for_a_rank_that_is_not_approved(self):
        """PA-03's next rank, PA-04, is a draft in the fixture: it is not skipped, so nobody is promoted into it."""
        PromotionRule.objects.create(rank=self.rank("PA-03"), min_months=12)
        p = self.served("Waiting", 40, rank=self.rank("PA-03"))
        row = self.table()["results"][0]
        self.assertEqual((row["personnel"]["id"], row["state"]), (str(p.pk), "no_next"))


class ProposalTests(PromotionBase):
    """Eligible people become rank-change requests in the normal approval queue, with the Army order that authorizes them."""

    ORDER = {"order_ref": "PO-2026/14", "issuing_officer": "Commissioner", "order_date": "2026-11-01"}

    def setUp(self):
        super().setUp()
        self.set_rule(24)
        self.hq = self.client_for(self.make_user("promo.hqadmin", "hq_admin"))
        self.p1 = self.served("Long Served", 40)
        self.p2 = self.served("Also Long", 36)
        self.young = self.served("Recent", 3)

    def propose(self, people, c=None, **kw):
        body = {"items": [{"personnel": str(p.pk)} for p in people], **self.ORDER}
        body.update(kw)
        return (c or self.hq).post(P + "propose/", body, format="json")

    def test_an_hq_administrator_proposes_and_nothing_changes_until_it_is_decided(self):
        from apps.organization.models import ChangeRequest
        r = self.propose([self.p1, self.p2])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["count"], {x["status"] for x in r.json()["results"]}), (2, {"pending"}))
        reqs = ChangeRequest.objects.filter(kind="rank_change")
        self.assertEqual(reqs.count(), 2)
        one = reqs.get(payload__personnel=str(self.p1.pk))
        self.assertEqual((one.order_ref, one.issuing_officer, one.payload["rank"]), ("PO-2026/14", "Commissioner", str(self.rank("PA-03").pk)))
        self.assertIn("40 months in rank (minimum 24)", one.payload["reason"])
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.rank_id, self.base_rank.pk)  # still the old rank
        self.assertTrue(AuditEvent.objects.filter(action="promotion.propose").exists())

    def test_the_super_administrator_s_own_proposal_is_applied_at_once_like_everywhere_in_the_queue(self):
        r = self.propose([self.p1], c=self.sa)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["results"][0]["status"], r.json()["results"][0]["self_approved"]), ("approved", True))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.rank_id, self.rank("PA-03").pk)

    def test_someone_who_is_not_eligible_cannot_be_proposed_and_nothing_is_created(self):
        from apps.organization.models import ChangeRequest
        r = self.propose([self.p1, self.young])
        self.assertEqual((r.status_code, r.json()["code"]), (400, "promotion_invalid"))
        self.assertEqual(r.json()["rows"], [{"index": 1, "code": "not_eligible", "state": "not_yet"}])
        self.assertEqual(ChangeRequest.objects.count(), 0)  # the eligible person was not proposed either

    def test_the_order_is_required(self):
        from apps.organization.models import ChangeRequest
        r = self.propose([self.p1], order_ref="")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()["rows"][0]["code"], "order_required")
        self.assertEqual(ChangeRequest.objects.count(), 0)

    def test_a_person_cannot_be_proposed_twice_while_one_is_waiting(self):
        self.assertEqual(self.propose([self.p1]).status_code, 201)
        r = self.propose([self.p1])
        self.assertEqual((r.status_code, r.json()["rows"][0]["code"]), (400, "already_pending"))

    def test_duplicates_and_unknown_people_are_reported(self):
        r = self.propose([self.p1, self.p1])
        self.assertEqual(r.json()["rows"], [{"index": 1, "code": "duplicate_entry"}])
        r = self.hq.post(P + "propose/", {"items": [{"personnel": "nope"}], **self.ORDER}, format="json")
        self.assertEqual(r.json()["rows"], [{"index": 0, "code": "personnel_not_found"}])
        self.assertEqual(self.hq.post(P + "propose/", {"items": [], **self.ORDER}, format="json").status_code, 400)

    def test_a_commander_cannot_propose_and_the_list_still_works_for_them(self):
        self.assertEqual(self.propose([self.p1], c=self.cmdr).status_code, 403)
        self.assertEqual(self.table()["counts"]["eligible"], 2)
