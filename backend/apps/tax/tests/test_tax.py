"""Vehicle and traffic taxes (cash, paper receipt): acceptance tests. Synthetic data only."""
from decimal import Decimal
from datetime import date, timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.personnel.tests.test_personnel import PersonnelBase
from apps.tax.models import TaxPayment, TaxType, TaxVehicle

URL = "/api/v1/tax/"


class TaxBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.unit_a = self.unit("BARI-ARMY-A")
        self.collector = self.client_for(self.make_user("collector", "tax_collector", unit="BARI-ARMY"))
        self.collector2 = self.client_for(self.make_user("collector2", "tax_collector", unit="BARI-ARMY"))
        self.cashier = self.client_for(self.make_user("cashier", "tax_cashier", unit="HQ"))
        self.nugaal = self.client_for(self.make_user("tax_n", "tax_collector", unit="NUGAAL-ARMY"))
        self.hq = self.client_for(self.make_user("hqadm_t", "hq_admin"))
        self.member = self.client_for(self.make_user("plain_t", "member", unit="BARI-ARMY"))
        self.licence = TaxType.objects.get(code="vehicle_licence")
        self.fine = TaxType.objects.get(code="traffic_fine")

    def vehicle(self, plate="GD-123", c=None, **kw):
        r = (c or self.collector).post(URL + "vehicles/create/", {"org_unit": str(self.unit_a.pk), "plate": plate, "owner_name": "Test Owner", **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def pay(self, v, receipt="R-1", t=None, c=None, **kw):
        body = {"vehicle": v["id"], "tax_type": str((t or self.licence).pk), "receipt_no": receipt, "amount": "25.00", **kw}
        return (c or self.collector).post(URL + "payments/create/", body, format="json")


class VehicleAndPaymentTests(TaxBase):
    def test_types_seeded_without_amounts(self):
        self.assertEqual(set(TaxType.objects.values_list("code", flat=True)) >= {"vehicle_licence", "road_tax", "traffic_fine", "permit_fee"}, True)
        self.assertTrue(all(t.default_amount is None for t in TaxType.objects.all()))

    def test_register_vehicle_and_duplicate_plate(self):
        self.vehicle("GD-123")
        r = self.collector.post(URL + "vehicles/create/", {"org_unit": str(self.unit_a.pk), "plate": "gd 123", "owner_name": "Other"}, format="json")
        self.assertEqual(r.status_code, 400)  # same plate ignoring case, spaces and dashes

    def test_payment_needs_amount_when_type_has_none_then_uses_default(self):
        v = self.vehicle()
        body = {"vehicle": v["id"], "tax_type": str(self.licence.pk), "receipt_no": "R-1"}
        self.assertEqual(self.collector.post(URL + "payments/create/", body, format="json").status_code, 400)
        TaxType.objects.filter(pk=self.licence.pk).update(default_amount="30.00")
        r = self.collector.post(URL + "payments/create/", body, format="json")
        self.assertEqual((r.status_code, r.data["amount"]), (201, "30.00"))

    def test_recurring_payment_sets_period_and_extends_cover(self):
        v = self.vehicle()
        first = self.pay(v, "R-1", paid_on=timezone.localdate().isoformat()).data
        self.assertIsNotNone(first["period_to"])
        second = self.pay(v, "R-2").data
        self.assertEqual(second["period_from"], str(date.fromisoformat(str(first["period_to"])) + timedelta(days=1)))
        detail = self.collector.get(f"{URL}{v['id']}/vehicle/").data
        self.assertFalse(detail["cover"][0]["overdue"])

    def test_one_off_type_has_no_period(self):
        v = self.vehicle()
        r = self.pay(v, "F-1", t=self.fine, reference="TICKET-9")
        self.assertEqual((r.status_code, r.data["period_to"]), (201, None))

    def test_receipt_number_cannot_repeat_until_voided(self):
        v = self.vehicle()
        p = self.pay(v, "R-1")
        self.assertEqual(self.pay(v, "R-1").status_code, 400)
        voided = self.collector.post(f"{URL}{p.data['id']}/payments/void/", {"version": 1, "reason": "Wrong plate"}, format="json")
        self.assertEqual(voided.status_code, 200, voided.data)
        self.assertEqual(self.pay(v, "R-1").status_code, 201)  # the number of a voided receipt can be reused
        self.assertEqual(TaxPayment.objects.count(), 2)

    def test_future_date_and_bad_amount(self):
        v = self.vehicle()
        self.assertEqual(self.pay(v, "R-1", paid_on=(timezone.localdate() + timedelta(days=2)).isoformat()).status_code, 400)
        self.assertEqual(self.pay(v, "R-2", amount="0").status_code, 400)
        self.assertEqual(self.pay(v, "R-3", amount="abc").status_code, 400)

    def test_overdue_filter(self):
        a, b = self.vehicle("AA-1"), self.vehicle("BB-2")
        self.pay(a, "R-1")
        listed = [x["plate"] for x in self.collector.get(URL + "vehicles/?overdue=1&type=vehicle_licence").data["results"]]
        self.assertEqual(listed, ["BB-2"])

    def test_delete_is_impossible(self):
        v = self.vehicle()
        self.pay(v)
        with self.assertRaises(AppendOnlyError):
            TaxPayment.objects.first().delete()
        with self.assertRaises(AppendOnlyError):
            TaxVehicle.objects.first().delete()


class HandoverTests(TaxBase):
    def handover(self, c=None, **kw):
        return (c or self.collector).post(URL + "handovers/create/", {"org_unit": str(self.unit_a.pk), **kw}, format="json")

    def test_handover_totals_and_locks_receipts(self):
        v = self.vehicle()
        p1 = self.pay(v, "R-1", amount="20.00").data
        self.pay(v, "R-2", amount="5.50")
        h = self.handover()
        self.assertEqual((h.status_code, h.data["expected_amount"], h.data["payments_count"]), (201, "25.50", 2))
        self.assertEqual(self.handover().status_code, 400)  # nothing left to hand over
        void = self.collector.post(f"{URL}{p1['id']}/payments/void/", {"version": 1, "reason": "x"}, format="json")
        self.assertEqual(void.status_code, 400)  # already in a handover

    def test_cash_must_be_counted_by_someone_else(self):
        v = self.vehicle()
        self.pay(v, "R-1", amount="20.00")
        h = self.handover().data
        own = self.collector.post(f"{URL}{h['id']}/handovers/confirm/", {"version": 1, "counted_amount": "20.00"}, format="json")
        self.assertEqual(own.status_code, 403)  # no tax.confirm at all
        ok = self.cashier.post(f"{URL}{h['id']}/handovers/confirm/", {"version": 1, "counted_amount": "20.00"}, format="json")
        self.assertEqual((ok.status_code, ok.data["difference"], ok.data["status"]), (200, "0.00", "confirmed"))

    def test_difference_needs_a_note_and_is_recorded(self):
        v = self.vehicle()
        self.pay(v, "R-1", amount="20.00")
        h = self.handover().data
        url = f"{URL}{h['id']}/handovers/confirm/"
        self.assertEqual(self.cashier.post(url, {"version": 1, "counted_amount": "18.00"}, format="json").status_code, 400)
        r = self.cashier.post(url, {"version": 1, "counted_amount": "18.00", "note": "Two dollars short"}, format="json")
        self.assertEqual((r.status_code, r.data["difference"]), (200, "-2.00"))
        self.assertTrue(AuditEvent.objects.filter(action="tax.handover_confirm").exists())

    def test_confirm_refuses_the_person_who_handed_over(self):
        from apps.tax.models import TaxHandover
        v = self.vehicle()
        self.pay(v, "R-1", amount="20.00")
        h = TaxHandover.objects.get(pk=self.handover().data["id"])
        h.handed_by_username = "cashier"  # the cash officer handed it over, so the same account cannot count it
        h.save()
        r = self.cashier.post(f"{URL}{h.pk}/handovers/confirm/", {"version": h.version, "counted_amount": "20"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)


class AccessTests(TaxBase):
    def test_scope_and_roles(self):
        v = self.vehicle()
        self.assertEqual(self.nugaal.get(f"{URL}{v['id']}/vehicle/").status_code, 404)
        self.assertEqual(len(self.nugaal.get(URL + "vehicles/").data["results"]), 0)
        self.assertEqual(self.pay(v, "R-9", c=self.nugaal).status_code, 404)
        self.assertEqual(self.member.get(URL + "vehicles/").status_code, 403)
        self.assertEqual(self.cashier.post(URL + "vehicles/create/", {"org_unit": str(self.unit_a.pk), "plate": "X", "owner_name": "Y"}, format="json").status_code, 403)

    def test_only_headquarters_configures_types(self):
        body = {"code": "parking", "name_en": "Parking"}
        self.assertEqual(self.collector.post(URL + "types/create/", body, format="json").status_code, 403)
        r = self.hq.post(URL + "types/create/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        upd = self.hq.post(f"{URL}{r.data['id']}/types/update/", {"version": 1, "default_amount": "12.50", "recurring": False}, format="json")
        self.assertEqual((upd.status_code, upd.data["default_amount"]), (200, "12.50"))

    def test_reads_are_audited_without_owner_names(self):
        v = self.vehicle()
        self.collector.get(URL + "vehicles/")
        self.collector.get(f"{URL}{v['id']}/vehicle/")
        events = AuditEvent.objects.filter(action__startswith="tax.")
        self.assertTrue(events.filter(action="tax.read_vehicle").exists())
        self.assertFalse(any("Test Owner" in str(e.metadata) for e in events))


class ReportAndExportTests(TaxBase):
    def test_collection_report_groups_and_flags_held_cash(self):
        a, b = self.vehicle("AA-1"), self.vehicle("BB-2")
        self.pay(a, "R-1", amount="20.00")
        self.pay(b, "R-2", amount="5.00", t=self.fine)
        gone = self.pay(b, "R-3", amount="9.00", t=self.fine).data
        self.collector.post(f"{URL}{gone['id']}/payments/void/", {"version": 1, "reason": "dup"}, format="json")
        r = self.collector.get(URL + "report/").data
        self.assertEqual(sum(float(x["total"]) for x in r["rows"]), 25.0)
        self.assertEqual(r["voided"], 1)
        self.assertEqual(Decimal(str(r["held_by_collectors"][0]["total"])), Decimal("25.00"))
        self.assertEqual(self.collector.get(URL + "report/?from=2026-02-01&to=2026-01-01").status_code, 400)
        self.assertEqual(len(self.nugaal.get(URL + "report/").data["rows"]), 0)  # other region sees nothing

    def test_overdue_export_lists_only_lapsed_and_is_audited(self):
        a, b = self.vehicle("AA-1"), self.vehicle("BB-2")
        self.pay(a, "R-1")
        self.pay(a, "R-1b", t=TaxType.objects.get(code="road_tax"))
        r = self.collector.get(URL + "overdue-export/").data
        self.assertEqual([x["plate"] for x in r["results"]], ["BB-2"])
        self.assertTrue(AuditEvent.objects.filter(action="tax.export_overdue").exists())
        self.assertEqual(self.member.get(URL + "overdue-export/").status_code, 403)
