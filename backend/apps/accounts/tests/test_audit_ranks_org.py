from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent, AuditImmutableError
from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import PlacementError
from apps.ranks.models import Rank


class AuditTests(BaseApiTest):
    def test_audit_events_are_append_only_in_the_application(self):
        ev = AuditEvent.objects.create(action="test.event", outcome="success")
        ev.action = "changed"
        with self.assertRaises(AuditImmutableError):
            ev.save()
        with self.assertRaises(AuditImmutableError):
            ev.delete()
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.all().delete()
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.filter(pk=ev.pk).update(action="x")

    def test_only_audit_view_holders_can_read_and_there_is_no_write_api(self):
        auditor = self.client_for(self.make_user("aud", "auditor"))
        self.assertEqual(auditor.get("/api/v1/audit-events/").status_code, 200)
        self.assertIn(auditor.post("/api/v1/audit-events/", {}, format="json").status_code, (403, 405))
        self.assertIn(auditor.delete("/api/v1/audit-events/", format="json").status_code, (403, 405))
        chief = self.client_for(self.make_user("chief", "regional_chief", unit="BARI"))
        self.assertEqual(chief.get("/api/v1/audit-events/").status_code, 403)

    def test_correlation_id_is_echoed_and_recorded(self):
        c = self.client_for(self.make_user("rd", "read_only"))
        c.post("/api/v1/auth/mfa/setup/", HTTP_X_REQUEST_ID="trace-abc-123")
        r = c.get("/api/v1/ranks/", HTTP_X_REQUEST_ID="trace-abc-123")
        self.assertEqual(r["X-Request-ID"], "trace-abc-123")
        c.post("/api/v1/users/", {}, format="json", HTTP_X_REQUEST_ID="trace-denied-1")
        self.assertTrue(AuditEvent.objects.filter(correlation_id="trace-denied-1", outcome="denied").exists())


class RankTests(BaseApiTest):
    OFFICIAL = ["Dable", "Alifle", "2 Alifle", "Saddex Alifle", "Isbatoore", "Laba Xarigle", "Saddex Xarigle", "Xidigle",
                "Laba Xidigle", "Captain", "Gaashanle", "Gaashanle dhexe", "Gaashanle sare", "Sarreye Guuto (General)",
                "Sarreye Gaas", "Sarreye Guud (Marshall)", "Commander of the Puntland Defense Forces",
                "President / Commander-in-Chief"]

    def test_seed_is_the_18_official_army_ranks_in_order(self):
        qs = Rank.objects.filter(active=True).order_by("sort_order")
        self.assertEqual(qs.count(), 18)
        self.assertEqual([r.name_en for r in qs], self.OFFICIAL)  # exact names, exact order
        self.assertEqual([r.sort_order for r in qs], list(range(1, 19)))
        self.assertEqual({r.branch.code for r in qs}, {"ARMY"})
        self.assertFalse(qs.exclude(approval_status="approved").exists())
        # no translation is invented: the supplied name is used for both languages
        self.assertTrue(all(r.name_so == r.name_en for r in qs))
        self.assertFalse(Rank.objects.filter(code__regex=r"^[EWO]-").exists())  # no provisional US-style ranks remain

    def test_seed_is_idempotent_and_keeps_edits(self):
        from django.core.management import call_command
        r = Rank.objects.get(code="PA-10")
        Rank.objects.filter(pk=r.pk).update(name_so="Kabtan")
        call_command("seed_reference_data", verbosity=0)
        r.refresh_from_db()
        self.assertEqual((Rank.objects.count(), r.approval_status, r.name_so), (18, "approved", "Kabtan"))

    def test_approval_workflow(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        Rank.objects.filter(code="PA-10").update(approval_status="draft", approved_at=None, name_so="")
        rank = Rank.objects.get(code="PA-10")
        url = f"/api/v1/ranks/{rank.pk}/"
        r = c.post(f"{url}approve/")
        self.assertEqual((r.status_code, r.data["code"]), (409, "somali_name_required"))
        r = c.patch(url, {"name_so": "Kabtan", "version": rank.version}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = c.post(f"{url}approve/")
        self.assertEqual((r.status_code, r.data["approval_status"]), (200, "approved"))
        # editing an approved rank's identity voids the approval
        r = c.patch(url, {"name_en": "Captain (rev)", "version": r.data["version"]}, format="json")
        self.assertEqual(r.data["approval_status"], "draft")
        self.assertIsNone(r.data["approved_at"])
        self.assertTrue(AuditEvent.objects.filter(action="rank.approve", outcome="success").exists())

    def test_stale_version_conflicts(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        rank = Rank.objects.get(code="PA-05")
        url = f"/api/v1/ranks/{rank.pk}/"
        c.patch(url, {"name_so": "A", "version": 1}, format="json")
        r = c.patch(url, {"name_so": "B", "version": 1}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (409, "version_conflict"))

    def test_only_authorised_roles_edit_or_approve(self):
        rank = Rank.objects.get(code="PA-01")
        reader = self.client_for(self.make_user("rd", "read_only", unit="BARI"))
        self.assertEqual(reader.get("/api/v1/ranks/").status_code, 200)
        self.assertEqual(reader.patch(f"/api/v1/ranks/{rank.pk}/", {"name_so": "x", "version": 1},
                                      format="json").status_code, 403)
        chief = self.client_for(self.make_user("ch", "regional_chief", unit="BARI"))
        self.assertEqual(chief.post(f"/api/v1/ranks/{rank.pk}/approve/").status_code, 403)

    def test_duplicate_rank_code_per_branch_is_rejected(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        army = Rank.objects.get(code="PA-01").branch
        r = c.post("/api/v1/ranks/", {"branch": str(army.pk), "category": "enlisted", "code": "pa-01",
                                      "name_en": "Dup"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("rank_code_taken", self.codes(r, "code"))
        navy = army.__class__.objects.get(code="NAVY")
        r = c.post("/api/v1/ranks/", {"branch": str(navy.pk), "category": "enlisted", "code": "E-1",
                                      "name_en": "Seaman Recruit"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)


class OrganizationRuleTests(BaseApiTest):
    def test_placement_rules_at_model_level(self):
        hq = self.unit("HQ")
        with self.assertRaises(PlacementError):
            OU.objects.create(code="BAD1", name_en="x", level="region", parent=None)
        with self.assertRaises(PlacementError):
            OU.objects.create(code="BAD2", name_en="x", level="unit", parent=hq)

    def test_second_hq_is_blocked_by_database_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OU.objects.create(code="HQ2", name_en="x", level="headquarters")

    def test_api_rejects_bad_placement_and_second_hq(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        r = c.post("/api/v1/organization/units/", {"code": "U9", "name_en": "U", "level": "unit",
                                                   "parent": str(self.unit("BARI").pk)}, format="json")
        self.assertIn("unit_parent_invalid", self.codes(r, "level"))
        r = c.post("/api/v1/organization/units/", {"code": "HQ9", "name_en": "H", "level": "headquarters"},
                   format="json")
        self.assertIn("hq_exists", self.codes(r, "level"))

    def test_hq_admin_can_add_region_and_unit_inherits_branch(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        r = c.post("/api/v1/organization/units/", {"code": "sanaag", "name_en": "Sanaag", "level": "region",
                                                   "parent": str(self.unit("HQ").pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = c.post("/api/v1/organization/units/", {"code": "u-1", "name_en": "U1", "level": "unit",
                                                   "parent": str(self.unit("BARI-NAVY").pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(str(r.data["branch"]), str(self.unit("BARI-NAVY").branch_id))

    def test_structure_is_immutable_and_versioned(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        u = self.unit("BARI-ARMY")
        url = f"/api/v1/organization/units/{u.pk}/"
        r = c.patch(url, {"parent": str(self.unit("NUGAAL").pk), "version": 1}, format="json")
        self.assertIn("immutable_field", self.codes(r, "parent"))
        self.assertEqual(c.patch(url, {"name_en": "Bari Army HQ", "version": 1}, format="json").status_code, 200)
        r = c.patch(url, {"name_en": "Again", "version": 1}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (409, "version_conflict"))

    def test_cannot_deactivate_unit_with_active_children(self):
        c = self.client_for(self.make_user("adm", "hq_admin"))
        u = self.unit("BARI")
        r = c.patch(f"/api/v1/organization/units/{u.pk}/", {"active": False, "version": 1}, format="json")
        self.assertIn("has_active_children", self.codes(r, "active"))
