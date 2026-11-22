"""Each serving person appears once on the roll and is recorded once per day. Synthetic data only."""
from .test_attendance import A, AttendanceBase


class OncePerPersonTests(AttendanceBase):
    def roll(self):
        return self.cmdr.get(A + "roll/", {"org_unit": str(self.unit_a.pk), "date": self.today.isoformat()}).json()["results"]

    def test_the_roll_lists_each_person_exactly_once(self):
        ids = [r["id"] for r in self.roll()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 3)

    def test_the_same_person_twice_in_one_request_is_refused_and_nothing_is_saved(self):
        r = self.record([self.entry(self.p1), self.entry(self.p1, "absent", reason="illness")])
        self.assertEqual(r.status_code, 400)
        self.assertIn("duplicate_entry", str(r.json()))
        self.assertTrue(all(x["attendance"] is None for x in self.roll()))

    def test_a_second_request_for_the_same_day_is_refused(self):
        self.assertEqual(self.record([self.entry(self.p1)]).status_code, 201)
        r = self.record([self.entry(self.p1)])
        self.assertEqual(r.status_code, 400)
        self.assertIn("already_recorded", str(r.json()))
