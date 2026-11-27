"""Food stores, bulk entry: opening stock from a spreadsheet and one order issued to many units. Synthetic data only."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.logistics.models import FoodAllocation, FoodBatch, StockLine, StockTransaction
from apps.organization.models import OrganizationalUnit as OU

from .test_food import FoodBase, iso

OPEN = "/api/v1/logistics/food/receipts/opening-import/"
BULK = "/api/v1/logistics/food/allocations/bulk/"
HEAD = "unit_code,category_code,quantity,uom,expires_on,received_on,batch_ref,supplier,delivery_note_ref,reorder_level\n"


def upload(text, name="opening.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class OpeningBase(FoodBase):
    def setUp(self):
        super().setUp()
        self.c = OU.objects.get_or_create(code="BARI-ARMY-C", defaults={
            "name_en": "BARI-ARMY-C", "level": "unit", "parent": OU.objects.get(code="BARI-ARMY")})[0]

    def send(self, text, confirm=False, authority="Stock-taking certificate 1/2026", client=None, name="opening.csv", **over):
        body = {"file": upload(text, name), "authority_ref": authority}
        if confirm:
            body["confirm"] = "true"
        body.update(over)
        return (client or self.hq).post(OPEN, body, format="multipart")

    def ledger(self, unit):
        return StockLine.objects.filter(category=self.cat, org_unit=unit).first()


class OpeningImportTests(OpeningBase):
    def test_preview_checks_the_file_and_saves_nothing(self):
        r = self.send(HEAD + f"BARI-ARMY-A,food_rations,100,kg,{iso(60)},,B1,,,\n")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["total"], body["valid"], body["can_commit"], body["rows"]), (1, 1, True, []))
        self.assertEqual([(s["unit_code"], s["quantity"], s["batches"]) for s in body["stores"]], [("BARI-ARMY-A", 100, 1)])
        self.assertFalse(StockLine.objects.filter(category=self.cat).exists())
        self.assertFalse(FoodBatch.objects.exists())

    def test_confirm_creates_one_opening_entry_per_store_with_a_batch_per_row(self):
        text = (HEAD + f"BARI-ARMY-A,food_rations,100,kg,{iso(90)},,LATE,,,50\n"
                f"BARI-ARMY-A,food_rations,30,kg,{iso(10)},,SOON,,,\n"
                "BARI-ARMY-B,food_rations,\"1,200\",kg,,,,,,\n")
        r = self.send(text, confirm=True)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json(), {"rows": 3, "stores": 2, "quantity": 1330})
        self.assertEqual((self.qty(self.a), self.qty(self.b)), (130, 1200))
        opening = StockTransaction.objects.filter(kind="opening")
        self.assertEqual(opening.count(), 2)
        txn = opening.get(stock_line__org_unit=self.a)
        self.assertEqual((txn.delta, txn.authority_ref), (130, "Stock-taking certificate 1/2026"))
        batches = FoodBatch.objects.filter(stock_line__org_unit=self.a)
        self.assertEqual({(b.batch_ref, b.remaining, b.source, b.txn_id) for b in batches},
                         {("LATE", 100, "opening", txn.pk), ("SOON", 30, "opening", txn.pk)})
        self.assertEqual(self.ledger(self.a).reorder_level, 50)
        self.assertEqual(self.hq.get("/api/v1/logistics/food/warnings/").json()["unbatched"], [])
        self.assertTrue(AuditEvent.objects.filter(action="food.opening_import").exists())
        self.assertEqual(AuditEvent.objects.filter(action="food.opening_balance").count(), 2)

    def test_opening_batches_are_used_earliest_expiry_first(self):
        self.send(HEAD + f"BARI-ARMY-A,food_rations,100,kg,{iso(90)},,LATE,,,\nBARI-ARMY-A,food_rations,30,kg,{iso(10)},,SOON,,,\n", confirm=True)
        self.assertEqual(self.issue(40).status_code, 201)
        self.assertEqual({b.batch_ref: b.remaining for b in FoodBatch.objects.all()}, {"SOON": 0, "LATE": 90})

    def test_one_bad_row_means_nothing_is_saved(self):
        text = HEAD + "BARI-ARMY-A,food_rations,100,kg,,,,,,\nNO-SUCH-UNIT,food_rations,5,kg,,,,,,\n"
        r = self.send(text, confirm=True)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["code"], "import_has_errors")
        self.assertEqual(r.json()["rows"], [{"row": 3, "errors": ["unit_unknown"]}])
        self.assertFalse(StockTransaction.objects.exists())
        self.assertFalse(StockLine.objects.filter(category=self.cat).exists())

    def test_row_problems_are_reported_by_row_number(self):
        text = (HEAD
                + "BARI-ARMY-A,general_supplies,5,kg,,,,,,\n"            # row 2: not a food category
                + "BARI-ARMY-A,food_rations,0,kg,,,,,,\n"                 # row 3: quantity
                + "BARI-ARMY-A,food_rations,12.5,kg,,,,,,\n"              # row 4: not a whole number
                + "BARI-ARMY-A,food_rations,5,kg,31/12/2026,,,,,\n"       # row 5: date must be yyyy-mm-dd
                + f"BARI-ARMY-A,food_rations,5,kg,{iso(1)},{iso(5)},,,,\n"  # row 6: expires before delivery
                + "BARI-ARMY-A,food_rations,5,kg,,,,Nobody Ltd,,\n"       # row 7: unknown supplier
                )
        r = self.send(text)
        problems = {p["row"]: p["errors"] for p in r.json()["rows"]}
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["can_commit"])
        self.assertEqual(r.json()["stores"], [])
        self.assertEqual(problems[2], ["not_food_category"])
        self.assertEqual(problems[3], ["invalid_quantity"])
        self.assertEqual(problems[4], ["invalid_quantity"])
        self.assertEqual(problems[5], ["date_invalid"])
        self.assertEqual(problems[6], ["expires_before_received"])
        self.assertEqual(problems[7], ["supplier_unknown"])

    def test_unit_of_measure_must_agree_within_a_store(self):
        r = self.send(HEAD + "BARI-ARMY-A,food_rations,5,kg,,,,,,\nBARI-ARMY-A,food_rations,5,tonnes,,,,,,\n")
        self.assertEqual(r.json()["rows"], [{"row": 3, "errors": ["uom_mismatch"]}])

    def test_the_same_row_twice_is_refused(self):
        row = f"BARI-ARMY-A,food_rations,5,kg,{iso(30)},,B1,,,\n"
        self.assertEqual(self.send(HEAD + row + row).json()["rows"], [{"row": 3, "errors": ["duplicate_batch_row"]}])

    def test_a_store_with_stock_movements_cannot_be_given_an_opening_balance(self):
        self.receive(qty=10)
        r = self.send(HEAD + "BARI-ARMY-A,food_rations,5,kg,,,,,,\n", confirm=True)
        self.assertEqual((r.status_code, r.json()["rows"]), (409, [{"row": 2, "errors": ["store_has_movements"]}]))
        self.assertEqual(self.qty(self.a), 10)

    def test_the_same_file_cannot_be_imported_twice(self):
        text = HEAD + "BARI-ARMY-A,food_rations,5,kg,,,,,,\n"
        self.assertEqual(self.send(text, confirm=True).status_code, 201)
        r = self.send(text, confirm=True)
        self.assertEqual((r.status_code, r.json()["rows"][0]["errors"]), (409, ["store_has_movements"]))
        self.assertEqual(self.qty(self.a), 5)

    def test_supplier_is_matched_by_name_and_must_be_active(self):
        ok = self.send(HEAD + "BARI-ARMY-A,food_rations,5,kg,,,,test supplier,,\n")
        self.assertEqual(ok.json()["can_commit"], True)
        self.hq.patch(f"/api/v1/logistics/suppliers/{self.supplier['id']}/", {"active": False, "version": self.supplier["version"]}, format="json")
        r = self.send(HEAD + "BARI-ARMY-A,food_rations,5,kg,,,,Test Supplier,,\n")
        self.assertEqual(r.json()["rows"], [{"row": 2, "errors": ["supplier_inactive"]}])

    def test_a_date_already_past_is_accepted_for_stock_on_the_shelf(self):
        r = self.send(HEAD + f"BARI-ARMY-A,food_rations,5,kg,{iso(-20)},,,,,\n", confirm=True)
        self.assertEqual(r.status_code, 201, r.content)
        expired = [w for w in self.hq.get("/api/v1/logistics/food/warnings/").json()["expiring"] if w["expired"]]
        self.assertEqual(len(expired), 1)

    def test_file_problems(self):
        self.assertEqual(self.codes(self.send(HEAD, confirm=True), "file"), ["file_empty"])
        self.assertEqual(self.codes(self.send("unit_code,quantity\nA,1\n"), "file"), ["file_columns_invalid"])
        self.assertEqual(self.codes(self.send(HEAD + "A,B,1,,,,,,,\n", name="x.txt"), "file"), ["food_file_type_invalid"])
        self.assertEqual(self.codes(self.hq.post(OPEN, {"authority_ref": "x"}, format="multipart"), "file"), ["file_required"])
        r = self.send(HEAD + "BARI-ARMY-A,food_rations,5,kg,,,,,,\n", authority="")
        self.assertEqual(self.codes(r, "authority_ref"), ["authority_required"])

    def test_semicolon_separated_files_from_regional_excel_settings_work(self):
        text = HEAD.replace(",", ";") + "BARI-ARMY-A;food_rations;5;kg;;;;;;\n"
        r = self.send(text)
        self.assertEqual((r.json()["valid"], r.json()["can_commit"]), (1, True))

    def test_xlsx_files_are_read_with_real_dates_and_numbers(self):
        import datetime

        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["unit_code", "category_code", "quantity", "expires_on"])
        ws.append(["BARI-ARMY-A", "food_rations", 100.0, datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=30), datetime.time())])
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile("opening.xlsx", buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        r = self.hq.post(OPEN, {"file": f, "authority_ref": "Count 1", "confirm": "true"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(FoodBatch.objects.get().expires_on.isoformat(), iso(30))

    def test_only_people_who_manage_food_can_import(self):
        c = self.client_for(self.make_user("repopen", "hq_reporting"))
        self.assertEqual(self.send(HEAD + "BARI-ARMY-A,food_rations,5,kg,,,,,,\n", client=c).status_code, 403)


class BulkTransferTests(OpeningBase):
    def setUp(self):
        super().setUp()
        self.receive(qty=100)
        self.line = StockLine.objects.get(category=self.cat, org_unit=self.a)

    def bulk(self, lines, client=None, **over):
        body = {"stock_line": str(self.line.pk), "order_ref": "Order 9/2026", "issuing_officer": "Col. Example", "order_date": iso(0),
                "issue_note_prefix": "BT-7", "lines": lines}
        body.update(over)
        return (client or self.hq).post(BULK, body, format="json")

    def test_one_order_is_issued_to_several_units(self):
        r = self.bulk([{"to_unit": str(self.b.pk), "quantity": 30}, {"to_unit": str(self.c.pk), "quantity": 20, "issue_note_ref": "OWN-1"}])
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual((body["count"], body["quantity"]), (2, 50))
        self.assertEqual([(a["status"], a["issue_note_ref"], a["order_ref"]) for a in body["allocations"]],
                         [("issued", "BT-7-01", "Order 9/2026"), ("issued", "OWN-1", "Order 9/2026")])
        self.assertEqual((self.qty(self.a), self.qty(self.b), self.qty(self.c)), (50, 0, 0))  # arrives only on delivery, as for one allocation
        self.assertEqual(FoodAllocation.objects.filter(status="issued").count(), 2)
        self.assertTrue(AuditEvent.objects.filter(action="food.bulk_issue").exists())
        row = body["allocations"][0]
        self.assertEqual(self.act(row, "acknowledge", received_by_name="R", receipt_note_ref="RN-1").status_code, 200)
        self.assertEqual(self.qty(self.b), 30)

    def test_if_the_total_is_more_than_the_store_holds_nothing_is_issued(self):
        r = self.bulk([{"to_unit": str(self.b.pk), "quantity": 70}, {"to_unit": str(self.c.pk), "quantity": 40}])
        self.assertEqual(r.status_code, 409)
        self.assertEqual((r.json()["code"], r.json()["rows"]), ("bulk_has_errors", [{"row": 2, "errors": ["insufficient_stock"]}]))
        self.assertEqual((self.qty(self.a), FoodAllocation.objects.count()), (100, 0))

    def test_line_problems_are_reported_by_line_number(self):
        r = self.bulk([{"to_unit": str(self.b.pk), "quantity": 10},
                       {"to_unit": str(self.b.pk), "quantity": 10},          # same unit twice
                       {"to_unit": str(self.a.pk), "quantity": 10},          # the sending store itself
                       {"to_unit": "", "quantity": 10},                      # no unit
                       {"to_unit": str(self.c.pk), "quantity": 0}])          # no quantity
        self.assertEqual({p["row"]: p["errors"] for p in r.json()["rows"]},
                         {2: ["duplicate_unit"], 3: ["no_change"], 4: ["org_unit_invalid"], 5: ["invalid_quantity"]})
        self.assertEqual(FoodAllocation.objects.count(), 0)

    def test_every_allocation_needs_its_own_issue_note(self):
        a = self.bulk([{"to_unit": str(self.b.pk), "quantity": 5, "issue_note_ref": "N-1"},
                       {"to_unit": str(self.c.pk), "quantity": 5, "issue_note_ref": "N-1"}], issue_note_prefix="")
        self.assertEqual(a.json()["rows"], [{"row": 2, "errors": ["duplicate_issue_note"]}])
        b = self.bulk([{"to_unit": str(self.b.pk), "quantity": 5}], issue_note_prefix="")
        self.assertEqual(b.json()["rows"], [{"row": 1, "errors": ["issue_note_required"]}])
        self.assertEqual(self.bulk([{"to_unit": str(self.b.pk), "quantity": 5}]).status_code, 201)
        again = self.bulk([{"to_unit": str(self.c.pk), "quantity": 5}])  # BT-7-01 is already used on this store
        self.assertEqual(again.json()["rows"], [{"row": 1, "errors": ["duplicate_issue_note"]}])

    def test_the_order_details_are_required_and_the_list_must_not_be_empty(self):
        for field in ("order_ref", "issuing_officer", "order_date"):
            self.assertEqual(self.bulk([{"to_unit": str(self.b.pk), "quantity": 5}], **{field: ""}).status_code, 400, field)
        self.assertEqual(self.codes(self.bulk([]), "lines"), ["lines_required"])
        self.assertEqual(self.codes(self.bulk([{"to_unit": str(self.b.pk), "quantity": 1}] * 101), "lines"), ["too_many_lines"])

    def test_only_people_who_manage_food_can_issue_in_bulk(self):
        c = self.client_for(self.make_user("repbulk", "hq_reporting"))
        self.assertEqual(self.bulk([{"to_unit": str(self.b.pk), "quantity": 5}], client=c).status_code, 403)
