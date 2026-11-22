"""Equipment Reference Catalogue and its links into the vehicle register. Synthetic data only."""
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.equipment.models import EquipmentItem, MountedWeaponCategory
from apps.equipment.reference import MOUNTED_WEAPON_CATEGORIES, VEHICLE_MODELS, seed_catalogue
from apps.vehicles.models import Vehicle, VehicleCategory, VehicleEvent
from apps.vehicles.tests.test_vehicles import PDF, URL as VEH, VehicleBase

URL = "/api/v1/equipment/"
PNG = b"\x89PNG\r\n\x1a\n synthetic image bytes"


class CatalogueBase(VehicleBase):
    def setUp(self):
        super().setUp()
        self.hq = self.client_for(self.make_user("hq_cat", "hq_admin"))
        self.sa1 = self.client_for(self.make_user("sa_one", "super_admin"))
        self.sa2 = self.client_for(self.make_user("sa_two", "super_admin"))

    def png(self, name="p.png"):
        return SimpleUploadedFile(name, PNG, content_type="image/png")

    def new_weapon(self, c=None, **kw):
        body = {"kind": "mounted_weapon", "name": "Test gun", "weapon_category": "heavy_machine_gun", **kw}
        return (c or self.hq).post(URL, body, format="json")


class SeedTests(CatalogueBase):
    def test_reference_models_and_categories_are_seeded_unverified_without_invented_content(self):
        names = {i.name for i in EquipmentItem.objects.filter(kind="vehicle_model")}
        self.assertEqual(names, {m[1] for m in VEHICLE_MODELS})
        self.assertEqual(set(MountedWeaponCategory.objects.values_list("code", flat=True)), {c[0] for c in MOUNTED_WEAPON_CATEGORIES})
        for i in EquipmentItem.objects.all():
            self.assertEqual(i.verification, "unverified")
            self.assertEqual((i.specs.count(), i.photos.count()), (0, 0))  # nothing invented
        self.assertEqual(EquipmentItem.objects.get(code="ford-f-350").vehicle_category.code, "utility")  # existing category reused
        self.assertEqual(EquipmentItem.objects.get(code="t-54-t-55").vehicle_category.group, "combat_vehicle")

    def test_seeding_twice_creates_nothing_and_keeps_edits(self):
        EquipmentItem.objects.filter(code="m939").update(description="Edited by HQ")
        before = (EquipmentItem.objects.count(), VehicleCategory.objects.count())
        seed_catalogue(VehicleCategory, MountedWeaponCategory, EquipmentItem)
        self.assertEqual((EquipmentItem.objects.count(), VehicleCategory.objects.count()), before)
        self.assertEqual(EquipmentItem.objects.get(code="m939").description, "Edited by HQ")

    def test_existing_vehicles_are_untouched(self):
        v = self.veh()
        seed_catalogue(VehicleCategory, MountedWeaponCategory, EquipmentItem)
        v.refresh_from_db()
        self.assertIsNone(v.reference_model)
        self.assertEqual(v.category.code, "hilux_4x4")


class CatalogueApiTests(CatalogueBase):
    def test_reading_follows_vehicle_or_weapon_permission_and_member_is_refused(self):
        self.assertEqual(self.officer.get(URL).status_code, 200)
        self.assertEqual(self.member.get(URL).status_code, 403)
        self.assertEqual(self.officer.get(URL, {"q": "hilux"}).data["count"], 1)
        self.assertEqual(self.officer.get(URL, {"classification": "military_cargo_truck"}).data["count"], 1)

    def test_only_hq_edits_and_only_a_second_super_admin_verifies(self):
        self.assertIn(self.officer.post(URL, {"kind": "mounted_weapon", "name": "X", "weapon_category": "heavy_machine_gun"}, format="json").status_code, (403, 404))
        r = self.new_weapon(name="Reference gun", manufacturer="Maker")
        self.assertEqual(r.status_code, 201, r.data)
        i = EquipmentItem.objects.get(pk=r.data["id"])
        self.assertEqual((i.verification, i.weapon_category.code), ("unverified", "heavy_machine_gun"))
        body = {"result": "verified", "version": i.version}
        self.assertEqual(self.hq.post(f"{URL}{i.pk}/verify/", body, format="json").status_code, 403)  # reserved for the super administrator
        r1 = self.new_weapon(self.sa1, name="Super entry")
        j = EquipmentItem.objects.get(pk=r1.data["id"])
        own = self.sa1.post(f"{URL}{j.pk}/verify/", {"result": "verified", "version": j.version}, format="json")
        self.assertEqual(own.status_code, 400)  # own entry
        ok = self.sa2.post(f"{URL}{j.pk}/verify/", {"result": "verified", "version": j.version}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(ok.data["verification"], "verified")
        self.assertTrue(AuditEvent.objects.filter(action="equipment.verify").exists())

    def test_changing_facts_of_a_verified_entry_returns_it_to_unverified(self):
        j = EquipmentItem.objects.get(pk=self.new_weapon(self.sa1, name="Checked gun").data["id"])
        self.sa2.post(f"{URL}{j.pk}/verify/", {"result": "verified", "version": j.version}, format="json")
        j.refresh_from_db()
        r = self.hq.post(f"{URL}{j.pk}/edit/", {"manufacturer": "Other maker", "version": j.version}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["verification"], "unverified")
        stale = self.hq.post(f"{URL}{j.pk}/edit/", {"manufacturer": "Third", "version": j.version}, format="json")
        self.assertEqual(stale.status_code, 409)

    def test_kind_decides_classification(self):
        bad = self.hq.post(URL, {"kind": "mounted_weapon", "name": "Y", "weapon_category": "nope"}, format="json")
        self.assertEqual(bad.status_code, 400)
        v = self.hq.post(URL, {"kind": "vehicle_model", "name": "Test truck", "vehicle_category": "military_cargo_truck"}, format="json")
        self.assertEqual(v.status_code, 201, v.data)

    def test_specifications_replace_the_list_and_photos_need_images(self):
        i = EquipmentItem.objects.get(code="m939")
        r = self.hq.post(f"{URL}{i.pk}/specs/", {"version": i.version, "specs": [{"name": "Crew", "value": "2"}, {"name": "Drive", "value": "6x6"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([s["name"] for s in self.officer.get(f"{URL}m939/").data["specs"]], ["Crew", "Drive"])
        pdf = self.hq.post(f"{URL}{i.pk}/photos/upload/", {"file": SimpleUploadedFile("a.png", PDF, content_type="image/png")}, format="multipart")
        self.assertEqual(pdf.status_code, 400)  # judged by content, not by the name
        ok = self.hq.post(f"{URL}{i.pk}/photos/upload/", {"file": self.png(), "caption": "Front"}, format="multipart")
        self.assertEqual(ok.status_code, 201, ok.data)
        img = self.officer.get(f"{URL}{i.pk}/photos/{ok.data['id']}/image/")
        self.assertEqual((img.status_code, img["Content-Type"], img.content), (200, "image/png", PNG))
        self.assertEqual(self.officer.get(f"{URL}m939/").data["photo_id"], ok.data["id"])
        self.hq.post(f"{URL}{i.pk}/photos/{ok.data['id']}/withdraw/", {"reason": "wrong vehicle"}, format="json")
        self.assertEqual(self.officer.get(f"{URL}{i.pk}/photos/{ok.data['id']}/image/").status_code, 404)

    def test_entries_are_switched_off_not_deleted(self):
        i = EquipmentItem.objects.get(code="nissan-frontier")
        self.hq.post(f"{URL}{i.pk}/edit/", {"active": False, "version": i.version}, format="json")
        self.assertEqual(self.officer.get(URL, {"q": "frontier"}).data["count"], 0)
        self.assertEqual(self.officer.get(f"{URL}nissan-frontier/").status_code, 404)
        self.assertTrue(EquipmentItem.objects.filter(code="nissan-frontier").exists())


class VehicleLinkTests(CatalogueBase):
    def test_vehicle_points_at_a_model_and_is_filterable_searchable_and_counted(self):
        r = self.add(reference_model="toyota-hilux", category="utility_pickup", plate="GD-501")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["reference_model"]["code"], "toyota-hilux")
        self.assertEqual(self.add(plate="GD-502").data["reference_model"], None)  # nothing guessed from make/model text
        self.assertEqual(self.officer.get(VEH, {"reference_model": "toyota-hilux"}).data["count"], 1)
        self.assertEqual(self.officer.get(VEH, {"q": "Hilux"}).data["count"], 2)
        a = self.officer.get(VEH + "analytics/").json()
        self.assertEqual(a["by_model"], [{"code": "toyota-hilux", "name": "Toyota Hilux", "count": 1}])
        self.assertEqual(self.add(reference_model="no-such", plate="GD-503").status_code, 400)

    def test_model_supplies_the_category_only_when_none_is_given(self):
        r = self.officer.post(VEH, {"reference_model": "btr-60", "org_unit": str(self.bn.pk), "plate": "GD-510"}, format="json")
        self.assertEqual((r.status_code, r.data["category"]["code"]), (201, "armoured_personnel_carrier"))

    def test_specifications_are_audited_and_replace_the_list(self):
        v = self.veh()
        r = self.post(v, "specifications", {"specs": [{"name": "Engine no.", "value": "E-1"}], "reason": "recorded from plate"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.officer.get(f"{VEH}{v.pk}/").data["specs"], [{"name": "Engine no.", "value": "E-1", "unit": ""}])
        self.assertTrue(VehicleEvent.objects.filter(vehicle=v, kind="specification").exists())
        self.assertEqual(self.post(v, "specifications", {"specs": [{"name": "Engine no.", "value": "E-1"}]}).status_code, 400)  # unchanged
        self.assertEqual(self.post(v, "specifications", {"specs": []}, c=self.member).status_code, 403)

    def test_photographs_are_images_kept_apart_from_documents(self):
        v = self.veh()
        up = lambda f, cat="photograph": self.officer.post(f"{VEH}{v.pk}/documents/upload/", {"category": cat, "title": "Front", "file": f}, format="multipart")
        self.assertEqual(up(SimpleUploadedFile("a.pdf", PDF, content_type="application/pdf")).status_code, 400)
        self.assertEqual(up(self.png()).status_code, 201)
        up(SimpleUploadedFile("r.pdf", PDF, content_type="application/pdf"), "registration")
        self.assertEqual(len(self.officer.get(f"{VEH}{v.pk}/photos/").data["results"]), 1)
        self.assertEqual([d["category"] for d in self.officer.get(f"{VEH}{v.pk}/documents/").data["results"]], ["registration"])
        self.assertEqual(self.nugaal.get(f"{VEH}{v.pk}/photos/").status_code, 404)  # outside scope

    def test_armament_uses_a_catalogue_weapon_and_never_invents_a_register_serial(self):
        v = self.veh()
        w = EquipmentItem.objects.get(pk=self.new_weapon(name="Mounted gun").data["id"])
        r = self.post(v, "armament/add", {"reference_item": w.code, "mount_position": "Turret"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.post(v, "armament/add", {"reference_item": w.code, "serial": "NOPE-1"}).status_code, 400)
        self.assertEqual(self.post(v, "armament/add", {"reference_item": "m939"}).status_code, 400)  # a vehicle model is not a weapon
        rows = self.officer.get(f"{VEH}{v.pk}/armament/").data["results"]
        self.assertEqual((len(rows), rows[0]["item"]["code"], rows[0]["register_linked"]), (1, w.code, False))
        gone = self.post(v, "armament/%s/remove" % rows[0]["id"], {"reason": "removed for repair"})
        self.assertEqual(gone.status_code, 200, gone.data)
        self.assertEqual(self.officer.get(f"{VEH}{v.pk}/armament/").data["results"], [])
        self.assertTrue(VehicleEvent.objects.filter(vehicle=v, kind="armament").count() == 2)


class LoadReferenceSpecsTests(CatalogueBase):
    def run_cmd(self, *args):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("load_reference_specs", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        self.run_cmd()
        self.assertEqual(EquipmentItem.objects.get(code="btr-60").specs.count(), 0)
        self.assertFalse(EquipmentItem.objects.filter(code="dshk-12-7").exists())

    def test_apply_fills_sourced_specs_stays_unverified_and_is_idempotent(self):
        self.run_cmd("--apply")
        btr = EquipmentItem.objects.get(code="btr-60")
        self.assertGreater(btr.specs.count(), 5)
        self.assertIn("wikipedia.org/wiki/BTR-60", btr.source_ref)
        gun = EquipmentItem.objects.get(code="dshk-12-7")
        self.assertEqual((gun.kind, gun.weapon_category.code, gun.photos.count()), ("mounted_weapon", "heavy_machine_gun", 0))
        for i in (btr, gun):
            self.assertEqual(i.verification, "unverified")  # a second person must still verify against the cited source
        self.assertTrue(AuditEvent.objects.filter(action="equipment.reference_loaded", entity_id=str(btr.pk)).exists())
        for code in ("toyota-land-cruiser-j79", "toyota-hilux", "nissan-frontier", "ford-f-350"):
            self.assertGreater(EquipmentItem.objects.get(code=code).specs.count(), 4, code)
        for code, cat in (("zu-23-2", "anti_aircraft_gun"), ("m2-browning", "heavy_machine_gun"), ("pkm", "general_purpose_machine_gun")):
            w = EquipmentItem.objects.get(code=code)
            self.assertEqual((w.kind, w.weapon_category.code, w.verification, w.photos.count()), ("mounted_weapon", cat, "unverified", 0))
            self.assertIn("wikipedia.org/wiki/", w.source_ref)
        n = EquipmentItem.objects.count()
        self.run_cmd("--apply")
        self.assertEqual((EquipmentItem.objects.count(), btr.specs.count()), (n, EquipmentItem.objects.get(code="btr-60").specs.count()))

    def test_an_edited_entry_is_not_overwritten(self):
        item = EquipmentItem.objects.get(code="m939")
        EquipmentItem.objects.filter(pk=item.pk).update(source_ref="Army technical manual TM-X")
        self.run_cmd("--apply")
        item.refresh_from_db()
        self.assertEqual(item.source_ref, "Army technical manual TM-X")
