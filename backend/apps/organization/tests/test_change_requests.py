"""Approval queue for hierarchy-affecting actions: HQ administrators propose, the super administrator decides. Synthetic data only."""
from apps.audit.models import AuditEvent
from apps.organization.models import ChangeRequest
from apps.personnel.models import Personnel
from apps.personnel.tests.test_personnel import PersonnelBase

URL = "/api/v1/organization/change-requests/"


class Base(PersonnelBase):
    def setUp(self):
        super().setUp()
        self.hq = self.client_for(self.make_user("hqadm", "hq_admin"))
        self.hq2 = self.client_for(self.make_user("hqadm2", "hq_admin"))
        self.sa_user = self.make_user("sup", "super_admin")
        self.sa = self.client_for(self.sa_user)
        self.person_a = self.person("BARI-ARMY-A", "Soldier One", service_number="S-100")

    def body(self, person=None, to="BARI-ARMY-B", **over):
        p = person or self.person_a
        data = {"kind": "transfer", "order_ref": "Order 41/2026", "issuing_officer": "Col. Example", "order_date": "2026-10-01",
                "payload": {"personnel": str(p.pk), "org_unit": str(self.unit(to).pk), "effective_date": "2026-10-02", "reason": "Posting"}}
        data.update(over)
        return data

    def propose(self, client=None, **kw):
        return (client or self.hq).post(URL, self.body(**kw), format="json")

    def act(self, row, name, client=None, note="ok"):
        return (client or self.sa).post(f"{URL}{row['id']}/{name}/", {"version": row["version"], "note": note}, format="json")


class ProposeTests(Base):
    def test_hq_admin_proposal_is_pending_and_changes_nothing(self):
        r = self.propose()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], "pending")
        self.person_a.refresh_from_db()
        self.assertEqual(self.person_a.org_unit.code, "BARI-ARMY-A")
        self.assertTrue(AuditEvent.objects.filter(action="change_request.propose").exists())

    def test_order_reference_and_officer_are_required(self):
        for field in ("order_ref", "issuing_officer", "order_date"):
            r = self.propose(**{field: ""})
            self.assertEqual(r.status_code, 400, field)
        self.assertEqual(ChangeRequest.objects.count(), 0)

    def test_invalid_transfers_are_refused(self):
        self.assertEqual(self.propose(to="BARI-ARMY-A").status_code, 400)  # same unit
        bad = self.body()
        bad["payload"]["personnel"] = "not-a-uuid"
        self.assertEqual(self.hq.post(URL, bad, format="json").status_code, 400)
        self.assertEqual(self.propose(kind="delete_everything").status_code, 400)

    def test_cannot_transfer_someone_holding_an_open_appointment(self):
        from datetime import date
        from apps.personnel.models import AppointmentType, CommandAppointment
        t = AppointmentType.objects.first()
        CommandAppointment.objects.create(personnel=self.person_a, org_unit=self.unit("BARI-ARMY-A"), appointment_type=t,
                                          exclusive=False, effective_from=date.today())
        r = self.propose()
        self.assertEqual((r.status_code, self.codes(r, "personnel")), (400, ["has_open_appointment"]))


class DecisionTests(Base):
    def test_approval_applies_the_transfer_and_keeps_history(self):
        row = self.propose().json()
        r = self.act(row, "approve")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "approved")
        self.person_a.refresh_from_db()
        self.assertEqual(self.person_a.org_unit.code, "BARI-ARMY-B")
        hist = self.person_a.history.filter(field="org_unit", new_label="Bari-Army-B").first()  # not the creation row (its date is today)
        self.assertEqual((hist.old_label, hist.new_label), ("Bari-Army-A", "Bari-Army-B"))
        self.assertIn("Order 41/2026", hist.reason)
        self.assertEqual(Personnel.objects.filter(org_unit__code="BARI-ARMY-A", pk=self.person_a.pk).count(), 0)  # counted once
        self.assertTrue(AuditEvent.objects.filter(action="personnel.transfer", metadata__order_ref="Order 41/2026").exists())

    def test_reject_needs_a_reason_and_changes_nothing(self):
        row = self.propose().json()
        self.assertEqual(self.act(row, "reject", note="").status_code, 400)
        r = self.act(row, "reject", note="Order not valid")
        self.assertEqual(r.json()["status"], "rejected")
        self.person_a.refresh_from_db()
        self.assertEqual(self.person_a.org_unit.code, "BARI-ARMY-A")

    def test_hq_admins_cannot_approve_reject_or_review(self):
        row = self.propose().json()
        for name in ("approve", "reject", "start-review"):
            self.assertEqual(self.act(row, name, client=self.hq2).status_code, 403, name)
            self.assertEqual(self.act(row, name, client=self.hq).status_code, 403, name)
        self.assertEqual(ChangeRequest.objects.get(pk=row["id"]).status, "pending")

    def test_super_admin_own_entry_applies_at_once_and_is_flagged(self):
        r = self.propose(client=self.sa)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["status"], r.json()["self_approved"]), ("approved", True))
        self.person_a.refresh_from_db()
        self.assertEqual(self.person_a.org_unit.code, "BARI-ARMY-B")

    def test_approval_rechecks_and_refuses_a_stale_request(self):
        row = self.propose().json()
        other = self.propose(client=self.hq2, to="BARI-ARMY-B").json()  # second request for the same move
        self.assertEqual(self.act(row, "approve").status_code, 200)
        r = self.act(other, "approve")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "stale_request"))
        self.assertEqual(ChangeRequest.objects.get(pk=other["id"]).status, "pending")

    def test_a_decided_request_cannot_be_decided_again(self):
        row = self.propose().json()
        self.act(row, "reject", note="no")
        fresh = self.sa.get(f"{URL}{row['id']}/").json()
        self.assertEqual(self.act(fresh, "approve").status_code, 409)


class WithdrawTests(Base):
    def test_proposer_can_withdraw_until_review_starts(self):
        row = self.propose().json()
        r = self.hq.post(f"{URL}{row['id']}/withdraw/", {"version": row["version"]}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "withdrawn"))

    def test_only_the_proposer_can_withdraw(self):
        row = self.propose().json()
        r = self.hq2.post(f"{URL}{row['id']}/withdraw/", {"version": row["version"]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_no_withdrawal_once_under_review(self):
        row = self.propose().json()
        reviewing = self.act(row, "start-review").json()
        self.assertEqual(reviewing["status"], "in_review")
        r = self.hq.post(f"{URL}{row['id']}/withdraw/", {"version": reviewing["version"]}, format="json")
        self.assertEqual(r.status_code, 409)


class AccessTests(Base):
    def test_roles_without_the_permission_are_refused(self):
        for name, role, unit, branch in (("rep", "hq_reporting", "HQ", None), ("bm", "branch_admin", "BARI", "ARMY"),
                                         ("aud", "auditor", "HQ", None)):
            c = self.client_for(self.make_user(name, role, unit=unit, branch=branch))
            self.assertEqual(c.get(URL).status_code, 403, role)
            self.assertEqual(c.post(URL, self.body(), format="json").status_code, 403, role)

    def test_hq_admin_sees_the_queue_and_it_is_audited(self):
        self.propose()
        r = self.hq.get(URL)
        self.assertEqual((r.status_code, len(r.json()["results"])), (200, 1))
        self.assertTrue(AuditEvent.objects.filter(action="change_request.list").exists())

    def test_hq_admin_still_cannot_transfer_directly(self):
        r = self.hq.post(f"/api/v1/personnel/{self.person_a.pk}/transfer/",
                         {"org_unit": str(self.unit("BARI-ARMY-B").pk), "version": 1}, format="json")
        self.assertIn(r.status_code, (403, 404))
        self.person_a.refresh_from_db()
        self.assertEqual(self.person_a.org_unit.code, "BARI-ARMY-A")


class AppointmentRequestTests(Base):
    def setUp(self):
        super().setUp()
        from django.core.management import call_command
        from apps.organization.models import OrganizationalUnit as OU, UnitType
        call_command("apply_army_structure", "--apply", stdout=open("/dev/null", "w"))
        self.urur = OU.objects.create(code="BARI-ARMY-URUR1", name_en="Urur 1", level="unit",
                                      parent=OU.objects.get(code="BARI-ARMY"), unit_type=UnitType.objects.get(code="URUR"))
        self.major = self.person("BARI-ARMY-A", "Major One", rank="PA-10")

    def type_id(self, code="TALIYE_URUR"):
        from apps.personnel.models import AppointmentType
        return str(AppointmentType.objects.get(code=code).pk)

    def add_body(self, **payload):
        p = {"personnel": str(self.major.pk), "org_unit": str(self.urur.pk), "appointment_type": self.type_id(),
             "effective_from": "2026-10-05"}
        p.update(payload)
        return {"kind": "appointment_add", "order_ref": "Order 77/2026", "issuing_officer": "Gen. Example",
                "order_date": "2026-10-01", "payload": p}

    def test_proposal_writes_nothing_and_approval_creates_the_appointment_with_the_order(self):
        from apps.personnel.models import CommandAppointment
        r = self.hq.post(URL, self.add_body(), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(CommandAppointment.objects.count(), 0)  # the dry run rolled back
        self.assertEqual(self.act(r.json(), "approve").status_code, 200)
        a = CommandAppointment.objects.get()
        self.assertIn("Order 77/2026", a.authority_ref)
        self.assertEqual((a.personnel_id, a.org_unit_id), (self.major.pk, self.urur.pk))

    def test_the_real_appointment_rules_apply_at_proposal(self):
        r = self.hq.post(URL, self.add_body(appointment_type=self.type_id("TALIYE_GUUTO")), format="json")
        self.assertEqual((r.status_code, self.codes(r, "org_unit")), (400, ["appointment_unit_mismatch"]))

    def test_a_second_exclusive_holder_is_refused_at_approval(self):
        other = self.person("BARI-ARMY-A", "Major Two", rank="PA-10")
        first = self.hq.post(URL, self.add_body(), format="json").json()
        second = self.hq.post(URL, self.add_body(personnel=str(other.pk)), format="json").json()
        self.assertEqual(self.act(first, "approve").status_code, 200)
        r = self.act(second, "approve")
        self.assertEqual((r.status_code, self.codes(r, "appointment_type")), (400, ["appointment_exists"]))

    def test_end_request_ends_the_appointment_on_approval(self):
        from apps.personnel.models import CommandAppointment
        self.act(self.hq.post(URL, self.add_body(), format="json").json(), "approve")
        appt = CommandAppointment.objects.get()
        body = {"kind": "appointment_end", "order_ref": "Order 90/2026", "issuing_officer": "Gen. Example", "order_date": "2026-11-01",
                "payload": {"personnel": str(self.major.pk), "appointment": str(appt.pk), "reason": "Replaced"}}
        r = self.hq.post(URL, body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        appt.refresh_from_db()
        self.assertIsNone(appt.ended_at)
        self.assertEqual(self.act(r.json(), "approve").status_code, 200)
        appt.refresh_from_db()
        self.assertIsNotNone(appt.ended_at)
        self.assertIn("Order 90/2026", appt.end_reason)

    def test_end_request_needs_a_reason(self):
        body = {"kind": "appointment_end", "order_ref": "O", "issuing_officer": "G", "order_date": "2026-11-01",
                "payload": {"personnel": str(self.major.pk), "appointment": "not-a-uuid", "reason": ""}}
        self.assertEqual(self.hq.post(URL, body, format="json").status_code, 400)


class PeopleLookupTests(Base):
    def test_hq_admin_can_find_a_person_but_only_narrow_fields(self):
        r = self.hq.get(f"{URL}people/", {"q": "Soldier"})
        self.assertEqual(r.status_code, 200, r.content)
        row = r.json()["results"][0]
        self.assertEqual(row["service_number"], "S-100")
        self.assertEqual(set(row), {"id", "full_name", "service_number", "rank", "unit", "unit_id", "status", "open_appointments"})
        self.assertTrue(AuditEvent.objects.filter(action="change_request.people_lookup").exists())

    def test_short_queries_are_refused_and_hq_admin_still_has_no_personnel_list(self):
        self.assertEqual(self.hq.get(f"{URL}people/", {"q": "So"}).status_code, 400)
        self.assertEqual(self.hq.get("/api/v1/personnel/").status_code, 403)

    def test_roles_without_changes_propose_are_refused(self):
        c = self.client_for(self.make_user("rep2", "hq_reporting"))
        self.assertEqual(c.get(f"{URL}people/", {"q": "Soldier"}).status_code, 403)


class CatalogueTests(Base):
    def test_hq_admin_can_list_command_posts_and_others_cannot(self):
        r = self.hq.get(f"{URL}appointment-types/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("TALIYE_URUR", [x["code"] for x in r.json()["results"]])
        c = self.client_for(self.make_user("rep3", "hq_reporting"))
        self.assertEqual(c.get(f"{URL}appointment-types/").status_code, 403)


BULK = URL + "bulk-transfer/"
BATCH = URL + "batch/"


class BulkTransferTests(Base):
    def setUp(self):
        super().setUp()
        self.people = [self.person("BARI-ARMY-A", f"Bulk {i}", service_number=f"B-{i}") for i in range(3)]

    def bulk(self, numbers=None, client=None, **over):
        d = {"order_ref": "Order 50/2026", "issuing_officer": "Col. Example", "order_date": "2026-10-01", "org_unit": str(self.unit("BARI-ARMY-B").pk),
             "effective_date": "2026-10-05", "reason": "Reposting",
             "items": [{"service_number": n} for n in (numbers or ["B-0", "B-1", "B-2"])]}
        d.update(over)
        return (client or self.hq).post(BULK, d, format="json")

    def unit_of(self, p):
        p.refresh_from_db()
        return p.org_unit.code

    def decide(self, batch, action, count=3, client=None, note="ok"):
        return (client or self.sa).post(BATCH, {"batch": batch, "action": action, "count": count, "note": note}, format="json")

    def test_one_order_creates_a_pending_request_per_person_and_changes_nothing(self):
        r = self.bulk()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["count"], {x["status"] for x in r.json()["results"]}), (3, {"pending"}))
        self.assertEqual(len({x["batch"] for x in r.json()["results"]}), 1)
        self.assertEqual({self.unit_of(p) for p in self.people}, {"BARI-ARMY-A"})

    def test_any_bad_row_creates_nothing_and_every_problem_is_reported(self):
        r = self.bulk(["B-0", "NOPE-1", "B-0", "B-2"])
        self.assertEqual(r.status_code, 400)
        rows = {x["row"]: [e["code"] for e in x["errors"]] for x in r.json()["rows"]}
        self.assertEqual(rows, {2: ["personnel_not_found"], 3: ["duplicate_person"]})
        self.assertEqual(ChangeRequest.objects.count(), 0)

    def test_a_person_with_a_pending_transfer_is_refused(self):
        self.assertEqual(self.bulk(["B-0"]).status_code, 201)
        r = self.bulk(["B-0", "B-1"])
        self.assertEqual((r.status_code, r.json()["rows"][0]["errors"][0]["code"]), (400, "already_pending"))
        self.assertEqual(ChangeRequest.objects.count(), 1)

    def test_order_fields_and_size_limits(self):
        self.assertEqual(self.bulk(order_ref="").status_code, 400)
        self.assertEqual(self.bulk(items=[]).status_code, 400)
        self.assertEqual(self.bulk(items=[{"service_number": f"X-{i}"} for i in range(201)]).status_code, 400)

    def test_super_admin_approves_the_whole_batch_at_once(self):
        batch = self.bulk().json()["results"][0]["batch"]
        r = self.decide(batch, "approve")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual({x["status"] for x in r.json()["results"]}, {"approved"})
        self.assertEqual({self.unit_of(p) for p in self.people}, {"BARI-ARMY-B"})
        self.assertTrue(AuditEvent.objects.filter(action="change_request.batch_approve").exists())

    def test_if_one_cannot_be_applied_nothing_in_the_batch_is_applied(self):
        from datetime import date
        from apps.personnel.models import AppointmentType, CommandAppointment
        batch = self.bulk().json()["results"][0]["batch"]
        CommandAppointment.objects.create(personnel=self.people[2], org_unit=self.unit("BARI-ARMY-A"), appointment_type=AppointmentType.objects.first(),
                                          exclusive=False, effective_from=date.today())
        r = self.decide(batch, "approve")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "batch_item_failed"))
        self.assertEqual({self.unit_of(p) for p in self.people}, {"BARI-ARMY-A"})
        self.assertEqual(set(ChangeRequest.objects.values_list("status", flat=True)), {"pending"})

    def test_the_count_guards_against_a_batch_that_changed(self):
        batch = self.bulk().json()["results"][0]["batch"]
        self.assertEqual(self.decide(batch, "approve", count=2).status_code, 409)
        self.assertEqual({self.unit_of(p) for p in self.people}, {"BARI-ARMY-A"})

    def test_hq_admins_cannot_decide_a_batch(self):
        batch = self.bulk().json()["results"][0]["batch"]
        for action in ("approve", "reject", "start_review"):
            self.assertEqual(self.decide(batch, action, client=self.hq2).status_code, 403, action)
        r = self.decide(batch, "approve", client=self.hq)
        self.assertEqual(r.status_code, 403)

    def test_members_of_a_batch_cannot_be_decided_one_by_one(self):
        row = self.bulk().json()["results"][0]
        self.assertEqual(self.act(row, "approve").status_code, 409)
        self.assertEqual(self.hq.post(f"{URL}{row['id']}/withdraw/", {"version": row["version"]}, format="json").status_code, 409)

    def test_reject_needs_a_reason_and_leaves_everyone_in_place(self):
        batch = self.bulk().json()["results"][0]["batch"]
        self.assertEqual(self.decide(batch, "reject", note="").status_code, 400)
        r = self.decide(batch, "reject", note="Order not valid")
        self.assertEqual({x["status"] for x in r.json()["results"]}, {"rejected"})
        self.assertEqual({self.unit_of(p) for p in self.people}, {"BARI-ARMY-A"})

    def test_proposer_withdraws_the_batch_until_review_starts(self):
        batch = self.bulk().json()["results"][0]["batch"]
        self.assertEqual(self.decide(batch, "withdraw", client=self.hq2).status_code, 403)
        r = self.decide(batch, "withdraw", client=self.hq)
        self.assertEqual({x["status"] for x in r.json()["results"]}, {"withdrawn"})
        batch2 = self.bulk().json()["results"][0]["batch"]
        self.assertEqual(self.decide(batch2, "start_review").status_code, 200)
        self.assertEqual(self.decide(batch2, "withdraw", client=self.hq).status_code, 409)

    def test_super_admins_own_bulk_entry_applies_at_once(self):
        r = self.bulk(client=self.sa)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual({(x["status"], x["self_approved"]) for x in r.json()["results"]}, {("approved", True)})
        self.assertEqual({self.unit_of(p) for p in self.people}, {"BARI-ARMY-B"})

    def test_destinations_can_differ_per_row(self):
        items = [{"service_number": "B-0", "org_unit": str(self.unit("BARI-ARMY-B").pk)}, {"service_number": "B-1"}]
        r = self.bulk(items=items, org_unit=str(self.unit("BARI-ARMY-A").pk))  # B-1's default destination is its own unit
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["rows"][0]["row"], 2)
