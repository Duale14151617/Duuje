"""Integrations (2.0): credentials, scope, failure handling, audit. Synthetic data only."""
import json
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.integrations.authentication import IntegrationRateThrottle
from apps.integrations.models import IntegrationCall, IntegrationClient
from apps.organization.models import OrganizationalUnit as OU
from apps.personnel import services as pers
from apps.ranks.models import Rank

ADMIN = "/api/v1/integrations/clients/"
EXT = "/api/v1/ext/"


class IntegrationBase(BaseApiTest):
    def setUp(self):
        super().setUp()
        Rank.objects.filter(branch__code="ARMY", code="PA-03").update(approval_status="approved", name_so="x")
        self.rank = Rank.objects.get(branch__code="ARMY", code="PA-03")
        self.bari = OU.objects.create(code="BARI-ARMY-A", name_en="Bari A", level="unit", parent=self.unit("BARI-ARMY"))
        self.karkaar = OU.objects.create(code="KARKAAR-ARMY-A", name_en="Karkaar A", level="unit", parent=self.unit("KARKAAR-ARMY"))
        for i in range(7):
            self.person(f"Bari {i}", self.bari)
        for i in range(2):
            self.person(f"Karkaar {i}", self.karkaar)

    def person(self, name, unit):
        return pers.create_personnel(None, full_name=name, phone="", service_number=None, org_unit=unit, rank=self.rank,
                                     status="active", effective_date=None)

    def admin(self, with_data_access=True):
        """An HQ administrator. By design they hold no data permissions, so they are given the reporting role as well."""
        user = self.make_user("adm", "hq_admin")
        if with_data_access:
            RoleAssignment.objects.create(user=user, role=Role.objects.get(code="hq_reporting"), org_unit=self.unit("HQ"))
        return self.client_for(User.objects.get(pk=user.pk))

    def body(self, **over):
        data = {"name": "Ministry dashboard", "description": "synthetic", "scopes": ["personnel"], "org_unit": str(self.unit("BARI").pk),
                "expires_at": (timezone.now() + timedelta(days=30)).isoformat()}
        data.update(over)
        return data

    def make_client(self, admin=None, **over):
        admin = admin or self.admin()
        r = admin.post(ADMIN, self.body(**over), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def machine(self, key):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        return c


class DisabledByDefaultTests(IntegrationBase):
    def test_the_feature_is_off_by_default(self):
        from django.conf import settings
        self.assertFalse(settings.INTEGRATIONS_ENABLED)

    def test_creating_a_client_is_refused_while_disabled(self):
        r = self.admin().post(ADMIN, self.body(), format="json")
        self.assertEqual((r.status_code, r.json()["code"]), (403, "feature_disabled"))
        self.assertEqual(IntegrationClient.objects.count(), 0)

    def test_external_endpoints_do_not_exist_while_disabled(self):
        for url in (EXT + "me/", EXT + "analytics/personnel/"):
            self.assertEqual(APIClient().get(url).status_code, 404, url)
            self.assertEqual(self.machine("ahq_deadbeef_" + "a" * 43).get(url).status_code, 404, url)


@override_settings(INTEGRATIONS_ENABLED=True)
class AdministrationTests(IntegrationBase):
    def test_key_is_returned_once_and_only_a_hash_is_stored(self):
        data = self.make_client()
        key = data["key"]
        self.assertTrue(key.startswith("ahq_"))
        obj = IntegrationClient.objects.get(pk=data["id"])
        self.assertNotEqual(obj.key_hash, key)
        self.assertNotIn(key.split("_", 2)[2], json.dumps(list(IntegrationClient.objects.values()), default=str))
        admin = self.client_for(User.objects.get(username="adm"))
        for response in (admin.get(ADMIN), admin.get(f"{ADMIN}{data['id']}/")):
            text = response.content.decode()
            self.assertNotIn(key, text)
            self.assertNotIn("key_hash", text)
            self.assertNotIn("\"key\"", text)

    def test_nobody_can_grant_access_they_do_not_hold(self):
        bare = self.admin(with_data_access=False)
        r = bare.post(ADMIN, self.body(), format="json")
        self.assertEqual((r.status_code, self.codes(r, "scopes")), (400, ["scope_not_held"]))
        regional = self.make_user("chief", "regional_chief", unit="BARI")  # holds personnel.view for BARI only
        self.assertEqual(self.client_for(regional).post(ADMIN, self.body(), format="json").status_code, 403)

    def test_cannot_widen_beyond_own_scope_by_choosing_a_bigger_unit(self):
        user = self.make_user("adm", "hq_admin")
        RoleAssignment.objects.create(user=user, role=Role.objects.get(code="regional_chief"), org_unit=self.unit("BARI"))
        c = self.client_for(User.objects.get(pk=user.pk))
        ok = c.post(ADMIN, self.body(), format="json")
        wide = c.post(ADMIN, self.body(org_unit=str(self.unit("HQ").pk)), format="json")
        self.assertEqual((ok.status_code, wide.status_code), (201, 400))
        self.assertEqual(self.codes(wide, "scopes"), ["scope_not_held"])

    def test_validation(self):
        a = self.admin()
        self.assertEqual(self.codes(a.post(ADMIN, self.body(scopes=[]), format="json"), "scopes"), ["invalid_scope"])
        self.assertEqual(self.codes(a.post(ADMIN, self.body(scopes=["audit"]), format="json"), "scopes"), ["invalid_scope"])
        past = (timezone.now() - timedelta(days=1)).isoformat()
        far = (timezone.now() + timedelta(days=4000)).isoformat()
        self.assertEqual(self.codes(a.post(ADMIN, self.body(expires_at=past), format="json"), "expires_at"), ["expiry_invalid"])
        self.assertEqual(self.codes(a.post(ADMIN, self.body(expires_at=far), format="json"), "expires_at"), ["expiry_too_far"])
        self.assertEqual(self.codes(a.post(ADMIN, self.body(name="x"), format="json"), "name"), ["name_too_short"])

    def test_only_permitted_users_can_list(self):
        self.make_client()
        for user in (self.make_user("chief", "regional_chief", unit="BARI"), self.make_user("aud", "auditor")):
            self.assertEqual(self.client_for(user).get(ADMIN).status_code, 403, user.username)

    def test_update_needs_the_current_version(self):
        a = self.admin()
        data = self.make_client(admin=a)
        url = f"{ADMIN}{data['id']}/"
        self.assertEqual(self.codes(a.patch(url, {"name": "Renamed"}, format="json"), "version"), ["version_required"])
        ok = a.patch(url, {"name": "Renamed", "version": data["version"]}, format="json")
        self.assertEqual((ok.status_code, ok.json()["version"]), (200, data["version"] + 1))
        stale = a.patch(url, {"name": "Again", "version": data["version"]}, format="json")
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "version_conflict"))

    def test_rotation_replaces_the_key_immediately(self):
        a = self.admin()
        data = self.make_client(admin=a)
        old = data["key"]
        self.assertEqual(self.machine(old).get(EXT + "me/").status_code, 200)
        r = a.post(f"{ADMIN}{data['id']}/rotate/", {"version": data["version"]}, format="json")
        self.assertEqual(r.status_code, 200)
        new = r.json()["key"]
        self.assertNotEqual(old, new)
        self.assertEqual(self.machine(old).get(EXT + "me/").status_code, 401)
        self.assertEqual(self.machine(new).get(EXT + "me/").status_code, 200)

    def test_revocation_works_even_if_the_feature_is_switched_off(self):
        a = self.admin()
        data = self.make_client(admin=a)
        with override_settings(INTEGRATIONS_ENABLED=False):
            r = a.post(f"{ADMIN}{data['id']}/revoke/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "key_revoked"))
        self.assertEqual(self.machine(data["key"]).get(EXT + "me/").json()["code"], "key_revoked")
        self.assertEqual(a.patch(f"{ADMIN}{data['id']}/", {"name": "Nope", "version": 9}, format="json").status_code, 400)

    def test_lifecycle_is_audited_without_secrets(self):
        a = self.admin()
        data = self.make_client(admin=a)
        a.post(f"{ADMIN}{data['id']}/rotate/", {"version": data["version"]}, format="json")
        a.post(f"{ADMIN}{data['id']}/revoke/", {}, format="json")
        actions = set(AuditEvent.objects.filter(action__startswith="integration.").values_list("action", flat=True))
        self.assertEqual(actions, {"integration.create", "integration.rotate", "integration.revoke"})
        blob = json.dumps(list(AuditEvent.objects.values("metadata", "action")))
        self.assertNotIn(data["key"].split("_", 2)[2], blob)
        self.assertNotIn(IntegrationClient.objects.get(pk=data["id"]).key_hash, blob)


@override_settings(INTEGRATIONS_ENABLED=True)
class ExternalApiTests(IntegrationBase):
    def test_no_credentials_means_401_on_every_external_route(self):
        for url in (EXT + "me/", EXT + "analytics/personnel/"):
            r = APIClient().get(url)
            self.assertEqual(r.status_code, 401, url)
            self.assertIn("Bearer", r["WWW-Authenticate"])
        self.assertEqual(APIClient().post(EXT + "me/", {}, format="json").status_code, 401)

    def test_a_signed_in_session_is_not_an_integration_credential(self):
        a = self.admin()
        self.assertEqual(a.get(EXT + "me/").status_code, 401)

    def test_wrong_secret_unknown_prefix_and_garbage_are_indistinguishable(self):
        data = self.make_client()
        prefix = data["key"].split("_")[1]
        results = []
        for bad in (f"ahq_{prefix}_" + "x" * 43, "ahq_00000000_" + "x" * 43, "not-a-key", "ahq_zz_1"):
            r = self.machine(bad).get(EXT + "me/")
            results.append((r.status_code, r.json()["code"]))
        self.assertEqual(set(results), {(401, "invalid_key")})

    def test_data_is_limited_to_the_clients_unit(self):
        data = self.make_client()  # BARI only, personnel
        r = self.machine(data["key"]).get(EXT + "analytics/personnel/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["data"]["by_status"]["total"], 7)
        with override_settings(INTEGRATION_ALLOW_UNIT_FILTER=True):
            other = self.machine(data["key"]).get(f"{EXT}analytics/personnel/?unit={self.karkaar.pk}")
            inside = self.machine(data["key"]).get(f"{EXT}analytics/personnel/?unit={self.bari.pk}")
        self.assertEqual((other.status_code, inside.status_code), (404, 200))

    def test_unit_filter_is_refused_for_keys_by_default(self):
        data = self.make_client()
        r = self.machine(data["key"]).get(f"{EXT}analytics/personnel/?unit={self.bari.pk}")
        self.assertEqual((r.status_code, self.codes(r, "unit")), (400, ["unit_filter_not_allowed"]))

    def test_sections_outside_the_key_scope_are_refused(self):
        data = self.make_client()
        c = self.machine(data["key"])
        for section in ("reports", "logistics", "training"):
            r = c.get(f"{EXT}analytics/{section}/")
            self.assertEqual((r.status_code, r.json()["code"]), (403, "scope_denied"), section)
        self.assertEqual(c.get(EXT + "analytics/audit/").status_code, 404)

    def test_clients_get_approved_reports_only_and_no_pipeline(self):
        a = self.admin()
        data = self.make_client(admin=a, scopes=["reports"])
        from apps.workflows.models import ReportType, Submission
        rt = ReportType.objects.get(code="monthly_admin_report")
        now = timezone.now()
        for status in ("approved", "draft"):
            Submission.objects.create(report_type=rt, org_unit=self.bari, title="T", period_start="2026-01-01", period_end="2026-01-31",
                                      submitter_username="x", status=status, submitted_at=now, decided_at=now if status == "approved" else None)
        with override_settings(INTEGRATION_MIN_CELL=0):
            d = self.machine(data["key"]).get(EXT + "analytics/reports/").json()["data"]
        self.assertEqual(d["approved_by_type"]["total"], 1)
        self.assertNotIn("pipeline", d)

    def test_small_cells_are_withheld(self):
        a = self.admin()
        karkaar = self.make_client(admin=a, org_unit=str(self.unit("KARKAAR").pk))  # only 2 people
        d = self.machine(karkaar["key"]).get(EXT + "analytics/personnel/").json()["data"]
        self.assertIsNone(d["by_status"]["total"])
        self.assertTrue(d["by_status"]["suppressed"])
        self.assertIsNone(d["by_status"]["rows"][0]["count"])
        with override_settings(INTEGRATION_MIN_CELL=1):
            d = self.machine(karkaar["key"]).get(EXT + "analytics/personnel/").json()["data"]
        self.assertEqual(d["by_status"]["total"], 2)

    def test_expired_revoked_and_disabled_keys(self):
        a = self.admin()
        data = self.make_client(admin=a)
        IntegrationClient.objects.filter(pk=data["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.machine(data["key"]).get(EXT + "me/")
        self.assertEqual((r.status_code, r.json()["code"]), (401, "key_expired"))
        IntegrationClient.objects.filter(pk=data["id"]).update(expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.machine(data["key"]).get(EXT + "me/").status_code, 200)
        a.post(f"{ADMIN}{data['id']}/revoke/", {}, format="json")
        self.assertEqual(self.machine(data["key"]).get(EXT + "me/").json()["code"], "key_revoked")

    def test_every_call_is_logged_with_its_outcome(self):
        a = self.admin()
        data = self.make_client(admin=a)
        c = self.machine(data["key"])
        c.get(EXT + "analytics/personnel/")
        c.get(EXT + "analytics/reports/")  # out of scope
        outcomes = list(IntegrationCall.objects.filter(client_id=data["id"]).order_by("at").values_list("endpoint", "status_code", "outcome"))
        self.assertEqual(outcomes, [("analytics/personnel", 200, "success"), ("analytics/reports", 403, "denied")])
        self.assertIsNotNone(IntegrationClient.objects.get(pk=data["id"]).last_used_at)
        logged = a.get(f"{ADMIN}{data['id']}/calls/").json()
        self.assertEqual(logged["count"], 2)

    def test_the_call_log_is_append_only(self):
        from apps.core.appendonly import AppendOnlyError
        data = self.make_client()
        self.machine(data["key"]).get(EXT + "me/")
        call = IntegrationCall.objects.get()
        with self.assertRaises(AppendOnlyError):
            call.outcome = "error"
            call.save()
        with self.assertRaises(AppendOnlyError):
            IntegrationCall.objects.all().delete()

    def test_per_client_rate_limit(self):
        data = self.make_client()
        c = self.machine(data["key"])
        with mock.patch.object(IntegrationRateThrottle, "THROTTLE_RATES", {"integration": "2/min"}):
            codes = [c.get(EXT + "me/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        self.assertEqual(IntegrationCall.objects.filter(outcome="throttled").count(), 1)

    def test_repeated_bad_keys_lock_the_source_out(self):
        data = self.make_client()
        with override_settings(INTEGRATION_FAIL_LIMIT=3):
            for _ in range(3):
                self.assertEqual(self.machine("ahq_00000000_" + "x" * 43).get(EXT + "me/").status_code, 401)
            self.assertEqual(self.machine(data["key"]).get(EXT + "me/").status_code, 429)
        self.assertTrue(AuditEvent.objects.filter(action="integration.auth_failed").exists())

    def test_responses_are_not_cacheable(self):
        data = self.make_client()
        self.assertEqual(self.machine(data["key"]).get(EXT + "me/")["Cache-Control"], "no-store")


@override_settings(INTEGRATIONS_ENABLED=True)
class ReviewCommandTests(IntegrationBase):
    def run_report(self):
        import io
        from django.core.management import call_command
        out = io.StringIO()
        try:
            call_command("integration_report", stdout=out)
            code = 0
        except SystemExit as e:
            code = e.code
        return code, json.loads(out.getvalue())

    def test_healthy_client_needs_no_attention(self):
        self.make_client()
        code, report = self.run_report()
        self.assertEqual((code, report["needs_attention"], report["creator_access_lost"]), (0, False, []))

    def test_key_whose_creator_was_disabled_is_flagged(self):
        data = self.make_client()
        User.objects.filter(username="adm").update(is_active=False)
        code, report = self.run_report()
        self.assertEqual((code, report["creator_access_lost"]), (2, [data["key_prefix"]]))

    def test_key_whose_creator_lost_the_access_is_flagged(self):
        data = self.make_client()
        RoleAssignment.objects.filter(user__username="adm", role__code="hq_reporting").delete()
        code, report = self.run_report()
        self.assertEqual((code, report["creator_access_lost"]), (2, [data["key_prefix"]]))
