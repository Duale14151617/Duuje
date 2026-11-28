"""Audit log search by one box, person and dates, and the CSV export."""
import hashlib
from datetime import datetime, timezone as tz

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest

URL = "/api/v1/audit-events/"


class AuditSearchTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.adm = self.make_user("adm", "super_admin")
        self.c = self.client_for(self.adm)
        mk = lambda who, action, when, **kw: AuditEvent.objects.create(
            actor_username=who, action=action, occurred_at=when, outcome=kw.get("outcome", "success"), entity_id=kw.get("entity_id", ""))
        mk("amina", "auth.login", datetime(2026, 11, 10, 9, 0, tzinfo=tz.utc))
        mk("amina", "personnel.update", datetime(2026, 11, 10, 23, 30, tzinfo=tz.utc), entity_id="ABC123")
        mk("omar", "auth.login", datetime(2026, 11, 12, 8, 0, tzinfo=tz.utc), outcome="failure")
        mk("=cmd()", "user.create", datetime(2026, 11, 13, 8, 0, tzinfo=tz.utc))

    def names(self, **params):
        data = self.c.get(URL, params).json()
        return {(e["actor_username"], e["action"]) for e in data["results"]}

    def test_one_box_matches_person_action_and_record_id(self):
        self.assertEqual(self.names(q="amina", action_prefix="auth."), {("amina", "auth.login")})
        self.assertIn(("amina", "personnel.update"), self.names(q="abc12"))

    def test_person_contains_and_action_prefix(self):
        self.assertEqual({a for _, a in self.names(who="mar")}, {"auth.login"})
        self.assertGreaterEqual(len({a for _, a in self.names(action_prefix="auth.")}), 1)

    def test_a_bare_end_date_includes_the_whole_day(self):
        got = self.names(**{"from": "2026-11-10", "to": "2026-11-10", "who": "amina"})
        self.assertEqual(got, {("amina", "auth.login"), ("amina", "personnel.update")})  # the 23:30 event is on that day

    def test_export_is_csv_checksummed_audited_and_defuses_formulas(self):
        resp = self.c.get(URL + "export/", {"who": "cmd"})
        self.assertEqual(resp.status_code, 200)
        body = resp.content
        self.assertEqual(resp["X-Content-SHA256"], hashlib.sha256(body).hexdigest())
        text = body.decode("utf-8-sig")
        self.assertIn("'=cmd()", text)          # defused
        self.assertNotIn(",=cmd()", text)
        evt = AuditEvent.objects.filter(action="audit.export").latest("occurred_at")
        self.assertEqual(evt.metadata["sha256"], resp["X-Content-SHA256"])

    def test_export_needs_audit_permission(self):
        self.assertEqual(self.client_for(self.make_user("walker", "member", mfa=False)).get(URL + "export/").status_code, 403)
