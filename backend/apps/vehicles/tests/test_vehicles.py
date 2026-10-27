"""Military vehicle registry: acceptance tests. Synthetic data only; plates and names below are test placeholders."""
from datetime import date, timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.organization.models import OrganizationalUnit as OU
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase
from apps.vehicles.models import Vehicle, VehicleCategory, VehicleEvent

URL = "/api/v1/vehicles/"
PDF = b"%PDF-1.4 synthetic test document"


class VehicleBase(PersonnelBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        OU.objects.create(code="BARI-ARMY-A1", name_en="Battalion A1", level="unit", parent=OU.objects.get(code="BARI-ARMY-A"))

    def setUp(self):
        super().setUp()
        self.brig, self.bn, self.other = self.unit("BARI-ARMY-A"), self.unit("BARI-ARMY-A1"), self.unit("BARI-ARMY-B")
        self.officer = self.client_for(self.make_user("transport", "transport_officer", unit="BARI-ARMY"))
        self.approver = self.client_for(self.make_user("approver", "vehicle_disposal_approver", unit="HQ"))
        self.cmdr = self.client_for(self.make_user("cmdr", "unit_commander", unit="BARI-ARMY-A"))
        self.nugaal = self.client_for(self.make_user("nugaal_tr", "transport_officer", unit="NUGAAL-ARMY"))
        self.member = self.client_for(self.make_user("plain", "member", unit="BARI-ARMY"))
        self.d1 = self.person("BARI-ARMY-A1", "Driver One", service_number="D-1")
        self.d2 = self.person("BARI-ARMY-A1", "Driver Two", service_number="D-2")
        self.cat = {c.code: c for c in VehicleCategory.objects.all()}

    def add(self, unit=None, c=None, **kw):
        body = {"category": "hilux_4x4", "org_unit": str((unit or self.bn).pk), "plate": "TEST-001", "make": "Toyota", "model": "Hilux",
                "location": "Test depot", **kw}
        return (c or self.officer).post(URL, body, format="json")

    def veh(self, **kw):
        r = self.add(**kw)
        self.assertEqual(r.status_code, 201, r.data)
        return Vehicle.objects.get(pk=r.data["id"])

    def post(self, v, action, body, c=None):
        v.refresh_from_db()
        return (c or self.officer).post(f"{URL}{v.pk}/{action}/", {"version": v.version, **body}, format="json")


class RegistryTests(VehicleBase):
    def test_categories_available_and_configurable(self):
        codes = {c["code"] for c in self.officer.get(URL + "categories/").data["results"]}
        self.assertTrue({"ambulance", "armored_truck", "hilux_4x4"} <= codes)
        self.assertEqual(self.officer.post(URL + "categories/", {"code": "x", "name_en": "X"}, format="json").status_code, 404)  # not HQ configure
        hq = self.client_for(self.make_user("hqadm", "hq_admin"))
        r = hq.post(URL + "categories/", {"code": "water_tanker", "name_en": "Water tanker"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.add(category="water_tanker", plate="TEST-009").status_code, 201)

    def test_register_generates_unique_stable_id_and_separates_category_from_model(self):
        a, b = self.veh(), self.veh(plate="TEST-002", category="ambulance", make="Toyota", model="Hilux")
        self.assertEqual((a.vehicle_id, b.vehicle_id), ("VEH-000001", "VEH-000002"))
        self.assertEqual(b.category.code, "ambulance")  # same make/model, different category
        old = a.vehicle_id
        r = self.post(a, "edit", {"plate": "NEW-777"})
        self.assertEqual(r.status_code, 200, r.data)
        a.refresh_from_db()
        self.assertEqual((a.vehicle_id, a.plate), (old, "NEW-777"))  # plate changed, ID did not

    def test_plate_uniqueness_ignores_case_and_spacing_and_none_is_explicit(self):
        self.veh(plate="ab 123")
        r = self.add(plate="AB-123")
        self.assertEqual(r.status_code, 400)
        self.assertIn("plate_in_use", self.codes(r, "plate"))
        v1 = self.veh(plate="", plate_status="none")
        v2 = self.veh(plate="", plate_status="unknown")  # several unplated vehicles are allowed, nothing invented
        self.assertEqual((v1.plate, v1.plate_status, v2.plate_status), ("", "none", "unknown"))
        self.assertEqual(self.add(plate="", plate_status="registered").status_code, 400)

    def test_validation(self):
        self.assertEqual(self.add(category="nope").status_code, 400)
        self.assertEqual(self.add(year=3000).status_code, 400)
        self.assertEqual(self.add(status="decommissioned").status_code, 400)
        self.assertEqual(self.add(driver="not-a-uuid").status_code, 400)
        self.assertEqual(self.add(unit=self.unit("NUGAAL-ARMY-A") if OU.objects.filter(code="NUGAAL-ARMY-A").exists() else self.unit("NUGAAL-ARMY")).status_code, 400)

    def test_search_by_vehicle_id_plate_driver_and_full_record(self):
        v = self.veh(driver=str(self.d1.pk), custodian=str(self.d2.pk))
        self.post(v, "status", {"status": "under_repair", "reason": "Gearbox"})
        for q in ({"q": v.vehicle_id}, {"vehicle_id": v.vehicle_id.lower()}, {"plate": "test 001"}, {"service_number": "D-1"}, {"status": "under_repair"},
                  {"category": "hilux_4x4"}, {"org_unit": str(self.brig.pk)}):
            rows = self.officer.get(URL, q).data["results"]
            self.assertEqual([r["vehicle_id"] for r in rows], [v.vehicle_id], q)
        d = self.officer.get(f"{URL}{v.vehicle_id}/").data  # lookup by Vehicle ID
        self.assertEqual((d["plate"], d["category"]["code"], d["org_unit"]["code"], d["driver"]["service_number"], d["custodian"]["service_number"],
                          d["location"], d["status"]), ("TEST-001", "hilux_4x4", "BARI-ARMY-A1", "D-1", "D-2", "Test depot", "under_repair"))
        self.assertTrue(d["assignment_history"])
        self.assertEqual(self.officer.get(f"{URL}{v.pk}/history/").status_code, 200)


class AssignmentTests(VehicleBase):
    def test_driver_change_keeps_history_and_blocks_double_booking(self):
        v, w = self.veh(driver=str(self.d1.pk)), self.veh(plate="TEST-002")
        r = self.post(w, "driver", {"driver": str(self.d1.pk)})
        self.assertIn("driver_already_assigned", self.codes(r, "driver"))
        self.assertEqual(self.post(v, "driver", {"driver": str(self.d2.pk), "authority_ref": "Order 7"}).status_code, 200)
        hist = [(e["kind"], e["before"].get("driver"), e["after"].get("driver")) for e in self.officer.get(f"{URL}{v.pk}/history/", {"kind": "driver_change"}).data["results"]]
        self.assertEqual(hist, [("driver_change", str(self.d1.pk), str(self.d2.pk))])
        self.assertEqual(self.post(w, "driver", {"driver": str(self.d1.pk)}).status_code, 200)  # freed driver can move on

    def test_driver_must_exist_serve_and_be_in_reach(self):
        v = self.veh()
        retired = self.person("BARI-ARMY-A1", "Retired Man", service_number="R-1")
        Personnel.objects.filter(pk=retired.pk).update(status="retired")
        self.assertIn("person_not_serving", self.codes(self.post(v, "driver", {"driver": str(retired.pk)}), "driver"))
        far = self.person("NUGAAL-ARMY-A", "Far Away", service_number="F-1")
        self.assertIn("person_unknown", self.codes(self.post(v, "driver", {"driver": str(far.pk)}), "driver"))

    def test_transfer_preserves_history_clears_assignments_and_moves_visibility(self):
        v = self.veh(driver=str(self.d1.pk), custodian=str(self.d2.pk))
        self.assertEqual(self.post(v, "transfer", {"org_unit": str(self.other.pk)}).status_code, 400)  # authority required
        r = self.post(v, "transfer", {"org_unit": str(self.other.pk), "authority_ref": "Order 9/2026", "reason": "Reorganisation"})
        self.assertEqual(r.status_code, 200, r.data)
        v.refresh_from_db()
        self.assertEqual((v.org_unit_id, v.driver_id, v.custodian_id), (self.other.pk, None, None))
        ev = VehicleEvent.objects.get(vehicle=v, kind="unit_transfer")
        self.assertEqual((ev.before["org_unit"], ev.after["org_unit"], ev.authority_ref), (str(self.bn.pk), str(self.other.pk), "Order 9/2026"))
        self.assertEqual(self.officer.get(URL, {"org_unit": str(self.bn.pk)}).data["count"], 0)
        self.assertEqual(self.officer.get(URL, {"org_unit": str(self.other.pk)}).data["count"], 1)
        self.assertEqual(self.post(v, "transfer", {"org_unit": str(self.unit("NUGAAL-ARMY").pk), "authority_ref": "x"}).status_code, 400)  # receiving unit outside scope

    def test_stale_version_is_a_conflict_and_changes_nothing(self):
        v = self.veh()
        r = self.officer.post(f"{URL}{v.pk}/location/", {"version": 99, "location": "Elsewhere"}, format="json")
        self.assertEqual(r.status_code, 409)
        v.refresh_from_db()
        self.assertEqual(v.location, "Test depot")
        self.assertFalse(VehicleEvent.objects.filter(vehicle=v, kind="location_change").exists())


class StatusMaintenanceSummaryTests(VehicleBase):
    def test_status_and_maintenance_update_record_and_summaries(self):
        v = self.veh(driver=str(self.d1.pk))
        self.assertEqual(self.post(v, "status", {"status": "under_repair"}).status_code, 400)  # reason required
        self.post(v, "status", {"status": "out_of_service", "reason": "Accident"})
        s = self.officer.get(URL + "summary/", {"org_unit": str(self.brig.pk)}).data
        self.assertEqual(s["combined"]["by_status"], {"out_of_service": 1})
        self.assertEqual(s["combined"]["unavailable"], 1)
        r = self.post(v, "maintenance/add", {"kind": "repair", "performed_on": str(date.today()), "reported_issue": "Engine", "next_due_date": str(date.today() + timedelta(days=30))})
        self.assertEqual(r.status_code, 201, r.data)
        v.refresh_from_db()
        self.assertEqual(v.status, "under_repair")
        self.assertEqual(self.post(v, "status", {"status": "operational", "reason": "Back"}).status_code, 400)  # job still open
        mid = r.data["record"]["id"]
        done = self.post(v, f"maintenance/{mid}/complete", {"work_performed": "Engine replaced"}) if False else None
        m = self.officer.get(f"{URL}{v.pk}/maintenance/").data["results"][0]
        done = self.officer.post(f"{URL}{v.pk}/maintenance/{mid}/complete/", {"version": m["version"], "work_performed": "Engine replaced"}, format="json")
        self.assertEqual(done.status_code, 200, done.data)
        v.refresh_from_db()
        self.assertEqual(v.status, "operational")
        self.assertEqual(v.maintenance.get().state, "completed")

    def test_overdue_maintenance_is_derived_from_due_dates(self):
        v = self.veh()
        self.post(v, "maintenance/add", {"kind": "service", "state": "completed", "performed_on": str(date.today() - timedelta(days=200)),
                                         "work_performed": "Oil", "next_due_date": str(date.today() - timedelta(days=5))})
        row = self.officer.get(URL, {"overdue": "1"}).data["results"]
        self.assertEqual([r["vehicle_id"] for r in row], [v.vehicle_id])
        self.assertTrue(row[0]["maintenance_overdue"])
        self.assertEqual(self.officer.get(URL + "summary/", {"org_unit": str(self.brig.pk)}).data["combined"]["overdue_maintenance"], 1)
        v.refresh_from_db()  # a newer service with a future due date clears it
        self.post(v, "maintenance/add", {"kind": "service", "state": "completed", "performed_on": str(date.today()), "work_performed": "Oil",
                                         "next_due_date": str(date.today() + timedelta(days=90))})
        self.assertEqual(self.officer.get(URL, {"overdue": "1"}).data["count"], 0)

    def test_fleet_totals_do_not_double_count(self):
        self.veh(category="ambulance", plate="A-1", unit=self.brig)
        self.veh(category="hilux_4x4", plate="H-1", unit=self.bn, driver=str(self.d1.pk))
        self.veh(category="hilux_4x4", plate="H-2", unit=self.bn)
        s = self.officer.get(URL + "summary/", {"org_unit": str(self.brig.pk)}).data
        self.assertEqual((s["total"], s["direct"]["total"], s["subordinate"]["total"], s["combined"]["total"]), (3, 1, 2, 3))
        cats = {c["code"]: c["count"] for c in s["combined"]["by_category"]}
        self.assertEqual(cats, {"ambulance": 1, "hilux_4x4": 2})
        self.assertEqual((s["combined"]["without_driver"], s["subordinate"]["without_driver"]), (2, 1))
        self.assertEqual([(c["unit"]["code"], c["total"], c["direct"]) for c in s["by_child_unit"]], [("BARI-ARMY-A1", 2, 2)])
        b = self.officer.get(URL + "summary/", {"org_unit": str(self.bn.pk)}).data
        self.assertEqual((b["direct"]["total"], b["subordinate"]["total"]), (2, 0))
        region = self.officer.get(URL + "summary/", {"org_unit": str(self.unit("BARI-ARMY").pk)}).data
        self.assertEqual(region["total"], 3)  # branch command total equals brigade total: each vehicle counted once
        v = Vehicle.objects.get(plate="H-2")
        self.post(v, "transfer", {"org_unit": str(self.brig.pk), "authority_ref": "O1"})
        s = self.officer.get(URL + "summary/", {"org_unit": str(self.brig.pk)}).data
        self.assertEqual((s["total"], s["direct"]["total"], s["subordinate"]["total"]), (3, 2, 1))


class SecurityTests(VehicleBase):
    def test_unauthorised_users_cannot_read_or_change(self):
        v = self.veh()
        for c in (self.member, self.client_for(self.make_user("hqrep", "hq_reporting"))):
            self.assertEqual(c.get(URL).status_code, 403)
            self.assertEqual(c.get(f"{URL}{v.pk}/").status_code, 403)
            self.assertEqual(c.post(URL, {}, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.make_user("anon_like", "member")).get(URL + "summary/", {"org_unit": str(self.bn.pk)}).status_code, 403)

    def test_guessing_ids_or_urls_outside_scope_reveals_nothing(self):
        v = self.veh()
        for key in (str(v.pk), v.vehicle_id):
            self.assertEqual(self.nugaal.get(f"{URL}{key}/").status_code, 404)
            self.assertEqual(self.nugaal.get(f"{URL}{key}/history/").status_code, 404)
            self.assertEqual(self.nugaal.post(f"{URL}{key}/status/", {"version": 1, "status": "out_of_service", "reason": "x"}, format="json").status_code, 404)
        self.assertEqual(self.nugaal.get(URL, {"q": v.vehicle_id}).data["count"], 0)
        self.assertEqual(self.nugaal.get(URL, {"org_unit": str(self.bn.pk)}).data["count"], 0)
        self.assertEqual(self.nugaal.get(URL + "summary/", {"org_unit": str(self.bn.pk)}).status_code, 404)
        v.refresh_from_db()
        self.assertEqual(v.status, "operational")

    def test_viewer_cannot_edit_and_cost_needs_its_own_permission(self):
        v = self.veh()
        self.assertEqual(self.cmdr.get(f"{URL}{v.pk}/").status_code, 200)  # commander of the brigade sees its vehicles ...
        self.assertEqual(self.post(v, "status", {"status": "out_of_service", "reason": "x"}, c=self.cmdr).status_code, 403)  # ... but cannot change them
        self.assertEqual(self.post(v, "transfer", {"org_unit": str(self.other.pk), "authority_ref": "x"}, c=self.cmdr).status_code, 403)
        self.assertEqual(self.cmdr.post(URL, {}, format="json").status_code, 403)
        r = self.post(v, "maintenance/add", {"kind": "service", "state": "completed", "performed_on": str(date.today()), "work_performed": "Oil", "cost": "120.50", "currency": "usd"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.officer.get(f"{URL}{v.pk}/maintenance/").data["results"][0]["cost"], "120.50")
        seen = self.cmdr.get(f"{URL}{v.pk}/maintenance/").data
        self.assertNotIn("cost", seen["results"][0])
        self.assertFalse(seen["cost_visible"])

    def test_audit_trail_for_views_and_changes(self):
        v = self.veh()
        self.officer.get(URL)
        self.officer.get(f"{URL}{v.pk}/")
        self.post(v, "location", {"location": "North yard"})
        self.cmdr.get(f"{URL}{v.pk}/")
        self.member.get(URL)  # denied
        actions = set(AuditEvent.objects.values_list("action", flat=True))
        self.assertTrue({"vehicle.registered", "vehicle.read_list", "vehicle.read_detail", "vehicle.location_change", "access.denied"} <= actions)
        ev = AuditEvent.objects.get(action="vehicle.location_change")
        self.assertEqual((ev.actor_username, ev.entity_id, ev.metadata["before"]["location"], ev.metadata["after"]["location"]),
                         ("transport", str(v.pk), "Test depot", "North yard"))
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.read_detail", actor_username="cmdr").exists())

    def test_history_is_append_only_and_records_cannot_be_deleted(self):
        v = self.veh()
        ev = VehicleEvent.objects.filter(vehicle=v).first()
        with self.assertRaises(AppendOnlyError):
            ev.delete()
        with self.assertRaises(AppendOnlyError):
            ev.save()
        with self.assertRaises(AppendOnlyError):
            v.delete()


class DisposalAndDocumentTests(VehicleBase):
    def test_controlled_disposal_workflow_preserves_history(self):
        v = self.veh(driver=str(self.d1.pk))
        self.assertEqual(self.post(v, "disposal/propose", {"reason": "Beyond repair"}).status_code, 400)  # authority required
        self.assertEqual(self.post(v, "disposal/propose", {"reason": "Beyond repair", "authority_ref": "Board 3/26"}, c=self.cmdr).status_code, 403)
        self.assertEqual(self.post(v, "disposal/propose", {"reason": "Beyond repair", "authority_ref": "Board 3/26"}).status_code, 200)
        self.assertEqual(self.post(v, "disposal/approve", {}, c=self.officer).status_code, 403)  # proposer role has no approve permission
        self.assertEqual(self.post(v, "disposal/reject", {"reason": "Need more evidence"}, c=self.approver).status_code, 200)
        self.assertEqual(self.post(v, "disposal/propose", {"reason": "Beyond repair", "authority_ref": "Board 4/26"}).status_code, 200)
        r = self.post(v, "disposal/approve", {}, c=self.approver)
        self.assertEqual(r.status_code, 200, r.data)
        v.refresh_from_db()
        self.assertEqual((v.status, v.driver_id), ("decommissioned", None))
        self.assertTrue(v.decommissioned_at)
        kinds = list(VehicleEvent.objects.filter(vehicle=v).order_by("created_at").values_list("kind", flat=True))
        self.assertEqual(kinds, ["registered", "disposal_proposed", "disposal_rejected", "disposal_proposed", "decommissioned"])
        self.assertEqual(self.post(v, "status", {"status": "operational", "reason": "x"}).status_code, 400)  # read-only afterwards
        self.assertEqual(self.officer.get(URL).data["count"], 0)  # not in the active list ...
        self.assertEqual(self.officer.get(URL, {"include_decommissioned": "1"}).data["count"], 1)  # ... but never erased
        s = self.officer.get(URL + "summary/", {"org_unit": str(self.brig.pk)}).data
        self.assertEqual((s["total"], s["decommissioned"]), (0, 1))
        self.assertEqual(self.d1.driven_vehicles.count(), 0)  # driver freed for another vehicle

    def test_proposer_cannot_approve_own_request(self):
        both = self.client_for(self.make_user("both", "transport_officer", unit="BARI-ARMY"))
        from apps.accounts.models import Role, RoleAssignment, User
        u = User.objects.get(username="both")
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code="vehicle_disposal_approver"), org_unit=self.unit("BARI-ARMY"))
        v = self.veh()
        self.assertEqual(self.post(v, "disposal/propose", {"reason": "R", "authority_ref": "A"}, c=both).status_code, 200)
        r = self.post(v, "disposal/approve", {}, c=both)
        self.assertEqual(r.status_code, 400)
        self.assertIn("self_approval", self.codes(r, "status"))

    def test_documents_are_validated_encrypted_audited_and_withdrawable(self):
        v = self.veh()
        f = lambda data, name="reg.pdf": SimpleUploadedFile(name, data, content_type="application/pdf")
        bad = self.officer.post(f"{URL}{v.pk}/documents/upload/", {"category": "registration", "title": "Papers", "file": f(b"MZ not a pdf")}, format="multipart")
        self.assertEqual(bad.status_code, 400)
        ok = self.officer.post(f"{URL}{v.pk}/documents/upload/", {"category": "registration", "title": "Papers", "file": f(PDF)}, format="multipart")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertNotIn(PDF, bytes(v.documents.get().content_enc))
        down = self.cmdr.get(f"{URL}{v.pk}/documents/{ok.data['id']}/download/")
        self.assertEqual((down.status_code, down.content), (200, PDF))
        self.assertEqual(self.nugaal.get(f"{URL}{v.pk}/documents/{ok.data['id']}/download/").status_code, 404)
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.document_download", actor_username="cmdr").exists())
        self.assertEqual(self.officer.post(f"{URL}{v.pk}/documents/{ok.data['id']}/withdraw/", {}, format="json").status_code, 400)
        self.assertEqual(self.officer.post(f"{URL}{v.pk}/documents/{ok.data['id']}/withdraw/", {"reason": "Wrong file"}, format="json").status_code, 200)
        self.assertEqual(self.officer.get(f"{URL}{v.pk}/documents/").data["results"], [])
        self.assertEqual(v.documents.count(), 1)  # withdrawn, not deleted


class LegacyImportTests(VehicleBase):
    def test_import_is_dry_by_default_idempotent_and_skips_retired(self):
        from django.core.management import call_command
        from io import StringIO
        from apps.logistics.models import Asset, InventoryCategory
        ic = InventoryCategory.objects.create(code="old-vehicles", name_en="Old vehicles", kind="asset")
        Asset.objects.create(category=ic, org_unit=self.bn, identifier="TAG-1", status="maintenance", description="Found in depot")
        Asset.objects.create(category=ic, org_unit=self.bn, identifier="TAG-2", status="retired")
        args = dict(inventory_category="old-vehicles", vehicle_category="hilux_4x4", stdout=StringIO())
        call_command("import_vehicle_assets", **args)
        self.assertEqual(Vehicle.objects.count(), 0)  # dry run
        call_command("import_vehicle_assets", apply=True, **args)
        call_command("import_vehicle_assets", apply=True, **args)  # repeat changes nothing
        v = Vehicle.objects.get()
        self.assertEqual((v.status, v.plate, v.plate_status, v.org_unit_id, v.acquisition_ref), ("under_maintenance", "", "unknown", self.bn.pk, "Legacy asset TAG-1"))
        self.assertEqual(VehicleEvent.objects.filter(vehicle=v, kind="registered").count(), 1)


class ConfigurableStatusTests(VehicleBase):
    def test_hq_can_add_a_status_and_it_drives_availability_counts(self):
        hq = self.client_for(self.make_user("hqadm2", "hq_admin"))
        codes = {s["code"] for s in self.officer.get(URL + "statuses/").data["results"]}
        self.assertTrue({"operational", "under_repair", "decommissioned"} <= codes)
        self.assertEqual(self.officer.post(URL + "statuses/", {"code": "on_loan", "name_en": "On loan"}, format="json").status_code, 404)  # not HQ
        v = self.veh()
        self.assertEqual(self.post(v, "status", {"status": "on_loan", "reason": "x"}).status_code, 400)  # unknown until configured
        r = hq.post(URL + "statuses/", {"code": "on_loan", "name_en": "On loan", "name_so": "Amaano", "available": False}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(hq.post(URL + "statuses/", {"code": "on_loan", "name_en": "Again"}, format="json").status_code, 400)
        self.assertEqual(self.post(v, "status", {"status": "on_loan", "reason": "Lent to Unit B"}).status_code, 200)
        s = self.officer.get(URL + "summary/", {"org_unit": str(self.brig.pk)}).data["combined"]
        self.assertEqual((s["by_status"], s["unavailable"]), ({"on_loan": 1}, 1))
        hq.patch(f"{URL}statuses/{r.data['id']}/", {"available": True}, format="json")
        self.assertEqual(self.officer.get(URL + "summary/", {"org_unit": str(self.brig.pk)}).data["combined"]["unavailable"], 0)
        self.assertEqual(hq.patch(f"{URL}statuses/{r.data['id']}/", {"active": False}, format="json").status_code, 400)  # still in use

    def test_system_statuses_cannot_be_switched_off_or_used_to_bypass_disposal(self):
        hq = self.client_for(self.make_user("hqadm3", "hq_admin"))
        from apps.vehicles.models import VehicleStatusType
        op = VehicleStatusType.objects.get(code="operational")
        self.assertEqual(hq.patch(f"{URL}statuses/{op.pk}/", {"active": False}, format="json").status_code, 400)
        v = self.veh()
        self.assertEqual(self.post(v, "status", {"status": "decommissioned", "reason": "x"}).status_code, 400)  # only via the approval workflow
