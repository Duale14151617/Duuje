"""Administrative task tracking for units. Synthetic data only."""
from datetime import date, timedelta

from apps.audit.models import AuditEvent
from apps.personnel.models import TaskEvent
from apps.personnel.tests.test_personnel import PersonnelBase

T = "/api/v1/operations/tasks/"


def iso(days):
    return (date.today() + timedelta(days=days)).isoformat()


class TaskBase(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.hq = self.client_for(self.make_user("hqtask", "hq_admin"))
        self.unit_a = self.unit("BARI-ARMY-A")
        self.p1 = self.person("BARI-ARMY-A", "Task Person", service_number="T-1")

    def body(self, **over):
        d = {"org_unit": str(self.unit_a.pk), "title": "Prepare roster", "description": "Monthly duty roster",
             "authority_ref": "Order 12/2026", "assigned_on": iso(0), "due_on": iso(7), "responsible": str(self.p1.pk)}
        d.update(over)
        return d

    def make(self, **over):
        return self.hq.post(T, self.body(**over), format="json")

    def act(self, row, name, **body):
        return self.hq.post(f"{T}{row['id']}/{name}/", {"version": row["version"], **body}, format="json")


class CreateTests(TaskBase):
    def test_hq_admin_records_a_task_with_its_authority_and_event(self):
        r = self.make()
        self.assertEqual(r.status_code, 201, r.content)
        row = r.json()
        self.assertEqual((row["status"], row["responsible"]["service_number"], row["overdue"]), ("open", "T-1", False))
        self.assertEqual(TaskEvent.objects.filter(task_id=row["id"], kind="created").count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="task.create").exists())

    def test_validation(self):
        self.assertEqual(self.make(title="").status_code, 400)
        self.assertEqual(self.make(authority_ref="").status_code, 400)
        self.assertEqual(self.make(due_on=iso(-3)).status_code, 400)
        self.assertEqual(self.make(org_unit="not-a-uuid").status_code, 400)

    def test_responsible_must_serve_in_the_unit_or_below(self):
        outsider = self.person("BARI-ARMY-B", "Elsewhere")
        r = self.make(responsible=str(outsider.pk))
        self.assertEqual((r.status_code, self.codes(r, "responsible")), (400, ["responsible_not_in_unit"]))

    def test_roles_without_task_permissions_are_refused(self):
        c = self.client_for(self.make_user("reptask", "hq_reporting"))
        self.assertEqual(c.get(T).status_code, 403)
        self.assertEqual(c.post(T, self.body(), format="json").status_code, 403)


class LifecycleTests(TaskBase):
    def test_start_then_complete_with_a_report(self):
        row = self.make().json()
        row = self.act(row, "start").json()
        self.assertEqual(row["status"], "in_progress")
        done = self.act(row, "complete", completion_report="Roster issued", document_ref="DOC-77")
        self.assertEqual((done.status_code, done.json()["status"], done.json()["document_ref"]), (200, "completed", "DOC-77"))
        kinds = [e["kind"] for e in done.json()["events"]]
        self.assertEqual(kinds, ["created", "started", "completed"])

    def test_completion_needs_a_report_and_finished_tasks_are_locked(self):
        row = self.make().json()
        self.assertEqual(self.act(row, "complete", completion_report="").status_code, 400)
        done = self.act(row, "complete", completion_report="Done").json()
        self.assertEqual(self.act(done, "cancel", reason="late").status_code, 409)
        self.assertEqual(self.act(done, "start").status_code, 409)
        r = self.hq.patch(f"{T}{done['id']}/", {"title": "Changed", "version": done["version"]}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_cancel_needs_a_reason(self):
        row = self.make().json()
        self.assertEqual(self.act(row, "cancel", reason="").status_code, 400)
        r = self.act(row, "cancel", reason="Order withdrawn")
        self.assertEqual((r.status_code, r.json()["status"], r.json()["cancel_reason"]), (200, "cancelled", "Order withdrawn"))

    def test_update_changes_fields_and_logs_it(self):
        row = self.make().json()
        r = self.hq.patch(f"{T}{row['id']}/", {"due_on": iso(14), "version": row["version"]}, format="json")
        self.assertEqual((r.status_code, r.json()["due_on"]), (200, iso(14)))
        self.assertEqual(r.json()["events"][-1]["kind"], "updated")

    def test_overdue_is_flagged_and_filterable(self):
        row = self.make(assigned_on=iso(-10), due_on=iso(-2)).json()
        self.assertTrue(row["overdue"])
        self.make(title="Later")
        r = self.hq.get(T, {"overdue": "1"})
        self.assertEqual([x["id"] for x in r.json()["results"]], [row["id"]])

    def test_stale_version_is_refused(self):
        row = self.make().json()
        self.act(row, "start")
        self.assertEqual(self.act(row, "cancel", reason="x").status_code, 409)

    def test_event_log_cannot_be_changed(self):
        from apps.core.appendonly import AppendOnlyError
        row = self.make().json()
        ev = TaskEvent.objects.get(task_id=row["id"])
        ev.note = "tampered"
        with self.assertRaises(AppendOnlyError):
            ev.save()


class MembersTests(TaskBase):
    def test_members_lists_only_people_in_the_unit_with_narrow_fields(self):
        other = self.person("BARI-ARMY-B", "Other Unit")
        r = self.hq.get(f"{T}members/", {"org_unit": str(self.unit_a.pk)})
        self.assertEqual(r.status_code, 200, r.content)
        ids = [x["id"] for x in r.json()["results"]]
        self.assertIn(str(self.p1.pk), ids)
        self.assertNotIn(str(other.pk), ids)
        self.assertEqual(set(r.json()["results"][0]), {"id", "full_name", "service_number", "rank", "unit"})
        self.assertTrue(AuditEvent.objects.filter(action="task.members_lookup").exists())
