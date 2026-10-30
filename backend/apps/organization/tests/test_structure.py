"""Tests for the Puntland Army addendum (ranks, regional commands, unit types, designations, strength). Synthetic data only."""
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.organization.models import (DesignationRule, OrganizationalUnit as OU, ServiceBranch, SpecialistDesignation,
                                      UnitType)
from apps.personnel import services as pers
from apps.personnel.models import Personnel
from apps.ranks.catalogue import OFFICIAL_ARMY_RANKS, apply_official_ranks
from apps.ranks.models import Rank

UNITS = "/api/v1/organization/units/"
TYPES = "/api/v1/organization/unit-types/"
DESIGS = "/api/v1/organization/designations/"
RULES = "/api/v1/organization/designation-rules/"
STRUCT = "/api/v1/organization/structure/"


class TemplateBase(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.types = {t.code: t for t in UnitType.objects.all()}
        cls.desig = {d.code: d for d in SpecialistDesignation.objects.all()}

    def admin(self):
        return self.client_for(self.make_user("adm", "hq_admin"))

    def add(self, client, code, parent, type_code=None, **extra):
        body = {"level": "unit", "parent": str(self.unit(parent).pk), "code": code, "name_en": code.title()}
        if type_code:
            body["unit_type"] = str(self.types[type_code].pk)
        body.update(extra)
        return client.post(UNITS, body, format="json")

    def chain(self, client, prefix="Q1"):
        """Qayb > Gaas > Guuto > Urur > Horin under Bari's Army command. Returns {type: code}."""
        codes, parent = {}, "BARI-ARMY"
        for tcode in ("QAYB", "GAAS", "GUUTO", "URUR", "HORIN"):
            code = f"{prefix}-{tcode}"
            r = self.add(client, code, parent, tcode)
            self.assertEqual(r.status_code, 201, r.data)
            codes[tcode], parent = code, code
        return codes

    def person(self, unit, name, status="active"):
        rank = Rank.objects.get(branch__code="ARMY", code="PA-03")
        p = pers.create_personnel(None, full_name=name, phone="", service_number=None, org_unit=self.unit(unit),
                                  rank=rank, status="active", effective_date=None)
        if status != "active":
            Personnel.objects.filter(pk=p.pk).update(status=status)
        return p


class SeededReferenceTests(TemplateBase):
    def test_regions_and_regional_army_commands(self):
        self.assertEqual(set(OU.objects.filter(level="region").values_list("name_en", flat=True)),
                         {"Bari", "Karkaar", "Nugaal", "Mudug"})
        tg = OU.objects.filter(unit_type__code="TALISKA_GUUD")
        self.assertEqual({u.code for u in tg}, {"BARI-ARMY", "KARKAAR-ARMY", "NUGAAL-ARMY", "MUDUG-ARMY"})
        self.assertTrue(all(u.level == "branch_command" and u.branch.code == "ARMY" for u in tg))
        self.assertFalse(OU.objects.filter(branch__code__in=["NAVY"], unit_type__isnull=False).exists())

    def test_template_levels_and_reference_strengths(self):
        rows = [(t.code, t.tier, t.parent_type.code if t.parent_type else None, t.reference_min, t.reference_max,
                 t.standard_per_parent) for t in UnitType.objects.order_by("tier")]
        self.assertEqual(rows, [
            ("TALISKA_GUUD", 1, None, None, None, None), ("QAYB", 2, "TALISKA_GUUD", 6000, 7000, None),
            ("GAAS", 3, "QAYB", 3500, 3500, 2), ("GUUTO", 4, "GAAS", 900, 1001, None),
            ("URUR", 5, "GUUTO", 320, 330, None), ("HORIN", 6, "URUR", 99, 99, None),
            ("KOOX", 7, "HORIN", 33, 33, None), ("UNUG", 8, "KOOX", 9, 9, None)])
        self.assertEqual(self.types["TALISKA_GUUD"].description_en, "Regional command")

    def test_specialist_designations_are_not_ranks(self):
        self.assertEqual(set(SpecialistDesignation.objects.values_list("code", flat=True)), {"SAHAN", "SANCO"})
        self.assertEqual(self.desig["SAHAN"].description_en, "Reconnaissance designation")
        self.assertEqual(self.desig["SANCO"].description_en, "Miino baar / bomb squad designation")
        self.assertFalse(Rank.objects.filter(name_en__in=["Sahan", "Sanco"]).exists())
        pairs = {(r.parent_type.code, r.child_type.code, r.designation.code) for r in DesignationRule.objects.all()}
        self.assertEqual(pairs, {("GUUTO", "HORIN", "SAHAN"), ("GAAS", "URUR", "SAHAN"), ("GAAS", "URUR", "SANCO")})

    def test_no_somali_text_is_invented(self):
        self.assertEqual(SpecialistDesignation.objects.exclude(description_so="").count(), 0)
        self.assertEqual(UnitType.objects.exclude(description_so="").count(), 0)

    def test_seed_is_idempotent_and_keeps_administrator_edits(self):
        UnitType.objects.filter(code="QAYB").update(reference_max=7500)
        before = (UnitType.objects.count(), SpecialistDesignation.objects.count(), DesignationRule.objects.count())
        call_command("seed_reference_data", verbosity=0)
        self.assertEqual(before, (UnitType.objects.count(), SpecialistDesignation.objects.count(), DesignationRule.objects.count()))
        self.assertEqual(UnitType.objects.get(code="QAYB").reference_max, 7500)

    def test_seeding_never_creates_personnel(self):
        call_command("seed_reference_data", verbosity=0)
        self.assertEqual(Personnel.objects.count(), 0)


class RankReplacementTests(TemplateBase):
    def test_upgrade_replaces_provisional_ranks_without_orphaning_people(self):
        army = ServiceBranch.objects.get(code="ARMY")
        held = Rank.objects.create(branch=army, category="enlisted", code="E-3", name_en="Private First Class",
                                   sort_order=3, approval_status="approved", name_so="x")
        unused_draft = Rank.objects.create(branch=army, category="enlisted", code="E-1", name_en="Private", sort_order=1)
        unused_approved = Rank.objects.create(branch=army, category="officer", code="O-1", name_en="Second Lieutenant",
                                              sort_order=20, approval_status="approved", name_so="x")
        person = Personnel.objects.create(full_name="Held Rank", branch=army, org_unit=self.unit("BARI-ARMY"),
                                          rank=held, status="active")
        created, removed, deactivated = apply_official_ranks(Rank, Personnel, army, timezone.now())
        self.assertEqual((created, removed, deactivated), (0, 1, 2))
        person.refresh_from_db()
        self.assertEqual(person.rank_id, held.pk)                      # nobody was re-ranked or orphaned
        held.refresh_from_db()
        self.assertFalse(held.active)                                  # kept for history, no longer assignable
        self.assertFalse(Rank.objects.filter(pk=unused_draft.pk).exists())
        unused_approved.refresh_from_db()
        self.assertFalse(unused_approved.active)
        self.assertEqual(Rank.objects.filter(active=True).count(), 18)
        self.assertEqual(apply_official_ranks(Rank, Personnel, army, timezone.now()), (0, 0, 0))  # re-run is a no-op

    def test_retired_provisional_rank_cannot_be_assigned_to_new_people(self):
        army = ServiceBranch.objects.get(code="ARMY")
        old = Rank.objects.create(branch=army, category="enlisted", code="E-3", name_en="Private First Class",
                                  sort_order=1003, approval_status="approved", name_so="x", active=False)
        c = self.client_for(self.make_user("mgr", "branch_admin", unit="BARI-ARMY", branch="ARMY"))
        r = c.post("/api/v1/personnel/", {"full_name": "New Person", "org_unit": str(self.unit("BARI-ARMY").pk),
                                          "rank": str(old.pk), "status": "active", "phone": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("rank_inactive", self.codes(r, "rank"))

    def test_navy_and_police_ranks_are_untouched(self):
        navy = ServiceBranch.objects.get(code="NAVY")
        r = Rank.objects.create(branch=navy, category="enlisted", code="N-1", name_en="Seaman", sort_order=1)
        apply_official_ranks(Rank, Personnel, ServiceBranch.objects.get(code="ARMY"), timezone.now())
        r.refresh_from_db()
        self.assertTrue(r.active)

    def test_catalogue_is_manageable_through_the_api_without_code_changes(self):
        c = self.admin()
        rank = Rank.objects.get(code="PA-10")
        r = c.patch(f"/api/v1/ranks/{rank.pk}/", {"name_so": "Kabtan", "version": rank.version}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["approval_status"], "draft")  # identity changed, so it must be re-approved
        self.assertTrue(AuditEvent.objects.filter(action="rank.update", entity_id=str(rank.pk)).exists())
        army = ServiceBranch.objects.get(code="ARMY")
        r = c.post("/api/v1/ranks/", {"branch": str(army.pk), "category": "unspecified", "code": "PA-19",
                                      "name_en": "New rank", "sort_order": 19}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        reader = self.client_for(self.make_user("rd", "read_only", unit="BARI"))
        self.assertEqual(reader.post("/api/v1/ranks/", {}, format="json").status_code, 403)
        listed = reader.get("/api/v1/ranks/", {"approval_status": "approved", "active": "true", "page_size": 100}).data["results"]
        self.assertEqual([x["name_en"] for x in listed if x["code"].startswith("PA-") and x["code"] != "PA-10"],
                         [n for n in OFFICIAL_ARMY_RANKS if n != "Captain"])


class UnitTypeAssignmentTests(TemplateBase):
    def test_admin_builds_the_standard_chain(self):
        c = self.admin()
        codes = self.chain(c)
        self.assertEqual(OU.objects.get(code=codes["HORIN"]).unit_type.code, "HORIN")
        ev = AuditEvent.objects.filter(action="org_unit.create", entity_type="organizational_unit").latest("occurred_at")
        self.assertEqual(ev.metadata["type"], str(self.types["HORIN"].pk))

    def test_type_must_fit_the_level_and_the_hierarchy(self):
        c = self.admin()
        qayb = self.add(c, "QX", "BARI-ARMY", "QAYB")
        self.assertEqual(qayb.status_code, 201)
        bad = self.add(c, "TG-ON-UNIT", "BARI-ARMY", "TALISKA_GUUD")
        self.assertIn("unit_type_level_mismatch", self.codes(bad, "unit_type"))
        army = str(ServiceBranch.objects.get(code="ARMY").pk)
        # A Qayb is also the regional command (branch-command level); a Guuto is never a command.
        ok = c.post(UNITS, {"level": "branch_command", "parent": str(self.unit("BARI").pk), "branch": army,
                            "code": "BARI-ARMY-2", "name_en": "x", "unit_type": str(self.types["QAYB"].pk)}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        r = c.post(UNITS, {"level": "branch_command", "parent": str(self.unit("BARI").pk), "branch": army,
                           "code": "BARI-ARMY-3", "name_en": "x", "unit_type": str(self.types["GUUTO"].pk)}, format="json")
        self.assertIn("unit_type_level_mismatch", self.codes(r, "unit_type"))
        inverted = self.add(c, "KX", "QX", "QAYB")  # a Qayb inside a Qayb
        self.assertIn("unit_type_tier_order", self.codes(inverted, "unit_type"))
        self.add(c, "KOOX1", "QX", "KOOX")
        up = self.add(c, "GX", "KOOX1", "GAAS")  # a Gaas below a Koox
        self.assertIn("unit_type_tier_order", self.codes(up, "unit_type"))

    def test_changing_type_cannot_break_the_order_of_existing_children(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        self.add(c, "GX", "QX", "GAAS")
        unit = OU.objects.get(code="QX")
        r = c.patch(f"{UNITS}{unit.pk}/", {"unit_type": str(self.types["KOOX"].pk), "version": unit.version}, format="json")
        self.assertIn("unit_type_tier_order", self.codes(r, "unit_type"))

    def test_inactive_type_cannot_be_assigned(self):
        UnitType.objects.filter(code="KOOX").update(active=False)
        r = self.add(self.admin(), "K1", "BARI-ARMY", "KOOX")
        self.assertIn("unit_type_inactive", self.codes(r, "unit_type"))

    def test_designations_apply_to_units_only_and_changes_are_audited(self):
        c = self.admin()
        codes = self.chain(c)
        horin = OU.objects.get(code=codes["HORIN"])
        r = c.patch(f"{UNITS}{horin.pk}/", {"designations": [str(self.desig["SAHAN"].pk)], "version": horin.version}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["designations"], [self.desig["SAHAN"].pk])
        ev = AuditEvent.objects.get(action="org_unit.designations_change", entity_id=str(horin.pk))
        self.assertEqual((ev.metadata["from"], ev.metadata["to"]), ([], ["SAHAN"]))
        cmd = self.unit("BARI-ARMY")
        bad = c.patch(f"{UNITS}{cmd.pk}/", {"designations": [str(self.desig["SANCO"].pk)], "version": cmd.version}, format="json")
        self.assertIn("designation_level_mismatch", self.codes(bad, "designations"))
        SpecialistDesignation.objects.filter(code="SANCO").update(active=False)
        horin.refresh_from_db()
        bad = c.patch(f"{UNITS}{horin.pk}/", {"designations": [str(self.desig["SANCO"].pk)], "version": horin.version}, format="json")
        self.assertIn("designation_inactive", self.codes(bad, "designations"))

    def test_type_change_is_audited_with_from_and_to(self):
        c = self.admin()
        self.add(c, "UX", "BARI-ARMY", "KOOX")
        unit = OU.objects.get(code="UX")
        c.patch(f"{UNITS}{unit.pk}/", {"unit_type": str(self.types["UNUG"].pk), "version": unit.version}, format="json")
        ev = AuditEvent.objects.get(action="org_unit.type_change", entity_id=str(unit.pk))
        self.assertEqual((ev.metadata["from"], ev.metadata["to"]), (str(self.types["KOOX"].pk), str(self.types["UNUG"].pk)))

    def test_stale_version_still_conflicts(self):
        c = self.admin()
        self.add(c, "UX", "BARI-ARMY", "KOOX")
        unit = OU.objects.get(code="UX")
        c.patch(f"{UNITS}{unit.pk}/", {"name_en": "One", "version": unit.version}, format="json")
        r = c.patch(f"{UNITS}{unit.pk}/", {"name_en": "Two", "version": unit.version}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (409, "version_conflict"))

    def test_scoped_admins_can_only_change_units_in_their_scope(self):
        c = self.admin()
        self.add(c, "NX", "NUGAAL-ARMY", "QAYB")
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        far = OU.objects.get(code="NX")
        self.assertEqual(chief.get(f"{UNITS}{far.pk}/").status_code, 404)
        r = chief.patch(f"{UNITS}{far.pk}/", {"unit_type": str(self.types["GAAS"].pk), "version": far.version}, format="json")
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(OU.objects.get(code="NX").unit_type.code, "QAYB")

    def test_unit_list_filters(self):
        c = self.admin()
        codes = self.chain(c)
        sahan = str(self.desig["SAHAN"].pk)
        horin = OU.objects.get(code=codes["HORIN"])
        c.patch(f"{UNITS}{horin.pk}/", {"designations": [sahan], "version": horin.version}, format="json")
        ids = lambda r: {u["code"] for u in r.data["results"]}
        self.assertEqual(ids(c.get(UNITS, {"unit_type": str(self.types["GAAS"].pk)})), {codes["GAAS"]})
        self.assertEqual(ids(c.get(UNITS, {"designation": sahan})), {codes["HORIN"]})
        self.assertIn(codes["QAYB"], ids(c.get(UNITS, {"q": "q1-qa"})))
        self.assertTrue(all(u["level"] in ("branch_command", "unit") for u in c.get(UNITS, {"placeable": "1", "page_size": 100}).data["results"]))
        self.assertEqual(c.get(UNITS, {"unit_type": "nope"}).status_code, 400)


class StrengthTests(TemplateBase):
    def test_reference_strength_is_information_not_a_constraint(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        mgr = self.client_for(self.make_user("hqs", "regional_chief", unit="BARI"))
        for i in range(3):
            self.person("QX", f"Synthetic {i}")
        rows = {r["code"]: r for r in mgr.get(STRUCT, {"type": "QAYB"}).data["results"]}
        row = rows["QX"]
        self.assertEqual((row["actual_strength"], row["reference_min"], row["reference_max"], row["strength_status"]),
                         (3, 6000, 7000, "below"))
        self.assertEqual(Personnel.objects.count(), 3)  # nothing was created to fill the gap

    def test_above_reference_is_allowed_and_reported(self):
        c = self.admin()
        self.add(c, "KX", "BARI-ARMY", "UNUG")
        mgr = self.client_for(self.make_user("hqs", "regional_chief", unit="BARI"))
        for i in range(10):
            self.person("KX", f"Synthetic {i}")
        row = mgr.get(STRUCT, {"type": "UNUG"}).data["results"][0]
        self.assertEqual((row["actual_strength"], row["strength_status"]), (10, "above"))

    def test_rollup_counts_subtree_and_excludes_people_who_left(self):
        c = self.admin()
        codes = self.chain(c)
        mgr = self.client_for(self.make_user("hqs", "regional_chief", unit="BARI"))
        self.person(codes["HORIN"], "A")
        self.person(codes["URUR"], "B")
        self.person(codes["HORIN"], "C", status="retired")
        rows = {r["code"]: r["actual_strength"] for r in mgr.get(STRUCT, {"page_size": 100}).data["results"]}
        self.assertEqual((rows[codes["HORIN"]], rows[codes["URUR"]], rows[codes["QAYB"]]), (1, 2, 2))

    def test_approved_exception_changes_the_comparison_and_is_audited(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        unit = OU.objects.get(code="QX")
        r = c.patch(f"{UNITS}{unit.pk}/", {"strength_exception_min": 100, "strength_exception_max": 5000, "version": unit.version}, format="json")
        self.assertIn("exception_note_required", self.codes(r, "strength_exception_note"))
        r = c.patch(f"{UNITS}{unit.pk}/", {"strength_exception_min": 5000, "strength_exception_max": 100,
                                           "strength_exception_note": "Approved variation", "version": unit.version}, format="json")
        self.assertIn("range_order", self.codes(r, "strength_exception_max"))
        r = c.patch(f"{UNITS}{unit.pk}/", {"strength_exception_min": 100, "strength_exception_max": 5000,
                                           "strength_exception_note": "Approved variation", "version": unit.version}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        unit.refresh_from_db()
        self.assertEqual(unit.strength_exception_by.username, "adm")
        self.assertIsNotNone(unit.strength_exception_at)
        ev = AuditEvent.objects.get(action="org_unit.strength_exception", entity_id=str(unit.pk))
        self.assertEqual(ev.metadata["to"], [100, 5000])
        mgr = self.client_for(self.make_user("hqs", "regional_chief", unit="BARI"))
        for i in range(3):
            self.person("QX", f"Synthetic {i}")
        row = mgr.get(STRUCT, {"type": "QAYB"}).data["results"][0]
        self.assertEqual((row["has_exception"], row["reference_min"], row["reference_max"], row["strength_status"]),
                         (True, 100, 5000, "below"))
        unit.refresh_from_db()
        r = c.patch(f"{UNITS}{unit.pk}/", {"strength_exception_min": None, "strength_exception_max": None, "version": unit.version}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        unit.refresh_from_db()
        self.assertEqual((unit.strength_exception_note, unit.strength_exception_by), ("", None))  # clearing wipes the stamp

    def test_strength_needs_personnel_view_and_respects_scope(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        self.add(c, "NQ", "NUGAAL-ARMY", "QAYB")
        self.person("QX", "Synthetic Bari")
        self.person("NQ", "Synthetic Nugaal")
        auditor = self.client_for(self.make_user("aud", "auditor"))  # org.view everywhere, no personnel.view
        rows = auditor.get(STRUCT, {"type": "QAYB"}).data["results"]
        self.assertEqual({r["code"]: r["actual_strength"] for r in rows}, {"QX": None, "NQ": None})
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        rows = chief.get(STRUCT, {"type": "QAYB"}).data["results"]
        self.assertEqual({r["code"]: r["actual_strength"] for r in rows}, {"QX": 1})  # Nugaal is not visible at all


class FindingsTests(TemplateBase):
    def findings(self, client):
        return client.get(STRUCT + "findings/").data["results"]

    def test_two_gaas_per_qayb_is_reported_not_enforced(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        self.add(c, "G1", "QX", "GAAS")
        f = [x for x in self.findings(c) if x["code"] == "child_count" and x["unit"]["code"] == "QX"]
        self.assertEqual((f[0]["expected"], f[0]["actual"]), (2, 1))
        self.add(c, "G2", "QX", "GAAS")
        self.assertEqual([x for x in self.findings(c) if x["code"] == "child_count" and x["unit"]["code"] == "QX"], [])
        self.assertEqual(self.add(c, "G3", "QX", "GAAS").status_code, 201)  # an approved variation is allowed
        f = [x for x in self.findings(c) if x["code"] == "child_count" and x["unit"]["code"] == "QX"]
        self.assertEqual(f[0]["actual"], 3)

    def test_guuto_needs_a_horin_sahan_and_gaas_needs_urur_sahan_and_sanco(self):
        c = self.admin()
        codes = self.chain(c)
        missing = {(x["unit"]["code"], x["designation"]) for x in self.findings(c) if x["code"] == "missing_designated_unit"}
        self.assertEqual(missing, {(codes["GUUTO"], "SAHAN"), (codes["GAAS"], "SAHAN"), (codes["GAAS"], "SANCO")})
        horin, urur = OU.objects.get(code=codes["HORIN"]), OU.objects.get(code=codes["URUR"])
        c.patch(f"{UNITS}{horin.pk}/", {"designations": [str(self.desig["SAHAN"].pk)], "version": horin.version}, format="json")
        c.patch(f"{UNITS}{urur.pk}/", {"designations": [str(self.desig["SAHAN"].pk), str(self.desig["SANCO"].pk)], "version": urur.version}, format="json")
        self.assertEqual([x for x in self.findings(c) if x["code"] == "missing_designated_unit"], [])

    def test_designation_must_be_on_the_right_type_of_unit(self):
        c = self.admin()
        codes = self.chain(c)
        guuto = OU.objects.get(code=codes["GUUTO"])  # a Sahan on the Guuto itself is not a Horin Sahan
        c.patch(f"{UNITS}{guuto.pk}/", {"designations": [str(self.desig["SAHAN"].pk)], "version": guuto.version}, format="json")
        missing = {(x["unit"]["code"], x["designation"]) for x in self.findings(c) if x["code"] == "missing_designated_unit"}
        self.assertIn((codes["GUUTO"], "SAHAN"), missing)

    def test_non_standard_parent_is_flagged(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        self.add(c, "G1", "QX", "GAAS")
        self.add(c, "H1", "G1", "HORIN")  # skips Guuto and Urur
        f = [x for x in self.findings(c) if x["code"] == "non_standard_parent"]
        self.assertEqual([(x["unit"]["code"], x["parent_type"]) for x in f], [("H1", "GAAS")])

    def test_findings_are_limited_to_the_callers_scope(self):
        c = self.admin()
        self.add(c, "NQ", "NUGAAL-ARMY", "QAYB")
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        self.assertNotIn("NQ", {x["unit"]["code"] for x in self.findings(chief)})
        self.assertIn("NQ", {x["unit"]["code"] for x in self.findings(c)})

    def test_inactive_rule_is_not_checked(self):
        c = self.admin()
        self.chain(c)
        DesignationRule.objects.update(active=False)
        self.assertEqual([x for x in self.findings(c) if x["code"] == "missing_designated_unit"], [])


class CatalogueApiTests(TemplateBase):
    def test_everyone_with_org_view_can_read_only_hq_admins_can_change(self):
        reader = self.client_for(self.make_user("rd", "read_only", unit="BARI"))
        for url in (TYPES, DESIGS, RULES):
            self.assertEqual(reader.get(url).status_code, 200, url)
        self.assertEqual(len(reader.get(TYPES).data), 8)
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        self.assertEqual(chief.post(TYPES, {"code": "NEWT", "name_en": "x", "tier": 9}, format="json").status_code, 403)
        self.assertEqual(chief.post(DESIGS, {"code": "NEWD", "name_en": "x"}, format="json").status_code, 403)
        self.assertEqual(chief.patch(f"{TYPES}{self.types['QAYB'].pk}/", {"reference_max": 1, "version": 1}, format="json").status_code, 403)
        anon = self.client_class()
        self.assertIn(anon.get(TYPES).status_code, (401, 403))

    @override_settings(STRUCTURE_CHANGES_REQUIRE_APPROVAL=False)
    def test_admin_manages_types_designations_and_rules_with_audit(self):
        c = self.admin()
        r = c.post(TYPES, {"code": "pelo", "name_en": "Pelo", "tier": 9, "parent_type": str(self.types["UNUG"].pk),
                           "reference_min": 3, "reference_max": 3}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (201, "PELO"), r.data)
        r2 = c.patch(f"{TYPES}{r.data['id']}/", {"reference_max": 4, "version": r.data["version"]}, format="json")
        self.assertEqual(r2.status_code, 200)
        d = c.post(DESIGS, {"code": "xaal", "name_en": "Xaal", "name_so": "Xaal"}, format="json")
        self.assertEqual(d.status_code, 201, d.data)
        rule = c.post(RULES, {"parent_type": str(self.types["QAYB"].pk), "child_type": str(self.types["GAAS"].pk),
                              "designation": d.data["id"], "note": "test"}, format="json")
        self.assertEqual(rule.status_code, 201, rule.data)
        toggled = c.patch(f"{RULES}{rule.data['id']}/", {"active": False, "version": rule.data["version"]}, format="json")
        self.assertEqual(toggled.status_code, 200)
        for action in ("unit_type.create", "unit_type.update", "specialist_designation.create", "designation_rule.create",
                       "designation_rule.update"):
            self.assertTrue(AuditEvent.objects.filter(action=action, outcome="success").exists(), action)

    @override_settings(STRUCTURE_CHANGES_REQUIRE_APPROVAL=False)
    def test_catalogue_validation(self):
        c = self.admin()
        self.assertIn("code_taken", self.codes(c.post(TYPES, {"code": "qayb", "name_en": "x", "tier": 9}, format="json"), "code"))
        self.assertIn("invalid_code", self.codes(c.post(TYPES, {"code": "bad code", "name_en": "x", "tier": 9}, format="json"), "code"))
        self.assertIn("range_order", self.codes(c.post(TYPES, {"code": "AAA", "name_en": "x", "tier": 9, "reference_min": 9, "reference_max": 1}, format="json"), "reference_max"))
        self.assertIn("tier_order", self.codes(c.post(TYPES, {"code": "AAB", "name_en": "x", "tier": 2, "parent_type": str(self.types["GAAS"].pk)}, format="json"), "parent_type"))
        q = self.types["QAYB"]
        self.assertIn("immutable_field", self.codes(c.patch(f"{TYPES}{q.pk}/", {"code": "OTHER", "version": q.version}, format="json"), "code"))
        self.assertIn("code_taken", self.codes(c.post(DESIGS, {"code": "sahan", "name_en": "x"}, format="json"), "code"))
        rule = DesignationRule.objects.first()
        r = c.post(RULES, {"parent_type": str(rule.parent_type_id), "child_type": str(rule.child_type_id),
                           "designation": str(rule.designation_id)}, format="json")
        self.assertIn("rule_exists", self.codes(r, "designation"))
        r = c.post(RULES, {"parent_type": str(self.types["GAAS"].pk), "child_type": str(self.types["QAYB"].pk),
                           "designation": str(self.desig["SAHAN"].pk)}, format="json")
        self.assertIn("tier_order", self.codes(r, "child_type"))
        self.assertIn("immutable_field", self.codes(c.patch(f"{RULES}{rule.pk}/", {"child_type": str(self.types["KOOX"].pk), "version": rule.version}, format="json"), "child_type"))

    @override_settings(STRUCTURE_CHANGES_REQUIRE_APPROVAL=False)
    def test_in_use_types_and_designations_cannot_be_deactivated(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        q = self.types["QAYB"]
        self.assertIn("type_in_use", self.codes(c.patch(f"{TYPES}{q.pk}/", {"active": False, "version": q.version}, format="json"), "active"))
        unit = OU.objects.get(code="QX")
        c.patch(f"{UNITS}{unit.pk}/", {"designations": [str(self.desig["SAHAN"].pk)], "version": unit.version}, format="json")
        s = self.desig["SAHAN"]
        self.assertIn("designation_in_use", self.codes(c.patch(f"{DESIGS}{s.pk}/", {"active": False, "version": s.version}, format="json"), "active"))

    def test_unknown_catalogue_ids_are_a_clean_404(self):
        import uuid
        c = self.admin()
        self.assertEqual(c.get(f"{TYPES}{uuid.uuid4()}/").status_code, 404)
        self.assertEqual(c.get(f"{UNITS}{uuid.uuid4()}/").status_code, 404)


class PersonnelIntegrationTests(TemplateBase):
    def test_personnel_in_template_units_work_and_expose_the_unit_type(self):
        c = self.admin()
        self.add(c, "QX", "BARI-ARMY", "QAYB")
        self.person("QX", "Synthetic Person")
        mgr = self.client_for(self.make_user("hqs", "regional_chief", unit="BARI"))
        r = mgr.get("/api/v1/personnel/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["results"][0]["org_unit"]["unit_type"], self.types["QAYB"].pk)
        self.assertEqual(r.data["results"][0]["rank"]["code"], "PA-03")
