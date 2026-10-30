"""Food stores: suppliers, receipts with expiry, allocations with delivery acknowledgement, warnings. Synthetic data only."""
from datetime import date, timedelta

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.logistics.models import FoodBatch, InventoryCategory, StockLine, StockTransaction
from apps.organization.models import OrganizationalUnit as OU

S = "/api/v1/logistics/suppliers/"
R = "/api/v1/logistics/food/receipts/"
A = "/api/v1/logistics/food/allocations/"
W = "/api/v1/logistics/food/warnings/"


def iso(days):
    return (date.today() + timedelta(days=days)).isoformat()


class FoodBase(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code in ("BARI-ARMY-A", "BARI-ARMY-B"):
            OU.objects.create(code=code, name_en=code, level="unit", parent=OU.objects.get(code="BARI-ARMY"))
        InventoryCategory.objects.all().update(approval_status="approved")

    def setUp(self):
        super().setUp()
        self.hq = self.client_for(self.make_user("hqfood", "hq_admin"))
        self.sa = self.client_for(self.make_user("safood", "super_admin"))
        self.cat = InventoryCategory.objects.get(code="food_rations")
        self.a, self.b = OU.objects.get(code="BARI-ARMY-A"), OU.objects.get(code="BARI-ARMY-B")
        self.supplier = self.hq.post(S, {"name": "Test Supplier"}, format="json").json()

    def receive(self, qty=100, expires=60, note="DN-1", client=None, **over):
        body = {"category": str(self.cat.pk), "org_unit": str(self.a.pk), "supplier": self.supplier["id"], "quantity": qty,
                "expires_on": iso(expires) if expires is not None else None, "delivery_note_ref": note, "order_ref": "Order 5/2026", "uom": "kg"}
        body.update(over)
        return (client or self.hq).post(R, body, format="json")

    def issue(self, qty=40, note="IN-1", to=None, **over):
        line = StockLine.objects.get(category=self.cat, org_unit=self.a)
        body = {"stock_line": str(line.pk), "to_unit": str((to or self.b).pk), "quantity": qty, "order_ref": "Order 9/2026",
                "issuing_officer": "Col. Example", "order_date": iso(0), "issue_note_ref": note}
        body.update(over)
        return self.hq.post(A, body, format="json")

    def act(self, row, name, **body):
        return self.hq.post(f"{A}{row['id']}/{name}/", {"version": row["version"], **body}, format="json")

    def qty(self, unit):
        line = StockLine.objects.filter(category=self.cat, org_unit=unit).first()
        return line.quantity if line else 0


class SupplierTests(FoodBase):
    def test_duplicate_names_are_refused_and_suppliers_can_be_switched_off(self):
        self.assertEqual(self.hq.post(S, {"name": "test supplier"}, format="json").status_code, 400)
        r = self.hq.patch(f"{S}{self.supplier['id']}/", {"active": False, "version": self.supplier["version"]}, format="json")
        self.assertEqual((r.status_code, r.json()["active"]), (200, False))
        self.assertEqual(self.receive().status_code, 400)  # an inactive supplier cannot be used

    def test_roles_without_food_permissions_are_refused(self):
        c = self.client_for(self.make_user("repfood", "hq_reporting"))
        self.assertEqual(c.get(S).status_code, 403)
        self.assertEqual(c.post(S, {"name": "X"}, format="json").status_code, 403)


class ReceiptTests(FoodBase):
    def test_receipt_updates_the_ledger_with_the_references(self):
        r = self.receive()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.qty(self.a), 100)
        t = StockTransaction.objects.get(stock_line__category=self.cat, kind="receive")
        self.assertEqual((t.external_ref, t.authority_ref, t.delta), ("DN-1", "Order 5/2026", 100))
        self.assertTrue(AuditEvent.objects.filter(action="food.receive").exists())

    def test_validation(self):
        self.assertEqual(self.receive(qty=0).status_code, 400)
        self.assertEqual(self.receive(note="").status_code, 400)
        self.assertEqual(self.receive(order_ref="").status_code, 400)
        self.assertEqual(self.receive(expires=-5, received_on=iso(0)).status_code, 400)
        general = InventoryCategory.objects.get(code="general_supplies")
        self.assertEqual(self.receive(category=str(general.pk)).status_code, 400)
        self.assertEqual(self.qty(self.a), 0)

    def test_the_same_delivery_note_cannot_be_entered_twice(self):
        self.assertEqual(self.receive().status_code, 201)
        self.assertEqual(self.receive(note="DN-1").status_code, 400)
        self.assertEqual(self.qty(self.a), 100)

    def test_listing_is_audited(self):
        self.receive()
        r = self.hq.get(R)
        self.assertEqual((r.status_code, len(r.json()["results"])), (200, 1))
        self.assertTrue(AuditEvent.objects.filter(action="food.receipts_list").exists())


class AllocationTests(FoodBase):
    def test_stock_leaves_at_issue_and_arrives_only_when_delivery_is_recorded(self):
        self.receive()
        row = self.issue(40).json()
        self.assertEqual((row["status"], self.qty(self.a), self.qty(self.b)), ("issued", 60, 0))
        r = self.act(row, "acknowledge", received_by_name="Capt. Receiver", receipt_note_ref="RN-1")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.qty(self.a), self.qty(self.b)), (60, 40))
        out = StockTransaction.objects.get(kind="transfer_out", stock_line__org_unit=self.a)
        into = StockTransaction.objects.get(kind="transfer_in", stock_line__org_unit=self.b)
        self.assertEqual(out.group, into.group)

    def test_order_and_notes_are_required_and_insufficient_stock_is_refused(self):
        self.receive(qty=10)
        for field in ("order_ref", "issuing_officer", "issue_note_ref", "order_date"):
            self.assertEqual(self.issue(5, **{field: ""}).status_code, 400, field)
        self.assertEqual(self.issue(11).status_code, 400)
        self.assertEqual(self.qty(self.a), 10)

    def test_earliest_expiry_is_used_first_and_travels_with_the_food(self):
        self.receive(qty=50, expires=90, note="LATE")
        self.receive(qty=30, expires=10, note="SOON")
        row = self.issue(40).json()
        soon = FoodBatch.objects.get(delivery_note_ref="SOON")
        late = FoodBatch.objects.get(delivery_note_ref="LATE")
        self.assertEqual((soon.remaining, late.remaining), (0, 40))
        self.act(row, "acknowledge", received_by_name="R", receipt_note_ref="RN-2")
        moved = FoodBatch.objects.filter(stock_line__org_unit=self.b).order_by("expires_on")
        self.assertEqual([(m.remaining, m.expires_on.isoformat()) for m in moved], [(30, iso(10)), (10, iso(90))])
        self.assertEqual(self.hq.get(W).json()["unbatched"], [])

    def test_cancel_returns_the_stock_and_the_batches(self):
        self.receive()
        row = self.issue(40).json()
        r = self.act(row, "cancel", reason="Order withdrawn")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "cancelled"))
        self.assertEqual((self.qty(self.a), self.qty(self.b)), (100, 0))
        self.assertEqual(FoodBatch.objects.get(delivery_note_ref="DN-1").remaining, 100)

    def test_no_second_decision_after_delivery_or_cancellation(self):
        self.receive()
        row = self.issue(40).json()
        self.act(row, "acknowledge", received_by_name="R", receipt_note_ref="RN-3")
        fresh = self.hq.get(f"{A}{row['id']}/").json()
        self.assertEqual(self.act(fresh, "cancel", reason="late").status_code, 409)
        self.assertEqual(self.act(fresh, "acknowledge", received_by_name="R", receipt_note_ref="RN-4").status_code, 409)
        self.assertEqual((self.qty(self.a), self.qty(self.b)), (60, 40))

    def test_acknowledgement_needs_the_receiver_and_the_delivery_note(self):
        self.receive()
        row = self.issue(40).json()
        self.assertEqual(self.act(row, "acknowledge", received_by_name="", receipt_note_ref="X").status_code, 400)
        self.assertEqual(self.act(row, "acknowledge", received_by_name="R", receipt_note_ref="").status_code, 400)
        self.assertEqual(self.qty(self.b), 0)

    def test_super_admin_can_also_act_and_everything_is_audited(self):
        self.receive(client=self.sa)
        self.assertTrue(AuditEvent.objects.filter(action="food.receive").exists())
        self.issue(10)
        self.assertTrue(AuditEvent.objects.filter(action="food.allocation_issue").exists())


class WarningTests(FoodBase):
    def test_low_stock_expiring_and_expired_are_flagged(self):
        self.receive(qty=100, expires=10, note="A1")
        self.receive(qty=20, expires=-3, note="A2", received_on=iso(-30))
        self.receive(qty=500, expires=300, note="A3")
        line = StockLine.objects.get(category=self.cat, org_unit=self.a)
        StockLine.objects.filter(pk=line.pk).update(reorder_level=1000)
        w = self.hq.get(W, {"days": 30}).json()
        self.assertEqual(len(w["low_stock"]), 1)
        flags = {e["batch_ref"] or "x": e["expired"] for e in w["expiring"]}
        self.assertEqual(sorted(e["expired"] for e in w["expiring"]), [False, True])
        self.assertEqual(len(w["expiring"]), 2)  # the 300-day batch is not listed
        self.assertEqual(w["unbatched"], [])
        self.assertTrue(flags is not None)

    def test_stock_adjusted_outside_the_module_shows_as_unbatched(self):
        self.receive(qty=100)
        line = StockLine.objects.get(category=self.cat, org_unit=self.a)
        StockLine.objects.filter(pk=line.pk).update(quantity=120)
        self.assertEqual(self.hq.get(W).json()["unbatched"][0]["ledger"], 120)

    def test_roles_without_food_view_are_refused(self):
        c = self.client_for(self.make_user("repfood2", "hq_reporting"))
        self.assertEqual(c.get(W).status_code, 403)


class OptionsTests(FoodBase):
    def test_options_list_food_categories_and_stores_for_hq_admins(self):
        self.receive()
        r = self.hq.get("/api/v1/logistics/food/options/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("food_rations", [c["code"] for c in r.json()["categories"]])
        self.assertEqual(r.json()["stores"][0]["quantity"], 100)
