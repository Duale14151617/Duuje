"""PPE ledger, asset lifecycle, procurement cost and the dashboard figures. Synthetic data only."""
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.logistics.models import Asset, InventoryCategory, StockLine, StockTransaction
from apps.personnel.tests.test_personnel import PersonnelBase
from apps.ppe.models import PpeMovement

P = "/api/v1/ppe/"
L = "/api/v1/logistics/"


class PpeBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        InventoryCategory.objects.all().update(approval_status="approved")
        self.cat = InventoryCategory.objects.get(code="ppe_helmets")
        self.unit_a = self.unit("BARI-ARMY-A")
        self.cust = self.client_for(self.make_user("ppe_cust", "logistics_custodian", unit="BARI-ARMY"))
        self.nug = self.client_for(self.make_user("ppe_nug", "logistics_custodian", unit="NUGAAL-ARMY"))
        self.line = StockLine.objects.create(category=self.cat, org_unit=self.unit_a, quantity=0)
        self.s1 = self.person("BARI-ARMY-A", "Rifleman One", rank="PA-03", service_number="S-1")
        r = self.cust.post(f"{L}stock/{self.line.pk}/transactions/", {"kind": "receive", "quantity": 100, "external_ref": "GRN-1",
                                                                       "unit_cost": "42.50", "currency": "usd"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def move(self, kind, qty, c=None, **kw):
        body = {"personnel": str(self.s1.pk), "kind": kind, "quantity": qty, **kw}
        return (c or self.cust).post(f"{P}{self.line.pk}/movement/", body, format="json")

    def store(self):
        self.line.refresh_from_db()
        return self.line.quantity


class PpeLedgerTests(PpeBase):
    def test_procurement_cost_is_recorded_and_shown_to_report_users(self):
        t = StockTransaction.objects.get(stock_line=self.line, kind="receive")
        self.assertEqual((str(t.unit_cost), t.currency), ("42.50", "USD"))
        s = self.cust.get(P + "summary/").json()
        self.assertEqual(s["procurement"]["by_currency"][0]["total"], "4250.00")

    def test_issue_return_keep_store_and_person_in_step(self):
        self.assertEqual(self.move("issue", 5, reference="V1", size="L").status_code, 201)
        self.assertEqual(self.store(), 95)
        self.assertEqual(self.move("return", 2, reference="R1").status_code, 201)
        self.assertEqual((self.store(), PpeMovement.objects.filter(personnel=self.s1).count()), (97, 2))
        h = self.cust.get(P + f"holder/?personnel={self.s1.pk}").json()
        self.assertEqual(h["holdings"][0]["held"], 3)

    def test_cannot_return_more_than_held_and_voucher_is_required(self):
        self.assertIn("voucher_required", self.codes(self.move("issue", 1), "reference"))
        self.move("issue", 2, reference="V1")
        self.assertIn("ppe_exceeds_held", self.codes(self.move("return", 3, reference="R1"), "quantity"))

    def test_damage_and_loss_write_off_the_person_not_the_store(self):
        self.move("issue", 4, reference="V1")
        self.assertIn("reason_required", self.codes(self.move("damaged", 1), "note"))
        self.assertEqual(self.move("damaged", 1, note="Cracked shell").status_code, 201)
        self.assertIn("authorization_required", self.codes(self.move("lost", 1, note="Lost in transit"), "authority_ref"))
        self.assertEqual(self.store(), 96)  # unchanged by write-offs

    def test_replace_pairs_write_off_and_new_issue(self):
        self.move("issue", 1, reference="V1")
        r = self.cust.post(f"{P}{self.line.pk}/replace/", {"personnel": str(self.s1.pk), "quantity": 1, "out_kind": "damaged",
                                                         "note": "Cracked", "reference": "V2"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        rows = PpeMovement.objects.filter(personnel=self.s1).exclude(kind="issue", reference="V1")
        self.assertEqual({x.group for x in rows}.__len__(), 1)
        self.assertEqual((self.store(), sum(m.delta for m in PpeMovement.objects.filter(personnel=self.s1))), (98, 1))

    def test_scope_and_serving_status_are_enforced(self):
        self.assertEqual(self.move("issue", 1, c=self.nug, reference="X").status_code, 404)  # other region's line is invisible
        away = self.person("BARI-ARMY-B", "Other Unit", rank="PA-03", service_number="S-9")
        r = self.cust.post(f"{P}{self.line.pk}/movement/", {"personnel": str(away.pk), "kind": "issue", "quantity": 1, "reference": "Z"}, format="json")
        self.assertIn("person_outside_unit", self.codes(r, "personnel"))

    def test_ledger_is_append_only_and_audited(self):
        self.move("issue", 1, reference="V1")
        m = PpeMovement.objects.get()
        with self.assertRaises(AppendOnlyError):
            m.delta = 9
            m.save()
        with self.assertRaises(AppendOnlyError):
            PpeMovement.objects.all().update(delta=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PpeMovement.objects.create(personnel=self.s1, stock_line=self.line, kind="issue", delta=-1)
        self.assertTrue(AuditEvent.objects.filter(action="ppe.issue").exists())

    def test_inspection_summary_counts_due_and_never_inspected(self):
        self.move("issue", 1, reference="V1")
        self.assertEqual(self.cust.get(P + "summary/").json()["inspection"]["never_inspected"], 1)
        r = self.cust.post(f"{P}{self.line.pk}/inspect/", {"personnel": str(self.s1.pk), "condition": "fair",
                                                         "next_due": "2999-01-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        i = self.cust.get(P + "summary/").json()["inspection"]
        self.assertEqual((i["never_inspected"], i["inspected"], i["by_condition"]), (0, 1, {"fair": 1}))


class AssetLifecycleTests(PpeBase):
    def asset(self, ident="RADIO-1"):
        r = self.cust.post(L + "assets/", {"category": str(InventoryCategory.objects.get(code="communications_equipment").pk),
                                           "org_unit": str(self.unit_a.pk), "identifier": ident, "manufacturer": "Acme",
                                           "acquisition_cost": "100.00", "currency": "usd", "acquired_on": "2026-01-02",
                                           "procurement_ref": "PO-9"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_register_inspect_replace_keeps_one_chain_without_duplicates(self):
        a = self.asset()
        self.assertEqual((a["currency"], a["condition"]), ("USD", "good"))
        r = self.cust.post(f"{L}assets/{a['id']}/inspect/", {"condition": "unserviceable", "note": "Cracked", "version": a["version"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.cust.post(f"{L}assets/{a['id']}/replace/", {"identifier": "RADIO-2", "note": "Beyond repair", "version": r.json()["version"]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        old = Asset.objects.get(identifier="RADIO-1")
        self.assertEqual((old.status, old.replaced_by.identifier), ("retired", "RADIO-2"))
        self.assertEqual(Asset.objects.count(), 2)
        kinds = list(old.events.values_list("kind", flat=True))
        self.assertIn("inspection", kinds)
        self.assertIn("replaced", kinds)

    def test_details_edit_in_place_and_validation(self):
        a = self.asset()
        r = self.cust.post(f"{L}assets/{a['id']}/details/", {"procurement_ref": "PO-10", "version": a["version"]}, format="json")
        self.assertEqual((r.status_code, r.json()["procurement_ref"]), (200, "PO-10"))
        bad = self.cust.post(f"{L}assets/{a['id']}/details/", {"acquisition_cost": "-5", "currency": "USD", "version": r.json()["version"]}, format="json")
        self.assertIn("invalid_amount", self.codes(bad, "acquisition_cost"))
        self.assertEqual(Asset.objects.count(), 1)


class DashboardEquipmentTests(PpeBase):
    def test_dashboard_carries_fleet_and_equipment_blocks_from_the_database(self):
        self.move("issue", 3, reference="V1")
        d = self.cust.get("/api/v1/dashboard/").json()
        self.assertEqual(d["equipment"]["ppe"]["with_personnel"], 3)
        self.assertEqual(d["equipment"]["ppe"]["in_store"], 97)
