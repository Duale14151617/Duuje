"""Governed structure changes: propose -> submit -> a different person approves (and applies) or rejects. Synthetic data only."""
import json

from django.test import override_settings

from apps.accounts.models import Role, RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import StructureChange, UnitType

CHANGES = "/api/v1/organization/structure-changes/"
TYPES = "/api/v1/organization/unit-types/"


class Base(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("adm", "hq_admin"))
        self.approver = self.client_for(self.make_user("appr", "structure_approver"))

    def propose(self, ops, title="Add a level", client=None):
        return (client or self.admin).post(CHANGES, {"title": title, "rationale": "synthetic", "operations": ops}, format="json")

    def draft(self, ops=None, **kw):
        r = self.propose(ops or [self.new_type()], **kw)
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    @staticmethod
    def new_type(code="PELO", **over):
        body = {"op": "create", "code": code, "name_en": "Pelo", "name_so": "Pelo", "tier": 9, "parent_type": "UNUG",
                "reference_min": 3, "reference_max": 3}
        body.update(over)
        return body

    def submit(self, change, client=None):
        return (client or self.admin).post(f"{CHANGES}{change['id']}/submit/", {"version": change["version"]}, format="json")

    def approve(self, change, client=None, note="ok"):
        return (client or self.approver).post(f"{CHANGES}{change['id']}/approve/", {"version": change["version"], "note": note}, format="json")


class ExistingCapabilityTests(Base):
    def test_the_template_levels_and_standards_are_already_data(self):
        rows = {t.code: t for t in UnitType.objects.all()}
        self.assertEqual([c for c, _ in sorted(((c, t.tier) for c, t in rows.items()), key=lambda x: x[1])],
                         ["TALISKA_GUUD", "QAYB", "GAAS", "GUUTO", "URUR", "HORIN", "KOOX", "UNUG"])
        self.assertEqual((rows["GAAS"].parent_type.code, rows["GAAS"].standard_per_parent, rows["GAAS"].reference_min), ("QAYB", 2, 3500))


class GateTests(Base):
    def test_direct_edits_are_refused_by_default_but_reads_are_not(self):
        self.assertEqual(self.admin.get(TYPES).status_code, 200)
        r = self.admin.post(TYPES, {"code": "NEWT", "name_en": "x", "tier": 9}, format="json")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "approval_required"))
        q = UnitType.objects.get(code="QAYB")
        r = self.admin.patch(f"{TYPES}{q.pk}/", {"reference_max": 1, "version": q.version}, format="json")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "approval_required"))
        self.assertEqual(UnitType.objects.get(code="QAYB").reference_max, 7000)

    def test_permission_is_still_checked_before_the_gate(self):
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        self.assertEqual(chief.post(TYPES, {"code": "NEWT", "name_en": "x", "tier": 9}, format="json").status_code, 403)

    @override_settings(STRUCTURE_CHANGES_REQUIRE_APPROVAL=False)
    def test_gate_can_be_switched_off(self):
        r = self.admin.post(TYPES, {"code": "NEWT", "name_en": "x", "tier": 9}, format="json")
        self.assertEqual(r.status_code, 201)


class WorkflowTests(Base):
    def test_nothing_is_live_until_approved(self):
        before = list(UnitType.objects.order_by("code").values_list("code", "tier", "reference_max", "version"))
        c = self.draft()
        self.assertEqual((c["status"], c["impact"]["errors"], c["impact"]["created"]), ("draft", [], ["PELO"]))
        self.assertEqual(self.submit(c).status_code, 200)
        self.assertEqual(list(UnitType.objects.order_by("code").values_list("code", "tier", "reference_max", "version")), before)

    def test_approval_applies_atomically_and_is_audited(self):
        old_version = UnitType.objects.get(code="QAYB").version
        c = self.draft([self.new_type(), {"op": "update", "code": "QAYB", "fields": {"reference_max": 7500, "name_so": "Qayb (SO)"}}])
        sub = self.submit(c).json()
        r = self.approve(sub)
        self.assertEqual((r.status_code, r.json()["status"], r.json()["decided_by_username"]), (200, "approved", "appr"))
        pelo = UnitType.objects.get(code="PELO")
        self.assertEqual((pelo.parent_type.code, pelo.tier, pelo.reference_min), ("UNUG", 9, 3))
        qayb = UnitType.objects.get(code="QAYB")
        self.assertEqual((qayb.reference_max, qayb.name_so, qayb.version), (7500, "Qayb (SO)", old_version + 1))
        actions = set(AuditEvent.objects.filter(action__startswith=("structure_change.")).values_list("action", flat=True))
        self.assertEqual(actions, {"structure_change.create", "structure_change.submit", "structure_change.approve"})
        self.assertTrue(AuditEvent.objects.filter(action="unit_type.create", metadata__via="structure_change").exists())

    def test_new_levels_can_be_chained_inside_one_proposal(self):
        ops = [self.new_type("SAFF", name_en="Saff", tier=9, parent_type="UNUG"),
               self.new_type("DHIG", name_en="Dhig", tier=10, parent_type="SAFF")]
        r = self.approve(self.submit(self.draft(ops)).json())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(UnitType.objects.get(code="DHIG").parent_type.code, "SAFF")

    def test_a_different_person_must_approve(self):
        both = self.make_user("both", "hq_admin")
        RoleAssignment.objects.create(user=both, role=Role.objects.get(code="structure_approver"), org_unit=self.unit("HQ"))
        c = self.client_for(User.objects.get(pk=both.pk))
        draft = self.propose([self.new_type()], client=c).json()
        sub = self.submit(draft, client=c).json()
        r = self.approve(sub, client=c)
        self.assertEqual((r.status_code, r.json()["code"]), (403, "self_approval_forbidden"))
        self.assertFalse(UnitType.objects.filter(code="PELO").exists())
        self.assertEqual(self.approve(sub).status_code, 200)

    def test_only_the_proposer_submits_and_only_approvers_decide(self):
        c = self.draft()
        self.assertEqual(self.approve(c, client=self.admin).status_code, 403)  # admins cannot approve
        other = self.client_for(self.make_user("adm2", "hq_admin"))
        self.assertEqual(self.submit(c, client=other).status_code, 403)

    def test_rejection_needs_a_reason_and_changes_nothing(self):
        sub = self.submit(self.draft()).json()
        url = f"{CHANGES}{sub['id']}/reject/"
        r = self.approver.post(url, {"version": sub["version"]}, format="json")
        self.assertEqual(self.codes(r, "note"), ["note_required"])
        r = self.approver.post(url, {"version": sub["version"], "note": "Not approved yet"}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "rejected"))
        self.assertFalse(UnitType.objects.filter(code="PELO").exists())
        self.assertEqual(self.approve(r.json()).status_code, 400)  # a rejected proposal cannot be approved

    def test_states_and_versions(self):
        c = self.draft()
        url = f"{CHANGES}{c['id']}/"
        self.assertEqual(self.codes(self.admin.patch(url, {"title": "Renamed"}, format="json"), "version"), ["version_required"])
        ok = self.admin.patch(url, {"title": "Renamed", "version": c["version"]}, format="json")
        self.assertEqual((ok.status_code, ok.json()["version"]), (200, c["version"] + 1))
        stale = self.admin.patch(url, {"title": "Again", "version": c["version"]}, format="json")
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "version_conflict"))
        sub = self.submit(ok.json()).json()
        self.assertEqual(self.codes(self.admin.patch(url, {"title": "x" * 5, "version": sub["version"]}, format="json"), "status"), ["not_a_draft"])
        self.assertEqual(self.codes(self.submit(sub), "status"), ["invalid_transition"])

    def test_who_can_see_proposals(self):
        self.draft()
        self.assertEqual(self.admin.get(CHANGES).status_code, 200)
        self.assertEqual(self.approver.get(CHANGES).status_code, 200)
        for role in ("regional_chief", "auditor", "hq_reporting"):
            self.assertEqual(self.client_for(self.make_user(f"u_{role}", role, unit="BARI" if role == "regional_chief" else "HQ")).get(CHANGES).status_code, 403, role)


class ValidationTests(Base):
    def codes_of(self, r):
        return [e["code"] for e in r.json()["errors"]["operations"]]

    def test_shape_errors_are_rejected_on_save(self):
        cases = {
            "invalid_operations": [],
            "invalid_operation": [{"op": "delete", "code": "QAYB"}],
            "invalid_code": [{"op": "update", "code": "bad code", "fields": {"tier": 2}}],
            "duplicate_code": [self.new_type("AAA"), self.new_type("AAA")],
            "unknown_field": [{"op": "update", "code": "QAYB", "fields": {"code": "OTHER"}}],
            "missing_field": [{"op": "create", "code": "AAA", "name_en": "x"}],
            "invalid_value": [{"op": "update", "code": "QAYB", "fields": {"tier": "2"}}],
        }
        for code, ops in cases.items():
            self.assertEqual(self.codes_of(self.propose(ops)), [code], code)

    def impact_errors(self, ops):
        c = self.draft(ops)
        return {(e["code"], e.get("type")) for e in c["impact"]["errors"]}, c

    def test_semantic_problems_are_reported_and_block_submission(self):
        errors, c = self.impact_errors([{"op": "update", "code": "GAAS", "fields": {"tier": 2}}])
        self.assertIn(("tier_order", "GAAS"), errors)
        r = self.submit(c)
        self.assertEqual((r.status_code, self.codes(r, "operations")), (400, ["proposal_invalid"]))

    def test_other_rules(self):
        e, _ = self.impact_errors([self.new_type("QAYB")])
        self.assertIn(("code_taken", "QAYB"), e)
        e, _ = self.impact_errors([self.new_type(reference_min=9, reference_max=1)])
        self.assertIn(("range_order", "PELO"), e)
        e, _ = self.impact_errors([self.new_type(parent_type="NOPE")])
        self.assertIn(("unknown_parent_type", "PELO"), e)
        e, _ = self.impact_errors([{"op": "update", "code": "NOPE", "fields": {"tier": 3}}])
        self.assertIn(("unknown_type", "NOPE"), e)

    def test_types_in_use_cannot_be_deactivated(self):
        OU.objects.create(code="QX", name_en="QX", level="unit", parent=self.unit("BARI-ARMY"),
                          unit_type=UnitType.objects.get(code="QAYB"))
        e, c = self.impact_errors([{"op": "update", "code": "QAYB", "fields": {"active": False}}])
        self.assertIn(("type_in_use", "QAYB"), e)
        self.assertEqual(c["impact"]["units_by_type"]["QAYB"], 1)

    def test_existing_units_must_stay_consistent_with_new_tiers(self):
        qayb = OU.objects.create(code="QX", name_en="QX", level="unit", parent=self.unit("BARI-ARMY"),
                                 unit_type=UnitType.objects.get(code="QAYB"))
        OU.objects.create(code="GX", name_en="GX", level="unit", parent=qayb, unit_type=UnitType.objects.get(code="GAAS"))
        # Move Qayb below Gaas while keeping the type links valid: the catalogue is fine, but the real units would invert.
        ops = [{"op": "update", "code": "GAAS", "fields": {"tier": 2, "parent_type": "TALISKA_GUUD"}},
               {"op": "update", "code": "QAYB", "fields": {"tier": 3, "parent_type": "GAAS"}},
               {"op": "update", "code": "GUUTO", "fields": {"tier": 4}}]
        errors, c = self.impact_errors(ops)
        self.assertIn(("existing_units_conflict", None), errors)
        conflict = next(e for e in c["impact"]["errors"] if e["code"] == "existing_units_conflict")
        self.assertEqual((conflict["count"], conflict["sample"][0]["unit"]), (1, "GX"))

    def test_approval_rechecks_against_the_current_catalogue(self):
        sub = self.submit(self.draft()).json()
        UnitType.objects.create(code="PELO", name_en="Taken meanwhile", tier=9)  # someone else got there first
        r = self.approve(sub)
        self.assertEqual((r.status_code, self.codes(r, "operations")), (400, ["proposal_invalid"]))
        self.assertEqual(StructureChange.objects.get(pk=sub["id"]).status, "submitted")


class AccessControlTests(Base):
    def test_administrators_cannot_approve_by_default(self):
        perms = set(Role.objects.get(code="hq_admin").permissions.values_list("code", flat=True))
        self.assertIn("org.structure_propose", perms)
        self.assertNotIn("org.structure_approve", perms)

    def test_the_approver_role_holds_no_data_access(self):
        perms = set(Role.objects.get(code="structure_approver").permissions.values_list("code", flat=True))
        self.assertEqual(perms, {"dashboard.view", "org.view", "org.structure_approve"})
        self.assertTrue(Role.objects.get(code="structure_approver").is_privileged)  # MFA required

    def test_existing_units_and_scopes_are_untouched_by_a_level_change(self):
        unit = OU.objects.create(code="QX", name_en="QX", level="unit", parent=self.unit("BARI-ARMY"),
                                 unit_type=UnitType.objects.get(code="QAYB"))
        before = (unit.path, unit.level, unit.parent_id)
        self.approve(self.submit(self.draft([self.new_type()])).json())
        unit.refresh_from_db()
        self.assertEqual((unit.path, unit.level, unit.parent_id), before)

    def test_audit_never_contains_secrets_and_is_json(self):
        self.approve(self.submit(self.draft()).json())
        json.dumps(list(AuditEvent.objects.values("metadata")), default=str)
