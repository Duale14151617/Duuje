import csv
import io
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import RoleAssignment
from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.organization.models import OrganizationalUnit as OU
from apps.workflows.models import Notification, ReportType, Submission

URL = "/api/v1/reports/submissions/"
SUMMARY = "/api/v1/reports/summary/"
FIG = {"personnel_strength": 100, "personnel_on_leave": 5, "personnel_in_training": 10}


class WorkflowBase(BaseApiTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, parent in (("BARI-ARMY-A", "BARI-ARMY"), ("BARI-ARMY-B", "BARI-ARMY"), ("NUGAAL-ARMY-A", "NUGAAL-ARMY")):
            OU.objects.create(code=code, name_en=code, level="unit", parent=OU.objects.get(code=parent))

    def who(self, name, role, unit, branch=None):
        cache = self.__dict__.setdefault("_clients", {})
        if name not in cache:
            cache[name] = self.client_for(self.make_user(name, role, unit=unit, branch=branch))
        return cache[name]

    def officer(self, name="officer", unit="BARI-ARMY-A"):
        return self.who(name, "reporting_officer", unit)

    def reviewer(self, name="rev-bari", region="BARI"):
        return self.who(name, "regional_chief", region)

    def hqr(self):
        return self.who("hqr", "hq_reporting", "HQ")

    def rtype(self, code="monthly_admin_report"):
        return ReportType.objects.get(code=code)

    def new(self, client, unit="BARI-ARMY-A", code="monthly_admin_report", **kw):
        body = {"report_type": str(self.rtype(code).pk), "org_unit": str(self.unit(unit).pk), "title": "May report",
                "period_start": "2026-05-01", "period_end": "2026-05-31", "figures": dict(FIG)}
        if code != "monthly_admin_report":
            body.pop("figures"), body.update(body="Please approve")
        body.update(kw)
        return client.post(URL, body, format="json")

    def act(self, client, sub, name, **extra):
        return client.post(f"{URL}{sub['id']}/{name}/", {"version": sub["version"], **extra}, format="json")

    def approved(self, officer, reviewer, unit="BARI-ARMY-A", figures=None, **kw):
        s = self.new(officer, unit=unit, figures=figures or dict(FIG), **kw).data
        for step in ("submit",):
            s = self.act(officer, s, step).data
        s = self.act(reviewer, s, "start-review").data
        s = self.act(reviewer, s, "approve")
        self.assertEqual(s.status_code, 200, s.data)
        return s.data


class LifecycleTests(WorkflowBase):
    def test_happy_path_records_history_notifications_and_audit(self):
        o, r = self.officer(), self.reviewer()
        s = self.new(o).data
        self.assertEqual((s["status"], s["submitter_username"], s["version"]), ("draft", "officer", 1))
        s = self.act(o, s, "submit").data
        self.assertEqual((s["status"], s["current_revision"]), ("submitted", 1))
        self.assertTrue(Notification.objects.filter(recipient__username="rev-bari", kind="submitted").exists())
        s = self.act(r, s, "start-review").data
        self.assertEqual(s["status"], "under_review")
        s = self.act(r, s, "approve").data
        self.assertEqual((s["status"], s["approved_revision_no"]), ("approved", 1))
        self.assertEqual([a["action"] for a in s["actions"]], ["create", "submit", "start_review", "approve"])
        self.assertEqual(s["actions"][-1]["actor_username"], "rev-bari")
        self.assertTrue(Notification.objects.filter(recipient__username="officer", kind="approved").exists())
        for action in ("report.create", "report.submit", "report.start_review", "report.approve"):
            self.assertTrue(AuditEvent.objects.filter(action=action, outcome="success").exists(), action)

    def test_invalid_transitions_are_rejected(self):
        o, r = self.officer(), self.reviewer()
        s = self.new(o).data
        for client, name in ((r, "approve"), (r, "start-review"), (o, "amend"), (r, "reject")):
            resp = self.act(client, s, name, comment="x")
            self.assertEqual((resp.status_code, resp.data["code"]), (409, "invalid_transition"), name)
        s = self.act(o, s, "submit").data
        self.assertEqual(self.act(o, s, "submit").data["code"], "invalid_transition")
        edit = o.patch(f"{URL}{s['id']}/", {"title": "Changed", "version": s["version"]}, format="json")
        self.assertEqual((edit.status_code, edit.data["code"]), (409, "not_editable"))
        s = self.act(r, s, "start-review").data
        self.assertEqual(self.codes(self.act(r, s, "reject"), "comment"), ["comment_required"])
        self.assertEqual(self.codes(self.act(r, s, "return"), "comment"), ["comment_required"])
        s = self.act(r, s, "reject", comment="Not acceptable").data
        self.assertEqual(s["status"], "rejected")
        self.assertEqual(self.act(o, s, "submit").status_code, 409)  # rejected is terminal
        self.assertEqual(self.act(o, s, "amend", comment="x").status_code, 409)

    def test_return_edit_resubmit_creates_new_revision(self):
        o, r = self.officer(), self.reviewer()
        s = self.new(o).data
        s = self.act(o, s, "submit").data
        s = self.act(r, s, "start-review").data
        s = self.act(r, s, "return", comment="Fix the numbers").data
        self.assertEqual(s["status"], "returned")
        fixed = dict(FIG, personnel_strength=111)
        s = o.patch(f"{URL}{s['id']}/", {"figures": fixed, "version": s["version"]}, format="json").data
        s = self.act(o, s, "submit").data
        self.assertEqual(s["current_revision"], 2)
        self.assertEqual(s["actions"][-1]["action"], "resubmit")
        self.assertTrue(Notification.objects.filter(recipient__username="rev-bari", kind="resubmitted").exists())
        s = self.act(r, s, "start-review").data
        s = self.act(r, s, "approve").data
        self.assertEqual(s["approved_revision_no"], 2)
        self.assertEqual(s["revisions"][1]["figures"]["personnel_strength"], 111)
        self.assertEqual(s["revisions"][0]["figures"]["personnel_strength"], 100)  # old snapshot preserved

    def test_amendment_keeps_prior_approved_totals_until_reapproved(self):
        o, r = self.officer(), self.reviewer()
        s = self.approved(o, r)
        s = self.act(o, s, "amend", comment="Correction needed").data
        self.assertEqual(s["status"], "amended")
        self.assertEqual(self.hqr().get(SUMMARY).data["consolidated"]["totals"]["personnel_strength"], 100)
        s = o.patch(f"{URL}{s['id']}/", {"figures": dict(FIG, personnel_strength=90), "version": s["version"]}, format="json").data
        s = self.act(o, s, "submit").data
        self.assertEqual(self.hqr().get(SUMMARY).data["consolidated"]["totals"]["personnel_strength"], 100)
        s = self.act(r, s, "start-review").data
        self.act(r, s, "approve")
        self.assertEqual(self.hqr().get(SUMMARY).data["consolidated"]["totals"]["personnel_strength"], 90)

    def test_stale_versions_conflict_and_change_nothing(self):
        o, r1 = self.officer(), self.reviewer()
        r2 = self.who("rev2", "regional_chief", "BARI")
        s = self.act(o, self.new(o).data, "submit").data
        self.assertEqual(self.act(r1, s, "start-review").status_code, 200)
        late = self.act(r2, s, "start-review")  # same stale version
        self.assertEqual((late.status_code, late.data["code"]), (409, "version_conflict"))
        self.assertEqual(Submission.objects.get(pk=s["id"]).status, "under_review")


class SeparationAndForgeryTests(WorkflowBase):
    def test_submitter_cannot_review_their_own_report(self):
        ba = self.who("ba", "branch_admin", "BARI", "ARMY")  # may both submit and review in scope
        s = self.act(ba, self.new(ba).data, "submit").data
        resp = self.act(ba, s, "start-review")
        self.assertEqual((resp.status_code, resp.data["code"]), (403, "self_review_not_allowed"))
        self.assertTrue(AuditEvent.objects.filter(action="report.start_review", outcome="denied",
                                                  metadata__reason="self_review").exists())
        self.assertEqual(Submission.objects.get(pk=s["id"]).status, "submitted")
        self.assertFalse(s["capabilities"]["start_review"])
        self.assertEqual(self.act(self.reviewer(), s, "start-review").status_code, 200)  # someone else can

    def test_policy_can_allow_self_review_and_it_is_flagged_in_audit(self):
        ReportType.objects.filter(code="training_request").update(separation_of_duties=False)
        ba = self.who("ba", "branch_admin", "BARI", "ARMY")
        s = self.act(ba, self.new(ba, code="training_request").data, "submit").data
        self.assertEqual(self.act(ba, s, "start-review").status_code, 200)
        ev = AuditEvent.objects.get(action="report.start_review", outcome="success")
        self.assertTrue(ev.metadata["self_review"])

    def test_clients_cannot_forge_actor_status_or_identity(self):
        o, r = self.officer(), self.reviewer()
        s = self.new(o, status="approved", submitter_username="general", version=99, current_revision=7,
                     reviewer=str(self.unit("HQ").pk)).data
        self.assertEqual((s["status"], s["submitter_username"], s["version"], s["current_revision"]),
                         ("draft", "officer", 1, 0))
        p = o.patch(f"{URL}{s['id']}/", {"status": "approved", "version": 1, "title": "T2"}, format="json").data
        self.assertEqual((p["status"], p["title"]), ("draft", "T2"))
        sub = self.act(o, p, "submit", status="approved", reviewer="x").data
        self.assertEqual(sub["status"], "submitted")
        moved = o.patch(f"{URL}{s['id']}/", {"org_unit": str(self.unit("BARI-ARMY-B").pk), "version": 3}, format="json")
        self.assertEqual(moved.status_code, 409)  # not editable now; and org_unit is immutable anyway
        d = self.new(o).data
        bad = o.patch(f"{URL}{d['id']}/", {"org_unit": str(self.unit("BARI-ARMY-B").pk), "version": 1}, format="json")
        self.assertIn("immutable_field", self.codes(bad, "org_unit"))
        other = o.patch(f"{URL}{d['id']}/", {"report_type": str(self.rtype("training_request").pk), "version": 1}, format="json")
        self.assertIn("immutable_field", self.codes(other, "report_type"))

    def test_only_the_submitter_may_edit_submit_or_amend(self):
        o, o2 = self.officer(), self.officer("officer2")
        s = self.new(o).data
        self.assertEqual(o2.get(f"{URL}{s['id']}/").status_code, 200)  # same scope, can read
        r = o2.patch(f"{URL}{s['id']}/", {"title": "Hijack", "version": 1}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (403, "not_owner"))
        self.assertEqual(self.act(o2, s, "submit").data["code"], "not_owner")

    def test_reviewers_cannot_use_submit_only_actions_and_vice_versa(self):
        o = self.officer()
        s = self.act(o, self.new(o).data, "submit").data
        self.assertEqual(self.act(o, s, "start-review").status_code, 403)  # officer lacks reports.review
        self.assertEqual(self.reviewer().post(URL, {}, format="json").status_code, 403)  # chief lacks reports.submit


class ScopeTests(WorkflowBase):
    def test_cross_region_access_is_blocked_everywhere(self):
        n_off = self.who("n-off", "reporting_officer", "NUGAAL-ARMY")
        n_rev = self.who("n-rev", "regional_chief", "NUGAAL")
        s = self.act(n_off, self.new(n_off, unit="NUGAAL-ARMY-A").data, "submit").data
        b_rev, b_off = self.reviewer(), self.officer()
        self.assertEqual(b_rev.get(f"{URL}{s['id']}/").status_code, 404)
        self.assertEqual(self.act(b_rev, s, "start-review").status_code, 404)
        self.assertEqual(b_rev.get(URL).data["count"], 0)
        self.assertEqual(b_rev.get(f"{URL}?org_unit={self.unit('NUGAAL').pk}").data["count"], 0)
        out = self.new(b_off, unit="NUGAAL-ARMY-A")
        self.assertEqual(out.status_code, 400)
        self.assertIn("out_of_scope", self.codes(out, "org_unit"))
        self.assertEqual(n_rev.get(URL).data["count"], 1)

    def test_listing_filters_and_malformed_ids(self):
        o, r = self.officer(), self.reviewer()
        a = self.new(o).data
        b = self.act(o, self.new(o, title="Second").data, "submit").data
        self.assertEqual(o.get(URL + "?mine=1").data["count"], 2)
        self.assertEqual(r.get(URL + "?awaiting_review=1").data["count"], 1)
        self.assertEqual(o.get(URL + "?awaiting_review=1").data["count"], 0)  # officers review nothing
        self.assertEqual(r.get(URL + "?status=draft").data["count"], 1)
        self.assertEqual(r.get(URL + "?from=2026-07-01").data["count"], 0)
        self.assertEqual(r.get(URL + "?report_type=abc").status_code, 400)
        self.assertEqual(r.get(URL + "?from=notadate").status_code, 400)
        self.assertEqual({a["id"], b["id"]}, {x["id"] for x in r.get(URL).data["results"]})

    def test_users_without_report_permissions_get_nothing(self):
        adm = self.who("adm", "hq_admin", "HQ")
        self.assertEqual(adm.get(URL).status_code, 403)
        self.assertEqual(adm.get(SUMMARY).status_code, 403)

    def test_unauthenticated_denied(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(URL).data["code"], "not_authenticated")


class ValidationTests(WorkflowBase):
    def test_content_validation(self):
        o = self.officer()
        cases = [({"figures": {"nope": 1}}, "figures", "unknown_figure"),
                 ({"figures": {"personnel_strength": -1}}, "figures", "invalid_figure"),
                 ({"figures": {"personnel_strength": "5"}}, "figures", "invalid_figure"),
                 ({"figures": {"personnel_strength": True}}, "figures", "invalid_figure"),
                 ({"period_end": "2026-04-01"}, "period_end", "period_invalid"),
                 ({"org_unit": str(self.unit("BARI").pk)}, "org_unit", "unit_level_invalid")]
        for patch, field, code in cases:
            self.assertIn(code, self.codes(self.new(o, **patch), field), patch)
        self.assertEqual(self.new(o, body="x" * 5001).status_code, 400)

    def test_incomplete_submissions_cannot_be_submitted(self):
        o = self.officer()
        s = self.new(o, figures={"personnel_strength": 3}).data  # drafts may be partial
        self.assertEqual(s["status"], "draft")
        r = self.act(o, s, "submit")
        self.assertEqual(self.codes(r, "figures"), ["incomplete_submission"])
        self.assertEqual(Submission.objects.get(pk=s["id"]).status, "draft")
        req = self.new(o, code="training_request", body="").data
        self.assertEqual(self.codes(self.act(o, req, "submit"), "body"), ["incomplete_submission"])


class SummaryTests(WorkflowBase):
    def build(self):
        bo = self.officer("bari-off", "BARI-ARMY")
        br = self.reviewer()
        no = self.who("n-off", "reporting_officer", "NUGAAL-ARMY")
        nr = self.who("n-rev", "regional_chief", "NUGAAL")
        self.approved(bo, br, "BARI-ARMY-A", {"personnel_strength": 100, "personnel_on_leave": 5, "personnel_in_training": 10})
        self.approved(bo, br, "BARI-ARMY-B", {"personnel_strength": 50, "personnel_on_leave": 2, "personnel_in_training": 3})
        self.approved(no, nr, "NUGAAL-ARMY-A", {"personnel_strength": 30, "personnel_on_leave": 1, "personnel_in_training": 0})
        self.new(bo, unit="BARI-ARMY-A", figures={"personnel_strength": 9999, "personnel_on_leave": 0, "personnel_in_training": 0})  # draft
        s = self.act(bo, self.new(bo, unit="BARI-ARMY-B", figures={"personnel_strength": 8888, "personnel_on_leave": 0, "personnel_in_training": 0}).data, "submit").data  # submitted only
        self.assertEqual(s["status"], "submitted")

    def test_totals_by_region_and_consolidated_exclude_unapproved(self):
        self.build()
        d = self.hqr().get(SUMMARY).data
        self.assertEqual(d["consolidated"]["submissions"], 3)
        self.assertEqual(d["consolidated"]["totals"], {"personnel_strength": 180, "personnel_on_leave": 8, "personnel_in_training": 13})
        by = {x["region"]["code"]: x for x in d["regions"]}
        self.assertEqual(by["BARI"]["totals"]["personnel_strength"], 150)
        self.assertEqual(by["BARI"]["submissions"], 2)
        self.assertEqual(by["NUGAAL"]["totals"]["personnel_strength"], 30)

    def test_summary_respects_scope_and_filters(self):
        self.build()
        bari = self.reviewer().get(SUMMARY).data
        self.assertEqual([x["region"]["code"] for x in bari["regions"]], ["BARI"])
        self.assertEqual(bari["consolidated"]["totals"]["personnel_strength"], 150)
        hq = self.hqr()
        self.assertEqual(hq.get(SUMMARY + "?from=2026-06-01").data["consolidated"]["submissions"], 0)
        self.assertEqual(hq.get(SUMMARY + "?from=2026-05-15&to=2026-05-20").data["consolidated"]["submissions"], 3)
        self.assertEqual(hq.get(SUMMARY + f"?report_type={self.rtype('training_request').pk}").data["consolidated"]["submissions"], 0)
        self.assertEqual(hq.get(SUMMARY + f"?org_unit={self.unit('NUGAAL').pk}").data["consolidated"]["submissions"], 1)
        self.assertEqual(hq.get(SUMMARY + "?to=bad").status_code, 400)
        self.assertEqual(self.officer().get(SUMMARY).status_code, 403)  # no reports.summary

    def test_export_off_by_default_then_scoped_audited_csv(self):
        self.build()
        self.assertEqual(self.hqr().get(SUMMARY + "export/").data["code"], "export_disabled")
        with override_settings(REPORT_EXPORT_ENABLED=True):
            r = self.hqr().get(SUMMARY + "export/", HTTP_ACCEPT="text/csv")
            self.assertEqual(r.status_code, 200)
            rows = list(csv.reader(io.StringIO(r.content.decode())))
            self.assertEqual(rows[0][:3], ["region_code", "region_name", "submissions"])
            self.assertEqual(rows[-1][0], "TOTAL")
            self.assertTrue(AuditEvent.objects.filter(action="report.summary_export", outcome="success").exists())
            ba = self.who("ba", "branch_admin", "BARI", "ARMY")  # may read summaries but not export
            self.assertEqual(ba.get(SUMMARY + "export/").status_code, 403)
            self.assertEqual(ba.get(SUMMARY).status_code, 200)


class NotificationTests(WorkflowBase):
    def test_notifications_are_private_and_marked_read(self):
        o, r = self.officer(), self.reviewer()
        s = self.act(o, self.new(o).data, "submit").data
        n = r.get("/api/v1/notifications/")
        self.assertEqual(n.data["count"], 1)
        self.assertEqual(n.data["results"][0]["submission"]["title"], "May report")
        self.assertEqual(r.get("/api/v1/notifications/unread-count/").data["count"], 1)
        self.assertEqual(o.get("/api/v1/notifications/").data["count"], 0)  # the submitter was not notified of their own submit
        s = self.act(r, s, "start-review").data
        mine = Notification.objects.get(recipient__username="officer")
        self.assertEqual(r.post(f"/api/v1/notifications/{mine.pk}/read/").status_code, 404)  # someone else's
        self.assertEqual(o.post(f"/api/v1/notifications/{mine.pk}/read/").status_code, 204)
        self.assertEqual(o.get("/api/v1/notifications/unread-count/").data["count"], 0)
        self.assertEqual(r.post("/api/v1/notifications/read-all/").status_code, 204)
        self.assertEqual(r.get("/api/v1/notifications/?unread=1").data["count"], 0)

    def test_notification_content_is_reauthorised_after_scope_is_lost(self):
        o, r = self.officer(), self.reviewer()
        s = self.act(o, self.new(o).data, "submit").data
        RoleAssignment.objects.filter(user__username="rev-bari").update(revoked_at=timezone.now())
        n = r.get("/api/v1/notifications/")
        self.assertEqual(n.status_code, 200)
        self.assertIsNone(n.data["results"][0]["submission"])  # no title/status leaks once scope is gone
        self.assertEqual(r.get(f"{URL}{s['id']}/").status_code, 403)

    def test_reviewers_are_found_by_scope_only(self):
        far = self.who("far", "regional_chief", "NUGAAL")
        o = self.officer()
        self.act(o, self.new(o).data, "submit")
        self.assertFalse(Notification.objects.filter(recipient__username="far").exists())
        self.assertEqual(far.get("/api/v1/notifications/").data["count"], 0)


class ConfigTests(WorkflowBase):
    def test_report_types_are_configurable_by_headquarters_only(self):
        adm, chief, o = self.who("adm", "hq_admin", "HQ"), self.reviewer(), self.officer()
        body = {"code": "Weekly_Note", "kind": "report", "name_en": "Weekly note", "figure_keys": ["open_requests"]}
        r = adm.post("/api/v1/reports/types/", body, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (201, "weekly_note"), r.data)
        self.assertEqual(chief.post("/api/v1/reports/types/", {**body, "code": "x2"}, format="json").status_code, 403)
        bad = adm.post("/api/v1/reports/types/", {**body, "code": "x3", "figure_keys": ["secret"]}, format="json")
        self.assertIn("unknown_figure", self.codes(bad, "figure_keys"))
        self.assertTrue(any(t["code"] == "weekly_note" for t in o.get("/api/v1/reports/types/").data))
        self.assertEqual(adm.get("/api/v1/reports/types/").status_code, 200)

    def test_types_in_use_keep_their_shape_and_edits_are_versioned(self):
        adm = self.who("adm", "hq_admin", "HQ")
        self.new(self.officer())
        t = self.rtype()
        url = f"/api/v1/reports/types/{t.pk}/"
        r = adm.patch(url, {"figure_keys": ["open_requests"], "version": t.version}, format="json")
        self.assertIn("type_in_use", self.codes(r, "figure_keys"))
        ok = adm.patch(url, {"name_so": "Warbixin", "version": t.version}, format="json")
        self.assertEqual(ok.status_code, 200)
        stale = adm.patch(url, {"name_so": "Kale", "version": t.version}, format="json")
        self.assertEqual((stale.status_code, stale.data["code"]), (409, "version_conflict"))
