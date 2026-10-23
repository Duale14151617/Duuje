from django.apps import apps as django_apps

from apps.accounts.models import Role, RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.core.testing import BaseApiTest
from apps.logistics.models import Asset, InventoryCategory, Reconciliation, StockLine, StockTransaction
from apps.organization.models import OrganizationalUnit as OU

L = "/api/v1/logistics/"


class LogisticsBase(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, parent in (("BARI-ARMY-A", "BARI-ARMY"), ("BARI-ARMY-B", "BARI-ARMY"), ("NUGAAL-ARMY-A", "NUGAAL-ARMY")):
            OU.objects.create(code=code, name_en=code, level="unit", parent=OU.objects.get(code=parent))
        InventoryCategory.objects.all().update(approval_status="approved")  # tests of the approval flow use new categories

    def who(self, name, role, unit, branch=None):
        cache = self.__dict__.setdefault("_clients", {})
        if name not in cache:
            cache[name] = self.client_for(self.make_user(name, role, unit=unit, branch=branch))
        return cache[name]

    def cust(self):
        return self.who("cust", "logistics_custodian", "BARI-ARMY")

    def rcust(self):
        return self.who("rcust", "restricted_custodian", "BARI-ARMY")

    def nug(self):
        return self.who("nug", "logistics_custodian", "NUGAAL-ARMY")

    def cat(self, code):
        return InventoryCategory.objects.get(code=code)

    def line(self, unit="BARI-ARMY-A", cat="general_supplies", qty=40, reorder=0):
        return StockLine.objects.create(category=self.cat(cat), org_unit=self.unit(unit), quantity=qty, reorder_level=reorder)

    def asset(self, ident="VEH-001", unit="BARI-ARMY-A", cat="vehicles"):
        return Asset.objects.create(category=self.cat(cat), org_unit=self.unit(unit), identifier=ident)

    def tx(self, client, line, kind, quantity, **kw):
        return client.post(f"{L}stock/{line.pk}/transactions/", {"kind": kind, "quantity": quantity, **kw}, format="json")

    def change(self, client, asset, action, **kw):
        asset.refresh_from_db()
        return client.post(f"{L}assets/{asset.pk}/change/", {"action": action, "version": asset.version, **kw}, format="json")


class CategoryTests(LogisticsBase):
    def test_new_categories_are_draft_and_unusable_until_approved(self):
        adm = self.who("adm", "hq_admin", "HQ")
        r = adm.post(L + "categories/", {"code": "Fuel", "kind": "stock", "name_en": "Fuel", "name_so": "Shidaal"}, format="json")
        self.assertEqual((r.status_code, r.data["approval_status"], r.data["code"]), (201, "draft", "fuel"), r.data)
        cat = InventoryCategory.objects.get(code="fuel")
        r = self.cust().post(L + "stock/", {"category": str(cat.pk), "org_unit": str(self.unit("BARI-ARMY-A").pk)}, format="json")
        self.assertIn("category_not_approved", self.codes(r, "category"))

    def test_institutional_review_rules(self):
        adm, rev, cust = self.who("adm", "hq_admin", "HQ"), self.who("rev", "logistics_reviewer", "HQ"), self.cust()
        c = adm.post(L + "categories/", {"code": "fuel", "kind": "stock", "name_en": "Fuel"}, format="json").data
        self.assertEqual(rev.post(f"{L}categories/{c['id']}/approve/", {"version": 1}, format="json").data["code"], "somali_name_required")
        c = adm.patch(f"{L}categories/{c['id']}/", {"name_so": "Shidaal", "version": 1}, format="json").data
        self.assertEqual(adm.post(f"{L}categories/{c['id']}/approve/", {"version": c["version"]}, format="json").status_code, 403)
        self.assertEqual(cust.post(f"{L}categories/{c['id']}/approve/", {"version": c["version"]}, format="json").status_code, 403)
        ok = rev.post(f"{L}categories/{c['id']}/approve/", {"version": c["version"]}, format="json")
        self.assertEqual((ok.status_code, ok.data["approval_status"]), (200, "approved"), ok.data)
        renamed = adm.patch(f"{L}categories/{c['id']}/", {"name_en": "Diesel fuel", "version": ok.data["version"]}, format="json")
        self.assertEqual(renamed.data["approval_status"], "draft")  # a rename needs fresh review
        bad = adm.patch(f"{L}categories/{c['id']}/", {"kind": "asset", "version": renamed.data["version"]}, format="json")
        self.assertIn("immutable_field", self.codes(bad, "kind"))

    def test_creator_cannot_approve_their_own_category(self):
        both = self.make_user("both", "hq_admin", unit="HQ")
        RoleAssignment.objects.create(user=both, role=Role.objects.get(code="logistics_reviewer"), org_unit=self.unit("HQ"))
        c = self.client_for(User.objects.get(pk=both.pk))
        cat = c.post(L + "categories/", {"code": "x1", "kind": "stock", "name_en": "X", "name_so": "X"}, format="json").data
        r = c.post(f"{L}categories/{cat['id']}/approve/", {"version": 1}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (403, "self_approval_not_allowed"))
        self.assertTrue(AuditEvent.objects.filter(action="category.approve", outcome="denied", metadata__reason="self_approval").exists())

    def test_restricted_categories_are_hidden_from_ordinary_users(self):
        codes = lambda r: {c["code"] for c in r.data}
        self.assertNotIn("restricted_equipment", codes(self.cust().get(L + "categories/")))
        self.assertIn("restricted_equipment", codes(self.rcust().get(L + "categories/")))
        self.assertIn("restricted_equipment", codes(self.who("rev", "logistics_reviewer", "HQ").get(L + "categories/")))

    def test_only_headquarters_configures_categories(self):
        self.assertEqual(self.cust().post(L + "categories/", {"code": "z", "kind": "stock", "name_en": "Z"}, format="json").status_code, 403)
        self.assertEqual(self.who("chief", "regional_chief", "BARI").post(L + "categories/", {"code": "z", "kind": "stock", "name_en": "Z"}, format="json").status_code, 403)


class StockTests(LogisticsBase):
    def test_receive_issue_adjust_keep_an_exact_ledger(self):
        c, line = self.cust(), self.line(qty=0)
        self.assertEqual(self.tx(c, line, "receive", 100).data["quantity"], 100)
        self.assertEqual(self.tx(c, line, "issue", 30, reason="Field use").data["quantity"], 70)
        self.assertEqual(self.tx(c, line, "adjust", -5, reason="Damaged").data["quantity"], 65)
        ledger = c.get(f"{L}stock/{line.pk}/transactions/").data
        self.assertEqual([t["delta"] for t in ledger["results"]][::-1], [100, -30, -5])
        self.assertEqual(ledger["results"][0]["balance_after"], 65)
        self.assertEqual(sum(t["delta"] for t in ledger["results"]), StockLine.objects.get(pk=line.pk).quantity)

    def test_negative_stock_and_invalid_transactions_are_rejected(self):
        c, line = self.cust(), self.line(qty=10)
        r = self.tx(c, line, "issue", 11)
        self.assertEqual((r.status_code, self.codes(r, "quantity")), (400, ["insufficient_stock"]))
        self.assertEqual(StockLine.objects.get(pk=line.pk).quantity, 10)
        self.assertEqual(StockTransaction.objects.filter(stock_line=line).count(), 0)
        self.assertIn("quantity_invalid", self.codes(self.tx(c, line, "receive", 0), "quantity"))
        self.assertIn("quantity_invalid", self.codes(self.tx(c, line, "receive", -3), "quantity"))
        self.assertIn("quantity_invalid", self.codes(self.tx(c, line, "issue", -3), "quantity"))
        self.assertIn("reason_required", self.codes(self.tx(c, line, "adjust", 2), "reason"))
        self.assertEqual(self.tx(c, line, "burn", 1).status_code, 400)
        self.assertEqual(self.tx(c, line, "adjust", -11, reason="x").status_code, 400)  # would go negative
        self.assertEqual(StockLine.objects.get(pk=line.pk).quantity, 10)

    def test_stale_balance_guard(self):
        c, line = self.cust(), self.line(qty=10)
        self.tx(c, line, "receive", 5)
        r = self.tx(c, line, "issue", 1, expected_balance=10)
        self.assertEqual((r.status_code, r.data["code"]), (409, "balance_changed"))
        self.assertEqual(self.tx(c, line, "issue", 1, expected_balance=15).status_code, 200)

    def test_ledger_is_append_only(self):
        line = self.line(qty=5)
        self.tx(self.cust(), line, "receive", 1)
        t = StockTransaction.objects.get(stock_line=line)
        t.reason = "tampered"
        with self.assertRaises(AppendOnlyError):
            t.save()
        with self.assertRaises(AppendOnlyError):
            t.delete()
        with self.assertRaises(AppendOnlyError):
            StockTransaction.objects.filter(pk=t.pk).update(delta=99)

    def test_transfer_conserves_stock_and_pairs_transactions(self):
        c, src = self.cust(), self.line("BARI-ARMY-A", qty=50)
        r = c.post(f"{L}stock/{src.pk}/transfer/", {"to_unit": str(self.unit("BARI-ARMY-B").pk), "quantity": 20}, format="json")
        self.assertEqual((r.status_code, r.data["quantity"]), (200, 30), r.data)
        dest = StockLine.objects.get(org_unit=self.unit("BARI-ARMY-B"))
        self.assertEqual(dest.quantity, 20)
        t_out = StockTransaction.objects.get(stock_line=src)
        t_in = StockTransaction.objects.get(stock_line=dest)
        self.assertEqual((t_out.group, t_out.delta, t_in.delta), (t_in.group, -20, 20))
        too_much = c.post(f"{L}stock/{src.pk}/transfer/", {"to_unit": str(self.unit("BARI-ARMY-B").pk), "quantity": 31}, format="json")
        self.assertEqual(too_much.status_code, 400)
        self.assertEqual((StockLine.objects.get(pk=src.pk).quantity, StockLine.objects.get(pk=dest.pk).quantity), (30, 20))
        same = c.post(f"{L}stock/{src.pk}/transfer/", {"to_unit": str(self.unit("BARI-ARMY-A").pk), "quantity": 1}, format="json")
        self.assertIn("no_change", self.codes(same, "to_unit"))

    def test_cannot_push_stock_into_units_you_do_not_manage(self):
        src = self.line(qty=10)
        r = self.cust().post(f"{L}stock/{src.pk}/transfer/", {"to_unit": str(self.unit("NUGAAL-ARMY-A").pk), "quantity": 1}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(StockLine.objects.get(pk=src.pk).quantity, 10)

    def test_line_creation_rules(self):
        c, unit = self.cust(), str(self.unit("BARI-ARMY-A").pk)
        cat = lambda code: str(self.cat(code).pk)
        ok = c.post(L + "stock/", {"category": cat("general_supplies"), "org_unit": unit, "uom": "boxes", "reorder_level": 5}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        dup = c.post(L + "stock/", {"category": cat("general_supplies"), "org_unit": unit}, format="json")
        self.assertIn("stock_line_exists", self.codes(dup, "category"))
        wrong = c.post(L + "stock/", {"category": cat("vehicles"), "org_unit": unit}, format="json")
        self.assertIn("category_kind_mismatch", self.codes(wrong, "category"))
        region = c.post(L + "stock/", {"category": cat("uniforms_clothing"), "org_unit": str(self.unit("BARI").pk)}, format="json")
        self.assertIn("unit_level_invalid", self.codes(region, "org_unit"))

    def test_cross_scope_access_is_blocked(self):
        line = self.line("BARI-ARMY-A", qty=10)
        n = self.nug()
        self.assertEqual(n.get(L + "stock/").data["count"], 0)
        self.assertEqual(n.get(f"{L}stock/{line.pk}/").status_code, 404)
        self.assertEqual(self.tx(n, line, "receive", 1).status_code, 404)
        self.assertEqual(n.get(f"{L}stock/{line.pk}/transactions/").status_code, 404)
        out = n.post(L + "stock/", {"category": str(self.cat("general_supplies").pk), "org_unit": str(self.unit("BARI-ARMY-B").pk)}, format="json")
        self.assertEqual(out.status_code, 403)
        self.assertEqual(n.get(L + f"stock/?org_unit={self.unit('BARI').pk}").data["count"], 0)
        self.assertEqual(n.get(L + "stock/?category=abc").status_code, 400)

    def test_view_only_roles_cannot_change_stock_and_admin_has_no_inventory_access(self):
        line = self.line(qty=10)
        chief = self.who("chief", "regional_chief", "BARI")
        self.assertEqual(chief.get(f"{L}stock/{line.pk}/").status_code, 200)
        self.assertEqual(self.tx(chief, line, "receive", 1).status_code, 403)
        self.assertEqual(self.who("adm", "hq_admin", "HQ").get(L + "stock/").status_code, 403)

    def test_reorder_flag_and_filter(self):
        self.line("BARI-ARMY-A", qty=3, reorder=5)
        self.line("BARI-ARMY-B", qty=50, reorder=5)
        r = self.cust().get(L + "stock/?below_reorder=1")
        self.assertEqual([x["org_unit"]["code"] for x in r.data["results"]], ["BARI-ARMY-A"])
        self.assertTrue(r.data["results"][0]["below_reorder"])


class RestrictedAndAssetTests(LogisticsBase):
    def test_restricted_equipment_is_separately_permissioned(self):
        a = self.asset("RX-001", cat="restricted_equipment")
        self.assertEqual(self.cust().get(L + "assets/").data["count"], 0)
        self.assertEqual(self.cust().get(f"{L}assets/{a.pk}/").status_code, 404)
        self.assertEqual(self.who("chief", "regional_chief", "BARI").get(f"{L}assets/{a.pk}/").status_code, 404)
        self.assertEqual(self.rcust().get(f"{L}assets/{a.pk}/").status_code, 200)
        denied = self.cust().post(L + "assets/", {"category": str(self.cat("restricted_equipment").pk), "org_unit": str(self.unit("BARI-ARMY-A").pk),
                                                  "identifier": "RX-002"}, format="json")
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="access.denied", metadata__restricted=True).exists())
        ok = self.rcust().post(L + "assets/", {"category": str(self.cat("restricted_equipment").pk), "org_unit": str(self.unit("BARI-ARMY-A").pk),
                                               "identifier": "RX-002"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)

    def test_restricted_assets_cannot_be_changed_without_the_restricted_permission(self):
        a = self.asset("RX-003", cat="restricted_equipment")
        self.assertEqual(self.change(self.cust(), a, "maintenance").status_code, 404)  # not even visible
        self.assertEqual(self.change(self.rcust(), a, "maintenance").status_code, 200)

    def test_inventory_never_links_to_individual_personnel(self):
        for model in django_apps.get_app_config("logistics").get_models():
            for f in model._meta.get_fields():
                target = getattr(f, "related_model", None)
                self.assertFalse(target is not None and target._meta.app_label == "personnel", f"{model.__name__}.{f.name}")
        a = self.asset("VEH-100")
        r = self.change(self.cust(), a, "issue", to_unit=str(self.unit("BARI-ARMY-B").pk), personnel="someone", person="x")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("personnel", str(r.data).lower())

    def test_register_validation(self):
        c, unit, cat = self.cust(), str(self.unit("BARI-ARMY-A").pk), str(self.cat("vehicles").pk)
        ok = c.post(L + "assets/", {"category": cat, "org_unit": unit, "identifier": " veh-77 ", "description": "Truck"}, format="json")
        self.assertEqual((ok.status_code, ok.data["identifier"]), (201, "VEH-77"), ok.data)
        dup = c.post(L + "assets/", {"category": cat, "org_unit": unit, "identifier": "VEH-77"}, format="json")
        self.assertIn("asset_duplicate", self.codes(dup, "identifier"))
        bad = c.post(L + "assets/", {"category": cat, "org_unit": unit, "identifier": "no spaces!"}, format="json")
        self.assertIn("identifier_invalid", self.codes(bad, "identifier"))
        kind = c.post(L + "assets/", {"category": str(self.cat("general_supplies").pk), "org_unit": unit, "identifier": "A1"}, format="json")
        self.assertIn("category_kind_mismatch", self.codes(kind, "category"))

    def test_lifecycle_issue_return_and_status_rules(self):
        c, a = self.cust(), self.asset()
        b = str(self.unit("BARI-ARMY-B").pk)
        r = self.change(c, a, "issue", to_unit=b)
        self.assertEqual((r.status_code, r.data["status"], r.data["issued_to_unit"]["code"]), (200, "issued", "BARI-ARMY-B"))
        self.assertEqual(self.change(c, a, "issue", to_unit=b).data["code"], "invalid_transition")
        self.assertEqual(self.change(c, a, "maintenance").status_code, 409)
        self.assertEqual(self.change(c, a, "return").data["status"], "in_stock")
        self.assertEqual(self.change(c, a, "maintenance").data["status"], "maintenance")
        self.assertEqual(self.change(c, a, "restore").data["status"], "in_stock")
        self.assertIn("note_required", self.codes(self.change(c, a, "lost"), "note"))
        self.assertEqual(self.change(c, a, "lost", note="Not found after patrol").data["status"], "lost")
        self.assertEqual(self.change(c, a, "retire", note="Written off").data["status"], "retired")
        self.assertEqual(self.change(c, a, "restore").status_code, 409)  # retired is terminal
        events = c.get(f"{L}assets/{a.pk}/events/").data
        self.assertEqual([e["kind"] for e in events][::-1][:3], ["issue", "return", "maintenance"])
        a.refresh_from_db()
        self.assertEqual((a.status, a.issued_to_unit_id), ("retired", None))

    def test_issue_and_transfer_targets_are_checked(self):
        c, a = self.cust(), self.asset()
        r = self.change(c, a, "issue", to_unit=str(self.unit("NUGAAL-ARMY-A").pk))
        self.assertEqual(r.status_code, 403)
        r = self.change(c, a, "issue", to_unit=str(self.unit("BARI").pk))
        self.assertIn("unit_level_invalid", self.codes(r, "to_unit"))
        self.assertIn("required", self.codes(self.change(c, a, "issue"), "to_unit"))
        moved = self.change(c, a, "transfer", to_unit=str(self.unit("BARI-ARMY-B").pk))
        self.assertEqual((moved.status_code, moved.data["org_unit"]["code"]), (200, "BARI-ARMY-B"))

    def test_asset_changes_are_versioned_and_scoped(self):
        c, a = self.cust(), self.asset()
        c.post(f"{L}assets/{a.pk}/change/", {"action": "maintenance", "version": 1}, format="json")
        stale = c.post(f"{L}assets/{a.pk}/change/", {"action": "restore", "version": 1}, format="json")
        self.assertEqual((stale.status_code, stale.data["code"]), (409, "version_conflict"))
        self.assertEqual(self.change(self.nug(), a, "maintenance").status_code, 404)

    def test_custodianship_requires_an_authorised_custodian(self):
        a = self.asset()
        self.cust()
        c = self.cust()
        r = c.post(f"{L}assets/{a.pk}/custodian/", {"username": "cust", "version": 1}, format="json")
        self.assertEqual((r.status_code, r.data["custodian_username"]), (200, "cust"), r.data)
        self.nug()
        bad = c.post(f"{L}assets/{a.pk}/custodian/", {"username": "nug", "version": 2}, format="json")
        self.assertIn("custodian_not_authorised", self.codes(bad, "user"))
        restricted = self.asset("RX-9", cat="restricted_equipment")
        no = self.rcust().post(f"{L}assets/{restricted.pk}/custodian/", {"username": "cust", "version": 1}, format="json")
        self.assertIn("custodian_not_authorised", self.codes(no, "user"))  # ordinary custodian cannot hold restricted items

    def test_asset_filters(self):
        self.asset("A-1")
        self.asset("B-2", unit="BARI-ARMY-B")
        c = self.cust()
        self.assertEqual(c.get(L + "assets/?q=a-1").data["count"], 1)
        self.assertEqual(c.get(L + "assets/?status=issued").data["count"], 0)
        self.assertEqual(c.get(L + f"assets/?org_unit={self.unit('BARI-ARMY-B').pk}").data["count"], 1)


class ReconciliationTests(LogisticsBase):
    def start(self, client, unit="BARI-ARMY-A"):
        return client.post(L + "reconciliations/", {"org_unit": str(self.unit(unit).pk)}, format="json")

    def count(self, client, rec, answers):
        lines = [{"id": l["id"], **answers[l["label"].split(" ")[-1] if l["kind"] == "asset" else "stock"]} for l in rec["lines"]]
        return client.post(f"{L}reconciliations/{rec['id']}/count/", {"lines": lines}, format="json")

    def test_variances_become_adjustments_and_missing_assets_are_flagged(self):
        line, lost, there, found = self.line(qty=40), self.asset("V-1"), self.asset("V-2"), self.asset("V-3")
        Asset.objects.filter(pk=found.pk).update(status="missing")
        c = self.cust()
        rec = self.start(c).data
        self.assertEqual(len(rec["lines"]), 4)
        self.assertEqual(self.start(c).status_code, 400)  # one open reconciliation per unit
        early = c.post(f"{L}reconciliations/{rec['id']}/complete/", {"version": rec["version"]}, format="json")
        self.assertIn("reconciliation_incomplete", self.codes(early, "lines"))
        counted = self.count(c, rec, {"stock": {"counted_quantity": 35}, "V-1": {"found": False}, "V-2": {"found": True}, "V-3": {"found": True}})
        self.assertEqual(counted.status_code, 200, counted.data)
        done = c.post(f"{L}reconciliations/{rec['id']}/complete/", {"version": rec["version"]}, format="json")
        self.assertEqual((done.status_code, done.data["status"]), (200, "completed"), done.data)
        self.assertEqual(StockLine.objects.get(pk=line.pk).quantity, 35)
        adj = StockTransaction.objects.get(stock_line=line)
        self.assertEqual((adj.kind, adj.delta), ("adjust", -5))
        self.assertEqual([Asset.objects.get(pk=x.pk).status for x in (lost, there, found)], ["missing", "in_stock", "in_stock"])
        again = c.post(f"{L}reconciliations/{rec['id']}/complete/", {"version": done.data["version"]}, format="json")
        self.assertEqual(again.status_code, 409)

    def test_variance_is_measured_against_the_current_balance(self):
        line, c = self.line(qty=40), self.cust()
        rec = self.start(c).data
        self.tx(c, line, "receive", 10)  # stock moves while the count is under way
        self.count(c, rec, {"stock": {"counted_quantity": 45}})
        c.post(f"{L}reconciliations/{rec['id']}/complete/", {"version": rec["version"]}, format="json")
        self.assertEqual(StockLine.objects.get(pk=line.pk).quantity, 45)

    def test_rules_and_permissions(self):
        c = self.cust()
        self.assertIn("nothing_to_reconcile", self.codes(self.start(c, "BARI-ARMY-B"), "org_unit"))
        self.line()
        self.assertEqual(self.start(self.who("chief", "regional_chief", "BARI")).status_code, 403)  # no logistics.reconcile
        self.assertEqual(self.start(self.nug()).status_code, 403)  # wrong region
        rec = self.start(c).data
        cancelled = c.post(f"{L}reconciliations/{rec['id']}/cancel/", {"version": rec["version"]}, format="json")
        self.assertEqual(cancelled.data["status"], "cancelled")
        self.assertEqual(self.start(c).status_code, 201)  # a new one may start after cancelling
        bad = c.post(f"{L}reconciliations/{rec['id']}/count/", {"lines": [{"id": rec["lines"][0]["id"], "counted_quantity": 1}]}, format="json")
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(self.nug().get(f"{L}reconciliations/{rec['id']}/").status_code, 404)

    def test_count_validation(self):
        self.line()
        c = self.cust()
        rec = self.start(c).data
        for bad in ({"counted_quantity": -1}, {"counted_quantity": "7"}, {"found": True}, {}):
            r = c.post(f"{L}reconciliations/{rec['id']}/count/", {"lines": [{"id": rec["lines"][0]["id"], **bad}]}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        r = c.post(f"{L}reconciliations/{rec['id']}/count/", {"lines": [{"id": "00000000-0000-0000-0000-000000000000", "counted_quantity": 1}]}, format="json")
        self.assertIn("line_not_found", self.codes(r, "lines"))

    def test_restricted_items_only_in_restricted_reconciliations(self):
        self.asset("R-1", cat="restricted_equipment")
        self.asset("V-9")
        plain = self.start(self.cust()).data
        self.assertEqual([l["label"] for l in plain["lines"]], ["Vehicles V-9"])
        Reconciliation.objects.all().delete()
        full = self.start(self.rcust())
        self.assertEqual(full.status_code, 201, full.data)
        self.assertTrue(full.data["includes_restricted"])
        self.assertEqual(len(full.data["lines"]), 2)
        self.assertEqual(self.cust().get(f"{L}reconciliations/{full.data['id']}/").status_code, 404)  # invisible to ordinary custodians
        self.assertEqual(self.cust().get(L + "reconciliations/").data["count"], 0)


class SummaryTests(LogisticsBase):
    def test_summary_is_scoped_and_hides_restricted_rows(self):
        self.line("BARI-ARMY-A", qty=3, reorder=5)
        self.line("NUGAAL-ARMY-A", qty=7)
        self.asset("V-1")
        self.asset("RX-1", cat="restricted_equipment")
        rows = lambda r: {(x["category"]["code"], x["region"]["code"]): x for x in r.data["rows"]}
        cust = rows(self.cust().get(L + "summary/"))
        self.assertEqual(set(cust), {("general_supplies", "BARI"), ("vehicles", "BARI")})
        self.assertEqual((cust[("general_supplies", "BARI")]["quantity"], cust[("general_supplies", "BARI")]["below_reorder"]), (3, 1))
        self.assertEqual(cust[("vehicles", "BARI")]["assets"], {"in_stock": 1})
        r = rows(self.rcust().get(L + "summary/"))
        self.assertIn(("restricted_equipment", "BARI"), r)
        hq = rows(self.who("hqr", "hq_reporting", "HQ").get(L + "summary/"))
        self.assertEqual({k[1] for k in hq}, {"BARI", "NUGAAL"})
        self.assertNotIn(("restricted_equipment", "BARI"), hq)
        self.assertEqual(self.who("ro", "read_only", "BARI").get(L + "summary/").status_code, 403)
