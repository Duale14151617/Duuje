"""Weapon register: serial numbers, custody, issue and return, history. Synthetic data only."""
from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.logistics.models import Asset, AssetEvent, InventoryCategory
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase
from apps.weapons.models import WeaponCustody, WeaponDetail

W = "/api/v1/weapons/"


class WeaponBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        InventoryCategory.objects.filter(code="weapons").update(approval_status="approved")
        self.cat = InventoryCategory.objects.get(code="weapons")
        self.unit_a, self.unit_b = self.unit("BARI-ARMY-A"), self.unit("BARI-ARMY-B")
        self.armourer = self.client_for(self.make_user("armourer", "weapons_custodian", unit="BARI-ARMY"))
        self.s1 = self.person("BARI-ARMY-A", "Rifleman One", rank="PA-03", service_number="S-1")
        self.s2 = self.person("BARI-ARMY-A", "Rifleman Two", rank="PA-03", service_number="S-2")
        self.away = self.person("BARI-ARMY-B", "Other Unit Soldier", rank="PA-03", service_number="S-9")

    def register(self, serial="AK-0001", unit=None, c=None, **kw):
        body = {"category": str(self.cat.pk), "org_unit": str((unit or self.unit_a).pk), "serial": serial,
                "weapon_type": "Rifle", "make_model": "Type 56", "caliber": "7.62mm", **kw}
        return (c or self.armourer).post(W, body, format="json")

    def weapon(self, serial="AK-0001"):
        self.assertEqual(self.register(serial).status_code, 201)
        return Asset.objects.get(identifier=serial)

    def issue(self, asset, person=None, c=None, **kw):
        asset.refresh_from_db()
        body = {"personnel": str((person or self.s1).pk), "condition": "serviceable", "authority_ref": "Order 5/2026",
                "version": asset.version, **kw}
        return (c or self.armourer).post(f"{W}{asset.pk}/issue/", body, format="json")

    def give_back(self, asset, c=None, **kw):
        asset.refresh_from_db()
        return (c or self.armourer).post(f"{W}{asset.pk}/return/", {"condition": "serviceable", "version": asset.version, **kw}, format="json")


class RegisterTests(WeaponBase):
    def test_register_a_weapon_with_a_unique_serial(self):
        r = self.register()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["serial"], r.json()["status"], r.json()["weapon_type"]), ("AK-0001", "in_stock", "Rifle"))
        self.assertTrue(AuditEvent.objects.filter(action="weapon.register").exists())
        self.assertEqual(self.codes(self.register(), "serial"), ["asset_duplicate"])
        self.assertEqual(self.codes(self.register("ak-0001", unit=self.unit_b), "serial"), ["asset_duplicate"])  # whole register, any unit

    def test_serial_is_unique_across_weapon_categories(self):
        other = InventoryCategory.objects.create(code="weapons_heavy", kind="asset", restricted=True, name_en="Heavy", approval_status="approved")
        self.weapon("HV-1")
        r = self.armourer.post(W, {"category": str(other.pk), "org_unit": str(self.unit_a.pk), "serial": "HV-1", "weapon_type": "Mortar"}, format="json")
        self.assertEqual(self.codes(r, "serial"), ["asset_duplicate"])

    def test_type_is_required_and_only_weapon_categories_are_accepted(self):
        self.assertEqual(self.register("AK-2", weapon_type="").status_code, 400)
        plain = InventoryCategory.objects.get(code="restricted_equipment")
        r = self.armourer.post(W, {"category": str(plain.pk), "org_unit": str(self.unit_a.pk), "serial": "X-1", "weapon_type": "Rifle"}, format="json")
        self.assertEqual(self.codes(r, "category"), ["not_a_weapon_category"])

    def test_the_general_asset_route_cannot_create_weapons(self):
        r = self.armourer.post("/api/v1/logistics/assets/", {"category": str(self.cat.pk), "org_unit": str(self.unit_a.pk),
                                                              "identifier": "SNEAK-1", "description": "x"}, format="json")
        self.assertEqual(self.codes(r, "category"), ["use_weapon_register"])
        self.assertFalse(Asset.objects.filter(identifier="SNEAK-1").exists())

    def test_only_authorized_users_reach_the_register(self):
        for user in (self.make_user("cmdr", "unit_commander", unit="BARI-ARMY-A"), self.make_user("uadm", "unit_admin", unit="BARI-ARMY-A"),
                     self.make_user("mem", "member", unit="BARI-ARMY")):
            c = self.client_for(user)
            self.assertEqual(c.get(W).status_code, 403, user.username)
            self.assertEqual(self.register(c=c).status_code, 403, user.username)

    def test_scope_limits_what_a_custodian_sees(self):
        self.weapon("AK-1")
        far = self.client_for(self.make_user("far", "weapons_custodian", unit="NUGAAL-ARMY"))
        self.assertEqual(far.get(W).json()["results"], [])
        self.assertEqual(far.get(f"{W}{Asset.objects.get(identifier='AK-1').pk}/").status_code, 404)


class CustodyTests(WeaponBase):
    def setUp(self):
        super().setUp()
        self.w = self.weapon()

    def test_issue_records_custody_authorization_and_unit_status(self):
        r = self.issue(self.w)
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d["status"], d["issued_to_unit"]["code"], d["custody"]["personnel"]["service_number"]), ("issued", "BARI-ARMY-A", "S-1"))
        self.assertEqual((d["custody"]["authority_ref"], d["custody"]["issued_by"]), ("Order 5/2026", "armourer"))
        self.assertTrue(AuditEvent.objects.filter(action="weapon.issued").exists())
        self.assertTrue(AssetEvent.objects.filter(asset=self.w, kind="custody_issue").exists())

    def test_issue_needs_a_documented_authorization(self):
        self.assertEqual(self.codes(self.issue(self.w, authority_ref=" "), "authority_ref"), ["authorization_required"])
        self.assertFalse(WeaponCustody.objects.exists())

    def test_one_holder_at_a_time(self):
        self.issue(self.w)
        self.assertEqual(self.codes(self.issue(self.w, person=self.s2), "asset"), ["weapon_already_in_custody"])
        self.assertEqual(WeaponCustody.objects.filter(returned_at__isnull=True).count(), 1)

    def test_only_serving_people_of_the_holding_unit(self):
        self.assertEqual(self.codes(self.issue(self.w, person=self.away), "personnel"), ["person_outside_unit"])
        Personnel.objects.filter(pk=self.s2.pk).update(status="retired")
        self.assertEqual(self.codes(self.issue(self.w, person=self.s2), "personnel"), ["person_not_serving"])

    def test_an_unserviceable_weapon_is_not_issued(self):
        WeaponDetail.objects.filter(pk=self.w.pk).update(condition="unserviceable")
        self.assertEqual(self.codes(self.issue(self.w), "asset"), ["weapon_unserviceable"])

    def test_stale_version_is_refused(self):
        r = self.armourer.post(f"{W}{self.w.pk}/issue/", {"personnel": str(self.s1.pk), "condition": "serviceable",
                                                           "authority_ref": "x", "version": 99}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_return_closes_custody_restores_status_and_keeps_history(self):
        self.issue(self.w)
        r = self.give_back(self.w, note="Handed in", condition="needs_repair")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d["status"], d["issued_to_unit"], d["custody"], d["condition"]), ("in_stock", None, None, "needs_repair"))
        h = d["custody_history"]
        self.assertEqual((len(h), h[0]["outcome"], h[0]["return_condition"], h[0]["returned_by"]), (1, "returned", "needs_repair", "armourer"))
        self.assertEqual(self.codes(self.give_back(self.w), "asset"), ["weapon_not_in_custody"])

    def test_chain_of_custody_across_holders(self):
        self.issue(self.w); self.give_back(self.w)
        WeaponDetail.objects.filter(pk=self.w.pk).update(condition="serviceable")
        self.issue(self.w, person=self.s2); self.give_back(self.w)
        who = [c.personnel.service_number for c in WeaponCustody.objects.filter(asset=self.w).order_by("issued_at")]
        self.assertEqual(who, ["S-1", "S-2"])
        kinds = list(AssetEvent.objects.filter(asset=self.w).order_by("created_at").values_list("kind", flat=True))
        self.assertEqual(kinds, ["register", "custody_issue", "custody_return", "custody_issue", "custody_return"])

    def test_a_weapon_issued_to_a_unit_keeps_that_state_after_the_soldier_returns_it(self):
        self.armourer.post(f"/api/v1/logistics/assets/{self.w.pk}/change/",
                           {"action": "issue", "to_unit": str(self.unit_b.pk), "version": Asset.objects.get(pk=self.w.pk).version}, format="json")
        b_soldier = self.person("BARI-ARMY-B", "Rifleman B", rank="PA-03", service_number="S-B")
        self.assertEqual(self.issue(self.w, person=b_soldier).status_code, 200)
        r = self.give_back(self.w).json()
        self.assertEqual((r["status"], r["issued_to_unit"]["code"]), ("issued", "BARI-ARMY-B"))

    def test_ordinary_asset_actions_are_blocked_while_in_custody(self):
        self.issue(self.w)
        self.w.refresh_from_db()
        r = self.armourer.post(f"/api/v1/logistics/assets/{self.w.pk}/change/",
                               {"action": "retire", "note": "x", "version": self.w.version}, format="json")
        self.assertEqual(self.codes(r, "asset"), ["asset_in_custody"])

    def test_reporting_it_lost_closes_the_custody(self):
        self.issue(self.w)
        self.w.refresh_from_db()
        r = self.armourer.post(f"/api/v1/logistics/assets/{self.w.pk}/change/",
                               {"action": "lost", "note": "Lost on patrol", "version": self.w.version}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        c = WeaponCustody.objects.get(asset=self.w)
        self.assertEqual((c.outcome, c.returned_at is not None), ("lost", True))

    def test_custody_rows_cannot_be_deleted(self):
        self.issue(self.w)
        with self.assertRaises(AppendOnlyError):
            WeaponCustody.objects.get().delete()

    def test_condition_changes_are_recorded(self):
        r = self.armourer.post(f"{W}{self.w.pk}/condition/", {"condition": "needs_repair", "note": "Bent barrel"}, format="json")
        self.assertEqual((r.status_code, r.json()["condition"]), (200, "needs_repair"))
        self.assertTrue(AssetEvent.objects.filter(asset=self.w, kind="condition", note__contains="serviceable -> needs_repair").exists())
        self.assertEqual(self.codes(self.armourer.post(f"{W}{self.w.pk}/condition/", {"condition": "needs_repair"}, format="json"), "condition"), ["no_change"])


class DerivedCountTests(WeaponBase):
    def test_counts_come_from_the_register_and_flag_non_serving_holders(self):
        a, b = self.weapon("AK-1"), self.weapon("AK-2")
        self.armourer.post(W, {"category": str(self.cat.pk), "org_unit": str(self.unit_a.pk), "serial": "PI-1", "weapon_type": "Pistol"}, format="json")
        self.issue(a)
        Personnel.objects.filter(pk=self.s1.pk).update(status="died")
        s = self.armourer.get(W + "summary/").json()
        self.assertEqual((s["total"], s["in_custody"], s["held_by_non_serving"]), (3, 1, 1))
        self.assertEqual(s["by_type"], {"Rifle": 2, "Pistol": 1})
        self.assertEqual(s["by_status"], {"in_stock": 2, "issued": 1})

    def test_list_filters_and_people_lookup(self):
        w = self.weapon("AK-1"); self.weapon("AK-2")
        self.issue(w)
        got = self.armourer.get(W, {"in_custody": "1"}).json()["results"]
        self.assertEqual([x["serial"] for x in got], ["AK-1"])
        self.assertEqual(got[0]["custody"]["personnel"]["service_number"], "S-1")
        Personnel.objects.filter(pk=self.s2.pk).update(status="retired")
        people = self.armourer.get(W + "people/", {"org_unit": str(self.unit_a.pk)}).json()["results"]
        self.assertEqual({p["service_number"] for p in people}, {"S-1"})
        self.assertEqual(set(people[0]), {"id", "full_name", "service_number", "rank", "unit"})      # a lookup, not a personnel record
