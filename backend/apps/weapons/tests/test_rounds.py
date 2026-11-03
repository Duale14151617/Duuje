"""Rounds held by soldiers and the superior's holdings report. Synthetic data only."""
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.logistics.models import InventoryCategory, StockLine, StockTransaction
from apps.personnel.models import Personnel
from datetime import date

from apps.weapons.models import SoldierRounds
from apps.weapons.tests.test_weapons import WeaponBase, W


class RoundsBase(WeaponBase):
    def setUp(self):
        super().setUp()
        InventoryCategory.objects.filter(code="ammunition").update(approval_status="approved")
        self.ammo = InventoryCategory.objects.get(code="ammunition")
        self.line = StockLine.objects.create(category=self.ammo, org_unit=self.unit_a, uom="rounds")
        r = self.armourer.post(f"/api/v1/logistics/ammunition/{self.line.pk}/movement/",
                               {"kind": "opening", "quantity": 1000, "reason": "Carried forward"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def rounds(self, kind, qty, person=None, c=None, **kw):
        body = {"personnel": str((person or self.s1).pk), "stock_line": str(self.line.pk), "kind": kind, "quantity": qty, **kw}
        return (c or self.armourer).post(f"{W}rounds/", body, format="json")

    def give(self, qty=90, ref="V1", **kw):
        return self.rounds("issue", qty, reference=ref, **kw)

    def store(self):
        self.line.refresh_from_db()
        return self.line.quantity


class RoundsTests(RoundsBase):
    def test_issue_moves_rounds_from_the_store_to_the_soldier(self):
        r = self.give(90)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["held"], r.json()["store_balance"]), (90, 910))
        self.assertEqual(self.store(), 910)
        self.assertTrue(StockTransaction.objects.filter(stock_line=self.line, kind="issue", delta=-90, external_ref="V1").exists())

    def test_a_voucher_is_needed_and_cannot_be_used_twice(self):
        self.assertEqual(self.codes(self.rounds("issue", 10), "reference"), ["voucher_required"])
        self.assertEqual(self.give(10, "V1").status_code, 201)
        self.assertEqual(self.codes(self.give(10, "V1"), "external_ref"), ["duplicate_movement"])
        self.assertEqual(self.store(), 990)
        self.assertEqual(SoldierRounds.objects.count(), 1)

    def test_cannot_issue_more_than_the_store_holds(self):
        self.assertEqual(self.codes(self.give(5000), "quantity"), ["insufficient_stock"])
        self.assertFalse(SoldierRounds.objects.exists())

    def test_expended_rounds_reduce_what_the_soldier_holds_not_the_store(self):
        self.give(90)
        r = self.rounds("expended", 30, note="Range practice")
        self.assertEqual((r.status_code, r.json()["held"], r.json()["store_balance"]), (201, 60, 910))
        self.assertEqual(self.codes(self.rounds("expended", 100, note="x"), "quantity"), ["rounds_exceed_held"])
        self.assertEqual(self.codes(self.rounds("expended", 5), "note"), ["reason_required"])

    def test_return_goes_back_to_the_store_and_cannot_exceed_what_is_held(self):
        self.give(90)
        self.rounds("expended", 30, note="Range practice")
        self.assertEqual(self.codes(self.rounds("return", 61, reference="R1"), "quantity"), ["rounds_exceed_held"])
        r = self.rounds("return", 60, reference="R1")
        self.assertEqual((r.status_code, r.json()["held"], r.json()["store_balance"]), (201, 0, 970))

    def test_lost_rounds_need_an_authorization(self):
        self.give(90)
        self.assertEqual(self.codes(self.rounds("lost", 5, note="Lost in the field"), "authority_ref"), ["authorization_required"])
        r = self.rounds("lost", 5, note="Lost in the field", authority_ref="Board 3/2026")
        self.assertEqual((r.status_code, r.json()["held"]), (201, 85))

    def test_only_serving_soldiers_of_the_unit_get_rounds(self):
        self.assertEqual(self.codes(self.give(10, "V2", person=self.away), "personnel"), ["person_outside_unit"])
        Personnel.objects.filter(pk=self.s2.pk).update(status="retired")
        self.assertEqual(self.codes(self.give(10, "V3", person=self.s2), "personnel"), ["person_not_serving"])
        self.assertEqual(self.store(), 1000)

    def test_the_ledger_is_append_only(self):
        self.give(90)
        row = SoldierRounds.objects.get()
        row.note = "edited"
        with self.assertRaises(AppendOnlyError):
            row.save()
        with self.assertRaises(AppendOnlyError):
            SoldierRounds.objects.all().delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SoldierRounds.objects.create(personnel=self.s1, stock_line=self.line, kind="issue", delta=-5)  # wrong sign for a kind

    def test_store_lines_offered_are_those_of_the_soldiers_unit_or_above(self):
        r = self.armourer.get(f"{W}ammo_lines/", {"org_unit": str(self.unit_a.pk)})
        self.assertEqual([x["id"] for x in r.json()["results"]], [str(self.line.pk)])
        r = self.armourer.get(f"{W}ammo_lines/", {"org_unit": str(self.unit_b.pk)})
        self.assertEqual(r.json()["results"], [])


class HoldingsReportTests(RoundsBase):
    def test_report_shows_weapons_and_rounds_left_per_soldier(self):
        w = self.weapon("AK-0001")
        self.assertEqual(self.issue(w).status_code, 200)  # weapon custody (WeaponBase.issue)
        self.give(90)
        self.rounds("expended", 30, note="Range practice")
        r = self.armourer.get(f"{W}holdings/", {"org_unit": str(self.unit_a.pk)})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["totals"], {"soldiers": 1, "weapons": 1, "rounds": 60})
        s = d["results"][0]
        self.assertEqual((s["personnel"]["service_number"], [x["serial"] for x in s["weapons"]]), ("S-1", ["AK-0001"]))
        line = s["rounds"]["lines"][0]
        self.assertEqual((line["issued"], line["expended"], line["returned"], line["lost"], line["held"]), (90, 30, 0, 0, 60))

    def test_report_can_also_list_soldiers_who_hold_nothing(self):
        self.give(10)
        d = self.armourer.get(f"{W}holdings/", {"org_unit": str(self.unit_a.pk), "all": "1"}).json()
        self.assertEqual({x["personnel"]["service_number"] for x in d["results"]}, {"S-1", "S-2"})

    def test_a_unit_commander_can_read_the_report_but_not_issue_rounds(self):
        self.give(10)
        cmdr = self.client_for(self.make_user("cmdr", "unit_commander", unit="BARI-ARMY-A"))
        self.assertEqual(cmdr.get(f"{W}holdings/").json()["totals"]["rounds"], 10)
        self.assertEqual(self.rounds("issue", 5, c=cmdr, reference="V9").status_code, 403)

    def test_report_is_limited_to_the_users_scope(self):
        self.give(10)
        far = self.client_for(self.make_user("far", "weapons_custodian", unit="NUGAAL-ARMY-A"))
        self.assertEqual(far.get(f"{W}holdings/").json()["totals"], {"soldiers": 0, "weapons": 0, "rounds": 0})
        member = self.client_for(self.make_user("mem", "member", unit="BARI-ARMY"))
        self.assertEqual(member.get(f"{W}holdings/").status_code, 403)


class LedgerConsistencyTests(RoundsBase):
    def statement(self):
        return self.armourer.get(f"/api/v1/logistics/ammunition/{self.line.pk}/statement/").json()

    def disposition(self, c=None, **q):
        return (c or self.armourer).get(f"{W}disposition/", {"stock_line": str(self.line.pk), **q})

    def test_issue_and_return_are_linked_one_to_one_to_the_unit_ledger(self):
        self.give(90, "V1")
        self.rounds("return", 40, reference="R1")
        rows = {r.kind: r for r in SoldierRounds.objects.all()}
        self.assertEqual((rows["issue"].store_transaction.kind, rows["issue"].store_transaction.delta, rows["issue"].store_transaction.external_ref), ("issue", -90, "V1"))
        self.assertEqual((rows["return"].store_transaction.kind, rows["return"].store_transaction.delta, rows["return"].store_transaction.external_ref), ("return", 40, "R1"))

    def test_fired_and_lost_rounds_are_never_a_second_store_deduction(self):
        self.give(90)
        self.rounds("expended", 30, note="Range practice")
        self.rounds("lost", 5, note="Lost in the field", authority_ref="Board 3/2026")
        self.assertEqual(self.store(), 910)
        self.assertFalse(StockTransaction.objects.filter(stock_line=self.line, kind__in=["expenditure", "loss"]).exists())
        self.assertEqual(SoldierRounds.objects.filter(kind__in=["expended", "lost"], store_transaction__isnull=False).count(), 0)
        st = self.statement()
        self.assertEqual((st["issued"], st["returned"], st["expended"], st["lost_damaged"], st["closing"]), (90, 0, 0, 0, 910))
        self.assertTrue(st["check"]["matches_balances"])

    def test_rounds_on_a_soldier_cannot_be_returned_through_the_general_ledger(self):
        self.give(90)
        r = self.armourer.post(f"/api/v1/logistics/ammunition/{self.line.pk}/movement/",
                               {"kind": "return", "quantity": 10, "external_ref": "X1"}, format="json")
        self.assertEqual(self.codes(r, "quantity"), ["return_exceeds_unassigned"])
        self.assertEqual(self.store(), 910)

    def test_rounds_issued_to_others_can_still_be_returned_through_the_general_ledger(self):
        self.armourer.post(f"/api/v1/logistics/ammunition/{self.line.pk}/movement/", {"kind": "issue", "quantity": 50, "external_ref": "O1"}, format="json")
        r = self.armourer.post(f"/api/v1/logistics/ammunition/{self.line.pk}/movement/", {"kind": "return", "quantity": 20, "external_ref": "O2"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_disposition_separates_store_from_soldiers_and_reconciles(self):
        self.give(90, "V1")
        self.give(60, "V2", person=self.s2)
        self.rounds("expended", 30, note="Range practice")
        self.rounds("lost", 5, note="Lost in the field", authority_ref="Board 3/2026")
        self.rounds("return", 20, reference="R1")
        self.armourer.post(f"/api/v1/logistics/ammunition/{self.line.pk}/movement/", {"kind": "issue", "quantity": 10, "external_ref": "O1"}, format="json")
        d = self.disposition().json()
        self.assertEqual((d["soldiers"]["issued"], d["soldiers"]["returned"], d["soldiers"]["expended"], d["soldiers"]["lost"], d["soldiers"]["held_end"]),
                         (150, 20, 30, 5, 95))
        st = d["store"]
        self.assertEqual((st["issued"], st["issued_to_soldiers"], st["issued_other"], st["returned"], st["returned_from_soldiers"], st["returned_other"]),
                         (160, 150, 10, 20, 20, 0))
        self.assertEqual(st["balance_end"], 1000 - 160 + 20)
        self.assertEqual(d["accountable_end"], st["balance_end"] + 95)  # store + on soldiers; fired and lost rounds are not counted again
        self.assertTrue(d["consistent"], d["checks"])
        by = {x["personnel"]["service_number"]: x for x in d["per_soldier"]}
        self.assertEqual((by["S-1"]["held"], by["S-2"]["held"]), (35, 60))

    def test_disposition_flags_a_row_that_does_not_match_the_unit_ledger(self):
        self.give(90)
        SoldierRounds.objects.create(personnel=self.s1, stock_line=self.line, kind="issue", delta=5, reference="BAD")  # no store movement
        d = self.disposition().json()
        self.assertFalse(d["consistent"])
        self.assertEqual(d["checks"]["unlinked_rows"], 1)
        self.assertFalse(d["checks"]["issues_match_store"])

    def test_disposition_respects_the_period(self):
        self.give(90)
        d = self.disposition(**{"from": "2000-01-01", "to": "2000-01-31"}).json()
        self.assertEqual((d["soldiers"]["issued"], d["soldiers"]["held_end"]), (0, 0))
        self.assertEqual(self.disposition(**{"from": "2026-02-01", "to": "2026-01-01"}).status_code, 400)

    def test_disposition_and_history_follow_the_reporting_permissions(self):
        self.give(90)
        cmdr = self.client_for(self.make_user("cmdr", "unit_commander", unit="BARI-ARMY-A"))
        self.assertEqual(self.disposition(c=cmdr).status_code, 200)
        far = self.client_for(self.make_user("far", "weapons_custodian", unit="NUGAAL-ARMY-A"))
        self.assertEqual(self.disposition(c=far).status_code, 400)
        member = self.client_for(self.make_user("mem", "member", unit="BARI-ARMY"))
        self.assertEqual(self.disposition(c=member).status_code, 403)
        self.assertEqual(member.get(f"{W}rounds_history/", {"personnel": str(self.s1.pk)}).status_code, 403)
        self.assertEqual(far.get(f"{W}rounds_history/", {"personnel": str(self.s1.pk)}).status_code, 400)

    def test_history_lists_every_movement_with_running_balance_and_links(self):
        self.give(90, "V1")
        self.rounds("expended", 30, note="Range practice")
        self.rounds("lost", 5, note="Lost in the field", authority_ref="Board 3/2026")
        self.rounds("return", 20, reference="R1")
        d = self.armourer.get(f"{W}rounds_history/", {"personnel": str(self.s1.pk)}).json()
        self.assertEqual([(r["kind"], r["quantity"], r["balance_after"]) for r in d["results"]],
                         [("return", 20, 35), ("lost", 5, 55), ("expended", 30, 60), ("issue", 90, 90)])
        self.assertEqual(d["held"], 35)
        by = {r["kind"]: r for r in d["results"]}
        self.assertEqual((by["lost"]["authority_ref"], by["lost"]["note"], by["issue"]["reference"]), ("Board 3/2026", "Lost in the field", "V1"))
        self.assertIsNotNone(by["issue"]["store_transaction"])
        self.assertIsNone(by["expended"]["store_transaction"])

    def test_every_rounds_action_is_audited(self):
        self.give(90)
        self.rounds("expended", 30, note="Range practice")
        self.rounds("lost", 5, note="x", authority_ref="Board 3/2026")
        self.rounds("return", 20, reference="R1")
        for kind in ("issue", "expended", "lost", "return"):
            self.assertTrue(AuditEvent.objects.filter(action=f"weapon.rounds_{kind}").exists(), kind)
        self.disposition()
        self.assertTrue(AuditEvent.objects.filter(action="weapon.read_disposition").exists())
