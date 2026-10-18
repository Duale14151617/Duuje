"""The seeded Police ranks must match Article 23 of Law No. 2 of 23 December 1972 (supplied copy, page 107),
and approving them is an accountable, guarded action."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.core.testing import BaseApiTest
from apps.ranks.models import Rank

# Article 23(1), senior -> junior, exactly as printed (class, title). "General Officers" has no ranks listed.
LAW = [("senior_officer", "Colonel"), ("senior_officer", "Lieutenant Colonel"), ("senior_officer", "Major"),
       ("junior_officer", "Captain"), ("junior_officer", "Lieutenant"), ("junior_officer", "Second Lieutenant"),
       ("inspector", "Chief Inspector"), ("inspector", "Inspector"), ("inspector", "Sub-Inspector"),
       ("nco", "First Sergeant"), ("nco", "Sergeant"), ("nco", "Cadet Officer"),
       ("askari", "First Askari"), ("askari", "Askari"), ("askari", "Recruit")]


@override_settings(POLICE_MODULE_ENABLED=True)
class PoliceLawTests(BaseApiTest):
    def test_catalogue_matches_article_23_in_order_and_class(self):
        ranks = Rank.objects.filter(branch__code="POLICE").order_by("-sort_order")  # senior first
        self.assertEqual([(r.category, r.name_en) for r in ranks], LAW)

    def test_general_officers_are_not_invented(self):
        self.assertFalse(Rank.objects.filter(branch__code="POLICE", category="general_officer").exists())

    def test_approval_needs_a_real_approver_and_the_review_confirmation(self):
        self.make_user("rankadm", "super_admin")   # holds ranks.approve at headquarters
        with self.assertRaises(CommandError):
            call_command("approve_police_ranks", by="nobody", confirm_reviewed=True)
        self.make_user("plain", "read_only", unit="BARI")
        with self.assertRaises(CommandError):
            call_command("approve_police_ranks", by="plain", confirm_reviewed=True)   # lacks ranks.approve
        with self.assertRaises(CommandError):
            call_command("approve_police_ranks", by="rankadm")                         # no --confirm-reviewed
        self.assertFalse(Rank.objects.filter(branch__code="POLICE", approval_status="approved").exists())

    def test_dry_run_writes_nothing_then_approval_is_attributed_and_audited(self):
        admin = self.make_user("rankadm", "super_admin")
        out = StringIO()
        call_command("approve_police_ranks", by="rankadm", dry_run=True, stdout=out)
        self.assertIn("Would approve 15", out.getvalue())
        self.assertFalse(Rank.objects.filter(branch__code="POLICE", approval_status="approved").exists())
        call_command("approve_police_ranks", by="rankadm", confirm_reviewed=True, stdout=StringIO())
        ranks = Rank.objects.filter(branch__code="POLICE")
        self.assertEqual(ranks.filter(approval_status="approved", approved_by=admin).count(), 15)
        self.assertEqual(AuditEvent.objects.filter(action="rank.approve", actor_id=admin.pk).count(), 15)

    def test_a_renamed_rank_is_not_approved_by_the_command(self):
        self.make_user("rankadm", "super_admin")
        Rank.objects.filter(branch__code="POLICE", name_en="Recruit").update(name_en="Trainee")
        call_command("approve_police_ranks", by="rankadm", confirm_reviewed=True, stdout=StringIO())
        self.assertEqual(Rank.objects.get(branch__code="POLICE", name_en="Trainee").approval_status, "draft")
        self.assertEqual(Rank.objects.filter(branch__code="POLICE", approval_status="approved").count(), 14)

    def test_command_authority_command_creates_a_confined_account(self):
        import os
        from apps.accounts.models import RoleAssignment, User
        os.environ["ARMYHQ_ADMIN_PASSWORD"] = "Correct-Horse-Battery-9"
        try:
            call_command("create_command_authority", username="President", full_name="Test Holder", stdout=StringIO())
        finally:
            os.environ.pop("ARMYHQ_ADMIN_PASSWORD", None)
        u = User.objects.get(username="president")
        self.assertTrue(u.must_change_password)
        self.assertEqual(RoleAssignment.objects.get(user=u).role.code, "command_authority")
