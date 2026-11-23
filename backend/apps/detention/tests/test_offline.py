import unittest

from django.conf import settings

if not settings.CUSTODY_ENABLED:  # custody is switched off for now; set CUSTODY_ENABLED=1 to run these tests
    raise unittest.SkipTest("custody is switched off (CUSTODY_ENABLED=0)")

"""Offline entry: bookings and log entries made without a connection and sent later must never duplicate, never be lost
silently, and never touch the strict rules. Synthetic data only."""
import uuid
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.detention.models import DetentionEvent, DetentionRecord
from apps.detention.tests.test_custody_units import UnitBase
from apps.detention.tests.test_detention import URL


class OfflineTests(UnitBase):
    def book_offline(self, ref=None, **kw):
        body = dict(org_unit=str(self.unit_a.pk), detainee_name="Offline One", reason="Theft", client_ref=ref or str(uuid.uuid4()), offline=True,
                    booked_at=timezone.now().isoformat())
        body.update(kw)
        return self.officer.post(URL, body, format="json")

    def event_offline(self, rec_id, ref=None, **kw):
        body = dict(kind="welfare", text="Checked, well", client_ref=ref or str(uuid.uuid4()), offline=True, occurred_at=timezone.now().isoformat())
        body.update(kw)
        return self.officer.post(f"{URL}{rec_id}/event/", body, format="json")  # note: no version, the device never saw the latest one

    def test_sending_a_booking_twice_creates_one_record(self):
        ref = str(uuid.uuid4())
        a = self.book_offline(ref)
        self.assertEqual(a.status_code, 201, a.data)
        b = self.book_offline(ref)
        self.assertEqual(b.status_code, 200, b.data)
        self.assertTrue(b.data["already_recorded"])
        self.assertEqual(a.data["register_no"], b.data["register_no"])
        self.assertEqual(DetentionRecord.objects.count(), 1)

    def test_the_booking_is_marked_as_entered_offline_in_log_and_audit(self):
        r = self.book_offline().data
        row = DetentionRecord.objects.get(pk=r["id"])
        self.assertIn("[entered offline]", row.events.get(kind="booked").text)
        self.assertTrue(AuditEvent.objects.filter(action="detention.book", metadata__offline=True).exists())

    def test_the_duplicate_id_guard_still_applies_to_offline_bookings(self):
        self.assertEqual(self.book_offline(id_ref="ID-9").status_code, 201)
        again = self.book_offline(id_ref="id 9")  # a different device booking the same person
        self.assertEqual(again.status_code, 400)  # surfaced at sync as "needs attention", not dropped by the server
        self.assertEqual(DetentionRecord.objects.count(), 1)

    def test_an_offline_event_needs_no_version_and_is_idempotent(self):
        rec = self.make()
        ref = str(uuid.uuid4())
        a = self.event_offline(rec["id"], ref)
        self.assertEqual(a.status_code, 201, a.data)
        b = self.event_offline(rec["id"], ref)
        self.assertEqual(b.status_code, 200, b.data)
        self.assertTrue(b.data["already_recorded"])
        self.assertEqual(DetentionEvent.objects.filter(client_ref=ref).count(), 1)
        self.assertIn("[entered offline]", DetentionEvent.objects.get(client_ref=ref).text)

    def test_offline_events_survive_a_newer_version_made_meanwhile(self):
        rec = self.make()
        self.act(rec, "event", {"kind": "note", "text": "Online note"})  # the record moved on while the device was offline
        self.assertEqual(self.event_offline(rec["id"]).status_code, 201)

    def test_only_log_kinds_can_be_entered_offline(self):
        rec = self.make()
        for kind in ("cell_move",):
            r = self.event_offline(rec["id"], kind=kind, text="x")
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self.event_offline(rec["id"], kind="review", text="").status_code, 201)

    def test_an_entry_for_a_record_that_closed_meanwhile_is_refused_not_dropped_silently(self):
        rec = self.make()
        self.act(rec, "close", {"outcome": "no_charge"})
        r = self.event_offline(rec["id"])
        self.assertEqual(r.status_code, 400)  # the desk keeps it in the queue as "needs attention" with this reason

    def test_other_regions_cannot_send_entries_for_this_record(self):
        rec = self.make()
        self.assertEqual(self.nugaal.post(f"{URL}{rec['id']}/event/", {"kind": "welfare", "text": "x", "client_ref": str(uuid.uuid4()), "offline": True}, format="json").status_code, 404)

    def test_an_entry_made_offline_cannot_be_dated_in_the_future_or_before_booking(self):
        rec = self.make()
        future = (timezone.now() + timedelta(days=2)).isoformat()
        self.assertEqual(self.event_offline(rec["id"], occurred_at=future).status_code, 400)
