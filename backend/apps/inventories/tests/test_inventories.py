from apps.inventories.models import InventoryCount
from apps.weapons.tests.test_weapons import WeaponBase

I = "/api/v1/inventories/"


class InventoryTests(WeaponBase):
    def setUp(self):
        super().setUp()
        self.w1, self.w2, self.w3 = self.weapon("AK-1"), self.weapon("AK-2"), self.weapon("AK-3")
        self.assertEqual(self.issue(self.w1).status_code, 200)
        self.boss = self.client_for(self.make_user("boss", "super_admin"))

    def open(self, c=None):
        r = (c or self.armourer).post(I, {"org_unit": str(self.unit_a.pk), "kind": "cyclic"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def lines(self, cid, c=None):
        return {ln["expected_identifier"]: ln["id"] for ln in (c or self.armourer).get(f"{I}{cid}/").json()["lines"]}

    def check(self, cid, line, result="verified", **kw):
        return self.armourer.post(f"{I}{cid}/check/", {"line": line, "result": result, **kw}, format="json")

    def test_the_count_starts_from_the_register_with_expected_holders(self):
        cid = self.open()
        body = self.armourer.get(f"{I}{cid}/").json()
        self.assertEqual(body["progress"]["total"], 3)
        holder = {ln["expected_identifier"]: ln["expected_holder"] for ln in body["lines"]}
        self.assertIn("Rifleman One", holder["AK-1"])
        self.assertIn("store", holder["AK-2"])
        self.assertEqual(self.armourer.post(I, {"org_unit": str(self.unit_a.pk)}, format="json").status_code, 400)  # one count at a time

    def test_clean_count_is_signed_by_a_different_person(self):
        cid = self.open()
        for line in self.lines(cid).values():
            self.assertEqual(self.check(cid, line).status_code, 200)
        self.assertEqual(self.armourer.post(f"{I}{cid}/submit/", {}, format="json").status_code, 200)
        self.assertEqual(self.armourer.post(f"{I}{cid}/sign/", {}, format="json").status_code, 403)  # not the same person
        r = self.boss.post(f"{I}{cid}/sign/", {"note": "All present"}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "signed"))
        self.assertEqual(self.check(cid, "x").status_code, 400)  # a signed count is closed

    def test_shortages_need_an_explanation_and_nothing_can_be_submitted_unchecked(self):
        cid = self.open()
        ids = self.lines(cid)
        self.assertEqual(self.armourer.post(f"{I}{cid}/submit/", {}, format="json").status_code, 400)  # unchecked lines
        self.check(cid, ids["AK-1"])
        self.check(cid, ids["AK-2"], "missing")
        self.assertEqual(self.check(cid, ids["AK-3"], "mismatch").status_code, 400)  # must say what serial was read
        self.check(cid, ids["AK-3"], "mismatch", observed_identifier="AK-9")
        self.assertEqual(self.armourer.post(f"{I}{cid}/submit/", {}, format="json").status_code, 200)
        r = self.boss.post(f"{I}{cid}/sign/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("AK-2", str(r.json()))
        for sid in (ids["AK-2"], ids["AK-3"]):
            self.assertEqual(self.armourer.post(f"{I}{cid}/annotate/", {"line": sid, "note": "Reported to the commander"}, format="json").status_code, 200)
        self.assertEqual(self.boss.post(f"{I}{cid}/sign/", {}, format="json").status_code, 200)

    def test_an_unlisted_item_can_be_added_once(self):
        cid = self.open()
        r = self.armourer.post(f"{I}{cid}/found/", {"identifier": "ZZ-77"}, format="json")
        self.assertEqual((r.status_code, r.json()["result"]), (201, "unlisted"))
        self.assertEqual(self.armourer.post(f"{I}{cid}/found/", {"identifier": "ZZ-77"}, format="json").status_code, 400)
        self.assertEqual(self.armourer.post(f"{I}{cid}/found/", {"identifier": "AK-1"}, format="json").status_code, 400)  # already listed

    def test_the_register_is_never_changed_by_a_count_and_outsiders_are_refused(self):
        cid = self.open()
        self.check(cid, self.lines(cid)["AK-2"], "missing")
        self.w2.refresh_from_db()
        self.assertEqual(self.w2.status, "in_stock")
        other = self.client_for(self.make_user("other_unit", "weapons_custodian", unit="NUGAAL-ARMY"))
        self.assertEqual(other.get(f"{I}{cid}/").status_code, 404)
        self.assertEqual(InventoryCount.objects.count(), 1)
