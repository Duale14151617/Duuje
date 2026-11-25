"""Shift handover: snapshot, acknowledgement by the next officer, blocking, scope and audit. Synthetic data only."""
from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.detention.models import ShiftHandover
from apps.detention.tests.test_detention import DetentionBase

HO = "/api/v1/shift-handovers/"


class HandoverBase(DetentionBase):
    def setUp(self):
        super().setUp()
        self.officer2 = self.client_for(self.make_user("custody2", "custody_officer", unit="BARI-ARMY"))

    def write(self, c=None, unit=None, **kw):
        body = {"org_unit": str((unit or self.unit_a).pk), "pending": "Court papers for Garowe (test)", "watch": "Cell 2 is noisy (test)", **kw}
        return (c or self.officer).post(HO, body, format="json")

    def make_note(self, **kw):
        r = self.write(**kw)
        self.assertEqual(r.status_code, 201, r.data)
        return r.data


class WritingTests(HandoverBase):
    def test_note_lists_who_is_in_custody_from_the_register(self):
        self.make(detainee_name="Held Person One", cell="Cell 1")
        closed = self.make(detainee_name="Gone Person")
        self.assertEqual(self.act(closed, "close", {"outcome": "no_charge"}).status_code, 200)
        note = self.make_note()
        self.assertEqual([p["name"] for p in note["custody"]], ["Held Person One"])
        self.assertEqual(note["custody"][0]["cell"], "Cell 1")
        self.assertIsNone(note["acknowledged"])

    def test_pending_and_watch_are_required(self):
        self.assertEqual(self.write(pending="").status_code, 400)
        self.assertEqual(self.write(watch="  ").status_code, 400)
        self.assertEqual(self.write(pending="x" * 2001).status_code, 400)

    def test_shift_end_cannot_be_in_the_future(self):
        from datetime import timedelta
        from django.utils import timezone
        self.assertEqual(self.write(shift_ended_at=(timezone.now() + timedelta(days=1)).isoformat()).status_code, 400)

    def test_preview_shows_current_custody(self):
        self.make(detainee_name="Held Person Two")
        r = self.officer.get(HO + "preview/", {"unit": str(self.unit_a.pk)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["custody"]), 1)
        self.assertIsNone(r.data["blocked_by"])

    def test_notes_are_append_only(self):
        self.make_note()
        row = ShiftHandover.objects.get()
        row.pending = "changed"
        with self.assertRaises(AppendOnlyError):
            row.save()
        with self.assertRaises(AppendOnlyError):
            row.delete()


class AcknowledgementTests(HandoverBase):
    def ack(self, note, c=None, **kw):
        return (c or self.officer2).post(f"{HO}{note['id']}/acknowledge/", kw, format="json")

    def test_the_author_cannot_acknowledge_their_own_note(self):
        note = self.make_note()
        self.assertEqual(self.ack(note, c=self.officer).status_code, 400)
        self.assertIsNone(self.officer.get(f"{HO}{note['id']}/").data["acknowledged"])

    def test_the_next_officer_acknowledges_once(self):
        note = self.make_note()
        r = self.ack(note, comment="Read, will check Cell 2")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["acknowledged"]["by"], "custody2")
        self.assertEqual(self.ack(note).status_code, 400)  # final

    def test_a_new_note_is_refused_until_the_previous_one_is_acknowledged(self):
        first = self.make_note()
        blocked = self.write(c=self.officer2)
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("previous_unacknowledged", str(blocked.data))
        self.assertIsNotNone(self.officer2.get(HO + "preview/", {"unit": str(self.unit_a.pk)}).data["blocked_by"])
        self.assertEqual(self.ack(first).status_code, 200)
        self.assertEqual(self.write(c=self.officer2).status_code, 201)

    def test_the_author_may_add_another_note_before_anyone_acknowledges(self):
        self.make_note()
        self.assertEqual(self.write().status_code, 201)

    def test_waiting_counts_only_notes_this_person_may_acknowledge(self):
        self.make_note()
        self.assertEqual(self.officer.get(HO + "waiting/").data["for_me"], 0)
        mine = self.officer2.get(HO + "waiting/").data
        self.assertEqual((mine["waiting"], mine["for_me"]), (1, 1))


class ScopeAndAuditTests(HandoverBase):
    def test_another_regions_officer_cannot_write_read_or_acknowledge(self):
        note = self.make_note()
        self.assertEqual(self.write(c=self.nugaal).status_code, 400)
        self.assertEqual(self.nugaal.get(f"{HO}{note['id']}/").status_code, 404)
        self.assertEqual(self.nugaal.post(f"{HO}{note['id']}/acknowledge/", {}, format="json").status_code, 404)
        self.assertEqual(self.nugaal.get(HO).data["count"], 0)

    def test_read_only_roles_can_read_but_not_write_or_acknowledge(self):
        note = self.make_note()
        self.assertEqual(self.cmdr.get(HO).data["count"], 1)
        self.assertEqual(self.cmdr.post(HO, {"org_unit": str(self.unit_a.pk), "pending": "x", "watch": "y"}, format="json").status_code, 403)
        self.assertEqual(self.cmdr.post(f"{HO}{note['id']}/acknowledge/", {}, format="json").status_code, 403)
        self.assertEqual(self.member.get(HO).status_code, 403)

    def test_audit_holds_counts_and_ids_but_not_names_or_text(self):
        self.make(detainee_name="Very Secret Name")
        note = self.make_note(pending="Very secret pending text")
        self.officer2.post(f"{HO}{note['id']}/acknowledge/", {"comment": "Very secret comment"}, format="json")
        for action in ("handover.create", "handover.acknowledge"):
            ev = AuditEvent.objects.get(action=action)
            self.assertNotIn("secret", str(ev.metadata).lower())
        self.assertEqual(AuditEvent.objects.get(action="handover.create").metadata["in_custody"], 1)
