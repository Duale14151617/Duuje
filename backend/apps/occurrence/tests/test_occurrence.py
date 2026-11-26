import unittest

from django.conf import settings

if not settings.CUSTODY_ENABLED:  # custody is switched off for now; set CUSTODY_ENABLED=1 to run these tests
    raise unittest.SkipTest("custody is switched off (CUSTODY_ENABLED=0)")

"""Occurrence Book: numbering, append-only follow-ups, voiding, scope and the link to the detention register. Synthetic data only."""
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.appendonly import AppendOnlyError
from apps.detention.tests.test_detention import URL as DET, DetentionBase
from apps.occurrence.models import OccurrenceEntry, OccurrenceFollowUp

OB = "/api/v1/occurrence-book/"


class OccurrenceBase(DetentionBase):
    def enter(self, c=None, unit=None, **kw):
        body = {"org_unit": str((unit or self.unit_a).pk), "category": "complaint", "summary": "Stolen phone (test)", **kw}
        return (c or self.officer).post(OB, body, format="json")

    def make_entry(self, **kw):
        r = self.enter(**kw)
        self.assertEqual(r.status_code, 201, r.data)
        return r.data


class NumberingTests(OccurrenceBase):
    def test_numbers_run_per_station_and_year_and_are_not_shared(self):
        a1, a2 = self.make_entry(), self.make_entry()
        b1 = self.make_entry(c=self.nugaal, unit=self.unit_b)
        year = timezone.localdate().year
        self.assertEqual((a1["ob_number"], a2["ob_number"], b1["ob_number"]), (f"OB 0001/{year}", f"OB 0002/{year}", f"OB 0001/{year}"))

    def test_an_entry_dated_in_an_earlier_year_uses_that_years_book(self):
        old = self.make_entry(occurred_at=(timezone.now() - timedelta(days=400)).isoformat())
        self.assertTrue(old["ob_number"].endswith(str(timezone.localdate().year - 1)))
        self.assertTrue(self.make_entry()["ob_number"].startswith("OB 0001/"))  # this year's book starts at 0001

    def test_required_and_future_rules(self):
        self.assertEqual(self.enter(summary="").status_code, 400)
        self.assertEqual(self.enter(category="nonsense").status_code, 400)
        self.assertEqual(self.enter(occurred_at=(timezone.now() + timedelta(days=1)).isoformat()).status_code, 400)

    def test_audit_has_no_narrative(self):
        self.make_entry(summary="Secret narrative")
        ev = AuditEvent.objects.get(action="occurrence.create")
        self.assertNotIn("Secret narrative", str(ev.metadata))


class FollowUpAndVoidTests(OccurrenceBase):
    def act(self, e, action, body, c=None):
        cur = (c or self.officer).get(f"{OB}{e['id']}/").data
        return (c or self.officer).post(f"{OB}{e['id']}/{action}/", {"version": cur["version"], **body}, format="json")

    def test_follow_ups_append_and_the_entry_itself_never_changes(self):
        e = self.make_entry()
        self.assertEqual(self.act(e, "follow-up", {"kind": "correction", "text": "Phone was a tablet"}).status_code, 201)
        self.assertEqual(self.act(e, "follow-up", {"kind": "outcome", "text": "Recovered"}).status_code, 201)
        d = self.officer.get(f"{OB}{e['id']}/").data
        self.assertEqual([f["kind"] for f in d["follow_ups"]], ["correction", "outcome"])
        self.assertEqual(d["summary"], "Stolen phone (test)")
        with self.assertRaises(AppendOnlyError):
            OccurrenceFollowUp.objects.all().update(text="x")

    def test_follow_up_rules(self):
        e = self.make_entry()
        self.assertEqual(self.act(e, "follow-up", {"text": ""}).status_code, 400)
        self.assertEqual(self.act(e, "follow-up", {"kind": "voided", "text": "x"}).status_code, 400)  # system kind cannot be typed in
        self.assertEqual(self.officer.post(f"{OB}{e['id']}/follow-up/", {"version": 99, "text": "x"}, format="json").status_code, 409)

    def test_void_needs_a_reason_keeps_the_row_and_freezes_it(self):
        e = self.make_entry()
        self.assertEqual(self.act(e, "void", {}).status_code, 400)
        self.assertEqual(self.act(e, "void", {"reason": "Entered in the wrong station"}).data["status"], "void")
        self.assertEqual(OccurrenceEntry.objects.count(), 1)
        self.assertEqual(self.act(e, "follow-up", {"text": "late"}).status_code, 400)
        self.assertEqual(len(self.officer.get(OB).data["results"]), 0)
        self.assertEqual(len(self.officer.get(OB + "?include_void=1").data["results"]), 1)

    def test_a_number_is_not_reused_after_a_void(self):
        e = self.make_entry()
        self.act(e, "void", {"reason": "Mistake"})
        self.assertTrue(self.make_entry()["ob_number"].startswith("OB 0002/"))


class ScopeTests(OccurrenceBase):
    def test_scope_and_permissions(self):
        e = self.make_entry()
        self.assertEqual(self.nugaal.get(f"{OB}{e['id']}/").status_code, 404)
        self.assertEqual(len(self.nugaal.get(OB).data["results"]), 0)
        self.assertEqual(self.enter(c=self.nugaal).status_code, 400)  # cannot write in Bari's book
        self.assertEqual(self.member.get(OB).status_code, 403)
        self.assertEqual(self.cmdr.get(OB).status_code, 200)  # a station commander reads but does not write
        self.assertEqual(self.enter(c=self.cmdr).status_code, 403)

    def test_search_and_summary(self):
        self.make_entry(summary="Lost wallet near the market", category="theft_loss")
        self.make_entry(summary="Patrol", category="patrol")
        self.assertEqual(len(self.officer.get(OB + "?q=wallet").data["results"]), 1)
        self.assertEqual(len(self.officer.get(OB + "?category=patrol").data["results"]), 1)
        s = self.officer.get(OB + "summary/").data
        self.assertEqual((s["today"], s["arrests_today"]), (2, 0))


class DetentionLinkTests(OccurrenceBase):
    def test_booking_can_also_write_the_ob_entry(self):
        r = self.make(log_in_ob=True, detainee_name="Link Test", reason="Theft", arrest_place="Market")
        entries = self.officer.get(OB + "?category=arrest").data["results"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["detention"]["register_no"], r["register_no"])
        self.assertEqual(len(self.officer.get(OB).data["results"]), 1)

    def test_booking_without_the_box_writes_no_ob_entry(self):
        self.make()
        self.assertEqual(OccurrenceEntry.objects.count(), 0)

    def test_an_entry_can_link_to_a_record_of_the_same_station_only(self):
        rec = self.make()
        e = self.make_entry(category="custody", summary="Visit by family", detention_record=rec["id"])
        self.assertEqual(e["detention"]["id"], rec["id"])
        other = self.make(c=self.nugaal, unit=self.unit_b)
        self.assertEqual(self.enter(detention_record=other["id"]).status_code, 400)
