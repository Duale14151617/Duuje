"""Detention register: acceptance tests. Synthetic data only."""
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.detention.models import DetentionEvent, DetentionRecord
from apps.personnel.tests.test_personnel import PersonnelBase

URL = "/api/v1/detention/"


class DetentionBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.unit_a, self.unit_b = self.unit("BARI-ARMY-A"), self.unit("NUGAAL-ARMY-A")
        self.officer = self.client_for(self.make_user("custody", "custody_officer", unit="BARI-ARMY"))
        self.nugaal = self.client_for(self.make_user("custody_n", "custody_officer", unit="NUGAAL-ARMY"))
        self.cmdr = self.client_for(self.make_user("cmdr_d", "unit_commander", unit="BARI-ARMY-A"))
        self.member = self.client_for(self.make_user("plain_d", "member", unit="BARI-ARMY"))

    def book(self, c=None, unit=None, **kw):
        body = {"org_unit": str((unit or self.unit_a).pk), "detainee_name": "Test Detainee", "reason": "Test ground", **kw}
        return (c or self.officer).post(URL, body, format="json")

    def make(self, **kw):
        r = self.book(**kw)
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def act(self, rec, action, body, c=None):
        cur = (c or self.officer).get(f"{URL}{rec['id']}/").data
        return (c or self.officer).post(f"{URL}{rec['id']}/{action}/", {"version": cur["version"], **body}, format="json")


class RegisterTests(DetentionBase):
    def test_book_in_numbers_and_logs(self):
        a, b = self.make(), self.make(detainee_name="Second")
        self.assertEqual((a["register_no"], b["register_no"]), ("DET-000001", "DET-000002"))
        self.assertEqual(a["status"], "in_custody")
        detail = self.officer.get(f"{URL}{a['id']}/").data
        self.assertEqual([e["kind"] for e in detail["events"]], ["booked"])
        self.assertTrue(AuditEvent.objects.filter(action="detention.book").exists())

    def test_required_and_future_rules(self):
        self.assertEqual(self.book(detainee_name="").status_code, 400)
        self.assertEqual(self.book(reason="").status_code, 400)
        self.assertEqual(self.book(booked_at=(timezone.now() + timedelta(days=1)).isoformat()).status_code, 400)
        self.assertEqual(self.book(age_years="200").status_code, 400)

    def test_events_cell_move_and_close(self):
        r = self.make(cell="Cell 1")
        self.assertEqual(self.act(r, "event", {"kind": "welfare", "text": "Fed, well"}).status_code, 201)
        moved = self.act(r, "event", {"kind": "cell_move", "cell": "Cell 3"})
        self.assertEqual(moved.data["cell"], "Cell 3")
        self.assertEqual(self.act(r, "event", {"kind": "released"}).status_code, 400)  # system kinds cannot be typed in
        out = self.act(r, "close", {"outcome": "no_charge"})
        self.assertEqual((out.status_code, out.data["status"]), (200, "released"))
        self.assertEqual(self.act(r, "event", {"kind": "note", "text": "late"}).status_code, 400)  # closed
        self.assertEqual(self.act(r, "close", {"outcome": "no_charge"}).status_code, 400)

    def test_transfer_needs_destination(self):
        r = self.make()
        self.assertEqual(self.act(r, "close", {"outcome": "transfer_court"}).status_code, 400)
        out = self.act(r, "close", {"outcome": "transfer_court", "destination": "Garowe court"})
        self.assertEqual(out.data["status"], "transferred")

    def test_void_needs_reason_and_keeps_row(self):
        r = self.make()
        self.assertEqual(self.act(r, "void", {}).status_code, 400)
        self.assertEqual(self.act(r, "void", {"reason": "Entered twice"}).data["status"], "void")
        self.assertEqual(DetentionRecord.objects.count(), 1)
        self.assertEqual(len(self.officer.get(URL).data["results"]), 0)  # hidden unless asked
        self.assertEqual(len(self.officer.get(URL + "?include_void=1").data["results"]), 1)

    def test_stale_version_is_refused(self):
        r = self.make()
        self.assertEqual(self.officer.post(f"{URL}{r['id']}/event/", {"version": 99, "kind": "note", "text": "x"}, format="json").status_code, 409)

    def test_overdue_flag_and_summary(self):
        r = self.make(booked_at=(timezone.now() - timedelta(hours=60)).isoformat())
        self.make()
        listed = {x["id"]: x for x in self.officer.get(URL).data["results"]}
        self.assertTrue(listed[r["id"]]["overdue"])
        self.assertEqual(len(self.officer.get(URL + "?overdue=1").data["results"]), 1)
        s = self.officer.get(URL + "summary/").data
        self.assertEqual((s["in_custody"], s["overdue"]), (2, 1))

    def test_delete_is_impossible(self):
        r = self.make()
        with self.assertRaises(AppendOnlyError):
            DetentionRecord.objects.get(pk=r["id"]).delete()
        with self.assertRaises(AppendOnlyError):
            DetentionEvent.objects.first().save()


class AccessTests(DetentionBase):
    def test_scope_and_roles(self):
        r = self.make()
        self.assertEqual(self.nugaal.get(f"{URL}{r['id']}/").status_code, 404)  # other region
        self.assertEqual(len(self.nugaal.get(URL).data["results"]), 0)
        self.assertEqual(self.book(c=self.nugaal, unit=self.unit_a).status_code, 400)  # cannot book into another region's station
        self.assertEqual(self.cmdr.get(URL).status_code, 200)  # station commander reads
        self.assertEqual(self.book(c=self.cmdr).status_code, 201)  # and manages the register of their own station
        self.assertEqual(self.book(c=self.cmdr, unit=self.unit_b).status_code, 400)  # but not another station's
        self.assertEqual(self.member.get(URL).status_code, 403)

    def test_reads_are_audited_without_personal_data(self):
        r = self.make(detainee_name="Secret Name")
        self.officer.get(f"{URL}{r['id']}/")
        self.officer.get(URL)
        events = AuditEvent.objects.filter(action__startswith="detention.")
        self.assertTrue(events.filter(action="detention.read_record").exists())
        self.assertFalse(any("Secret Name" in str(e.metadata) for e in events))
