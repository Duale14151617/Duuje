"""Ammunition ledger: movements, vouchers, authorizations, balances from transactions, statement. Synthetic data only."""
from datetime import date

from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.logistics.models import InventoryCategory, Reconciliation, ReconciliationLine, StockLine, StockTransaction
from apps.personnel.tests.test_personnel import PersonnelBase

AM = "/api/v1/logistics/ammunition/"


class AmmoBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        InventoryCategory.objects.filter(code="ammunition").update(approval_status="approved")
        self.cat = InventoryCategory.objects.get(code="ammunition")
        self.unit_a = self.unit("BARI-ARMY-A")
        self.line = StockLine.objects.create(category=self.cat, org_unit=self.unit_a, uom="rounds")
        self.store = self.client_for(self.make_user("storekeeper", "restricted_custodian", unit="BARI-ARMY-A"))   # manage + restricted + reconcile
        self.armourer = self.client_for(self.make_user("armourer", "weapons_custodian", unit="BARI-ARMY-A"))      # manage + restricted, no reconcile

    def move(self, kind, quantity, c=None, line=None, **kw):
        return (c or self.store).post(f"{AM}{(line or self.line).pk}/movement/", {"kind": kind, "quantity": quantity, **kw}, format="json")

    def bal(self):
        self.line.refresh_from_db()
        return self.line.quantity

    def stock(self, qty=1000):
        self.assertEqual(self.move("opening", qty, reason="Carried forward").status_code, 201)


class MovementTests(AmmoBase):
    def test_opening_balance_starts_an_empty_ledger_once(self):
        self.stock(1000)
        self.assertEqual(self.bal(), 1000)
        self.assertEqual(self.codes(self.move("opening", 5, reason="again"), "kind"), ["opening_not_first"])

    def test_opening_cannot_follow_other_movements(self):
        self.assertEqual(self.move("receive", 50, external_ref="DN-1").status_code, 201)
        self.assertEqual(self.codes(self.move("opening", 5, reason="late"), "kind"), ["opening_not_first"])

    def test_receipts_issues_and_returns_need_a_voucher_number(self):
        self.stock()
        for kind in ("receive", "issue", "return"):
            self.assertEqual(self.codes(self.move(kind, 10), "external_ref"), ["voucher_required"], kind)
        self.assertEqual(self.bal(), 1000)

    def test_the_same_voucher_cannot_be_booked_twice(self):
        self.stock()
        self.assertEqual(self.move("receive", 100, external_ref="DN-7").status_code, 201)
        self.assertEqual(self.codes(self.move("receive", 100, external_ref="DN-7"), "external_ref"), ["duplicate_movement"])
        self.assertEqual(self.bal(), 1100)
        self.assertEqual(self.move("issue", 100, external_ref="DN-7").status_code, 201)   # a different kind of movement may reuse a number

    def test_database_refuses_a_duplicate_voucher_and_a_wrong_direction(self):
        self.stock()
        self.move("receive", 10, external_ref="X-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockTransaction.objects.create(stock_line=self.line, kind="receive", delta=5, balance_after=1015, external_ref="X-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockTransaction.objects.create(stock_line=self.line, kind="issue", delta=5, balance_after=1015)

    def test_issue_cannot_exceed_the_balance(self):
        self.stock(100)
        self.assertEqual(self.codes(self.move("issue", 101, external_ref="IS-1"), "quantity"), ["insufficient_stock"])
        self.assertEqual(self.bal(), 100)

    def test_balance_is_always_the_sum_of_the_movements(self):
        self.stock(1000)
        self.move("receive", 500, external_ref="R1"); self.move("issue", 300, external_ref="I1"); self.move("return", 50, external_ref="RT1")
        self.move("expenditure", 120, reason="Range practice"); self.move("loss", 10, reason="Lost in transit", authority_ref="Board 4/26")
        self.move("damage", 20, reason="Water damage", authority_ref="Board 5/26")
        total = sum(StockTransaction.objects.filter(stock_line=self.line).values_list("delta", flat=True))
        self.assertEqual((self.bal(), total), (1100, 1100))
        self.assertEqual(StockTransaction.objects.filter(stock_line=self.line).order_by("-created_at", "-id").first().balance_after, 1100)

    def test_returns_cannot_exceed_what_was_issued(self):
        self.stock()
        self.move("issue", 100, external_ref="I1")
        self.assertEqual(self.move("return", 60, external_ref="RT1").status_code, 201)
        self.assertEqual(self.codes(self.move("return", 50, external_ref="RT2"), "quantity"), ["return_exceeds_issued"])
        self.assertEqual(self.move("return", 40, external_ref="RT3").status_code, 201)

    def test_expenditure_losses_and_damage_must_be_explained_and_authorized(self):
        self.stock()
        self.assertEqual(self.codes(self.move("expenditure", 10), "reason"), ["reason_required"])
        self.assertEqual(self.codes(self.move("loss", 10, reason="Lost"), "authority_ref"), ["authorization_required"])
        self.assertEqual(self.codes(self.move("damage", 10, authority_ref="B1"), "reason"), ["reason_required"])
        self.assertEqual(self.bal(), 1000)

    def test_quantities_must_be_positive_whole_numbers_except_adjustments(self):
        self.stock()
        self.assertEqual(self.codes(self.move("receive", -5, external_ref="N1"), "quantity"), ["quantity_invalid"])
        self.assertEqual(self.codes(self.move("receive", 0, external_ref="N2"), "quantity"), ["quantity_invalid"])
        self.assertEqual(self.codes(self.move("explode", 5), "kind"), ["invalid_kind"])

    def test_every_movement_is_audited_with_its_references(self):
        self.stock()
        self.move("receive", 10, external_ref="DN-9")
        e = AuditEvent.objects.filter(action="ammunition.receive").first()
        self.assertEqual(e.metadata["external_ref"], "DN-9")


class AdjustmentTests(AmmoBase):
    def test_an_adjustment_needs_reason_authorization_and_the_reconcile_authority(self):
        self.stock()
        self.assertEqual(self.codes(self.move("adjust", -5, reason="count"), "authority_ref"), ["authorization_required"])
        self.assertEqual(self.codes(self.move("adjust", -5, authority_ref="Order 1"), "reason"), ["reason_required"])
        r = self.move("adjust", -5, c=self.armourer, reason="count", authority_ref="Order 1")   # no logistics.reconcile
        self.assertEqual(self.codes(r, "kind"), ["adjust_not_authorized"])
        self.assertEqual(self.bal(), 1000)

    def test_an_adjustment_keeps_the_original_values_and_who_authorized_it(self):
        self.stock(1000)
        before = list(StockTransaction.objects.filter(stock_line=self.line).values("id", "delta", "balance_after", "reason"))
        r = self.move("adjust", -30, reason="Recount short", authority_ref="Board 9/26")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.bal(), 970)
        self.assertEqual(list(StockTransaction.objects.filter(stock_line=self.line).order_by("created_at").values("id", "delta", "balance_after", "reason"))[:1], before)
        adj = StockTransaction.objects.get(stock_line=self.line, kind="adjust")
        self.assertEqual((adj.authority_ref, adj.reason, adj.actor_username, adj.delta), ("Board 9/26", "Recount short", "storekeeper", -30))

    def test_an_adjustment_cannot_drive_the_balance_negative(self):
        self.stock(10)
        self.assertEqual(self.codes(self.move("adjust", -11, reason="x", authority_ref="B"), "quantity"), ["insufficient_stock"])

    def test_the_ledger_rows_are_append_only(self):
        self.stock()
        txn = StockTransaction.objects.get(stock_line=self.line)
        txn.delta = 5
        with self.assertRaises(Exception):
            txn.save()


class AccessTests(AmmoBase):
    def test_only_authorized_users_can_see_or_post(self):
        self.stock()
        for user in (self.make_user("uadm", "unit_admin", unit="BARI-ARMY-A"), self.make_user("mem", "member", unit="BARI-ARMY")):
            c = self.client_for(user)
            self.assertEqual(c.get(AM).status_code, 403, user.username)
            self.assertEqual(self.move("receive", 5, c=c, external_ref="Z").status_code, 403, user.username)
        self.assertEqual(self.bal(), 1000)

    def test_a_unit_commander_can_read_but_not_post(self):
        self.stock()
        cmdr = self.client_for(self.make_user("cmdr", "unit_commander", unit="BARI-ARMY-A"))
        self.assertEqual(cmdr.get(f"{AM}{self.line.pk}/statement/").status_code, 200)
        self.assertEqual(self.move("issue", 5, c=cmdr, external_ref="Q1").status_code, 403)

    def test_the_general_stock_route_cannot_post_to_ammunition(self):
        self.stock()
        r = self.store.post(f"/api/v1/logistics/stock/{self.line.pk}/transactions/", {"kind": "receive", "quantity": 5}, format="json")
        self.assertEqual(self.codes(r, "category"), ["use_ammunition_ledger"])
        self.assertEqual(self.bal(), 1000)

    def test_scope_limits_other_units(self):
        far = self.client_for(self.make_user("far", "restricted_custodian", unit="NUGAAL-ARMY-A"))
        self.assertEqual(far.get(f"{AM}{self.line.pk}/statement/").status_code, 404)
        self.assertEqual(self.move("receive", 5, c=far, external_ref="F1").status_code, 404)


class StatementTests(AmmoBase):
    def test_statement_reports_every_kind_and_closes_correctly(self):
        self.stock(1000)
        self.move("receive", 500, external_ref="R1"); self.move("issue", 300, external_ref="I1"); self.move("return", 50, external_ref="RT1")
        self.move("expenditure", 120, reason="Range"); self.move("loss", 10, reason="Lost", authority_ref="B1")
        self.move("damage", 20, reason="Wet", authority_ref="B2"); self.move("adjust", 5, reason="Found", authority_ref="B3")
        self.move("adjust", -3, reason="Short", authority_ref="B4")
        s = self.store.get(f"{AM}{self.line.pk}/statement/").json()
        got = {k: s[k] for k in ("balance_start", "opening_recorded", "received", "returned", "adjusted_up", "issued", "expended",
                                 "lost_damaged", "adjusted_down", "transferred_out", "closing")}
        self.assertEqual(got, {"balance_start": 0, "opening_recorded": 1000, "received": 500, "returned": 50, "adjusted_up": 5,
                               "issued": 300, "expended": 120, "lost_damaged": 30, "adjusted_down": 3, "transferred_out": 0, "closing": 1102})
        self.assertEqual((s["check"]["computed_closing"], s["check"]["matches_balances"], s["check"]["matches_current"]), (1102, True, True))
        self.assertEqual(len(s["transactions"]), 9)

    def test_a_later_period_starts_from_the_earlier_closing_balance(self):
        self.stock(1000)
        self.move("issue", 100, external_ref="I1")
        today = date.today().isoformat()
        s = self.store.get(f"{AM}{self.line.pk}/statement/", {"from": today, "to": today}).json()
        self.assertEqual((s["balance_start"], s["closing"]), (0, 900))
        nxt = self.store.get(f"{AM}{self.line.pk}/statement/", {"from": "2999-01-01", "to": "2999-01-31"}).json()
        self.assertEqual((nxt["balance_start"], nxt["closing"], nxt["transactions"]), (900, 900, []))

    def test_reconciliation_discrepancies_appear_and_open_ones_are_outstanding(self):
        self.stock(1000)
        open_rec = Reconciliation.objects.create(org_unit=self.unit_a, includes_restricted=True)
        ReconciliationLine.objects.create(reconciliation=open_rec, stock_line=self.line, label="Ammo", expected_quantity=1000, counted_quantity=990)
        s = self.store.get(f"{AM}{self.line.pk}/statement/").json()
        self.assertEqual((s["outstanding_discrepancies"], s["reconciliations"][0]["variance"]), (1, -10))

    def test_the_situation_report_figures_reconcile_with_the_ledger(self):
        from apps.attendance.situation import compute_figures
        self.stock(1000)
        self.move("receive", 200, external_ref="R1"); self.move("issue", 300, external_ref="I1"); self.move("return", 50, external_ref="RT1")
        self.move("expenditure", 100, reason="Range"); self.move("loss", 10, reason="Lost", authority_ref="B1")
        cmdr = self.make_user("cmdr2", "unit_commander", unit="BARI-ARMY-A")
        today = date.today()
        f = compute_figures(cmdr, self.unit_a, today, today)
        parts = (f["ammo_balance_start"] + f["ammo_opening_recorded"] + f["ammo_received"] + f["ammo_returned"] + f["ammo_adjusted_up"]
                 - f["ammo_issued"] - f["ammo_expended"] - f["ammo_lost_damaged"] - f["ammo_adjusted_down"] - f["ammo_transferred_out"])
        self.assertEqual((f["ammo_remaining"], parts), (840, 840))
        self.assertEqual((f["ammo_issued"], f["ammo_returned"], f["ammo_expended"], f["ammo_lost_damaged"]), (300, 50, 100, 10))
