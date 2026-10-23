"""Police ranks are the Army ranking (separate rows, approved), the retired 1972 draft rows are handled safely, and the remaining
approval command stays guarded."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.core.testing import BaseApiTest
from apps.ranks.catalogue import OFFICIAL_ARMY_RANKS
from apps.ranks.models import Rank
from apps.ranks.police_catalogue import apply_police_ranks


@override_settings(POLICE_MODULE_ENABLED=True)
class PoliceRankTests(BaseApiTest):
    def police(self):
        return Rank.objects.filter(branch__code="POLICE", active=True).order_by("sort_order")

    def test_police_ranks_equal_the_army_list_in_order_and_are_approved(self):
        self.assertEqual([r.name_en for r in self.police()], OFFICIAL_ARMY_RANKS)
        self.assertTrue(all(r.approval_status == "approved" and r.category == "unspecified" for r in self.police()))
        self.assertEqual(self.police().first().code, "PL-01")

    def test_seeding_again_changes_nothing_and_keeps_administrator_edits(self):
        Rank.objects.filter(branch__code="POLICE", code="PL-10").update(name_en="Kabtan", name_so="Kabtan")
        self.assertEqual(apply_police_ranks(Rank, Rank.objects.get(code="PL-10").branch), 0)
        self.assertEqual(Rank.objects.get(branch__code="POLICE", code="PL-10").name_en, "Kabtan")

    def test_untouched_1972_draft_rows_are_removed_and_edited_ones_are_left(self):
        police = Rank.objects.get(branch__code="POLICE", code="PL-01").branch
        Rank.objects.create(branch=police, code="PP-01", category="askari", name_en="Recruit", name_so="Recruit", sort_order=1)
        Rank.objects.create(branch=police, code="PP-02", category="askari", name_en="Edited Name", name_so="x", sort_order=2)
        apply_police_ranks(Rank, police)
        self.assertFalse(Rank.objects.filter(code="PP-01").exists())
        self.assertTrue(Rank.objects.filter(code="PP-02", active=True).exists())

    def test_approval_command_still_needs_a_real_approver_and_the_review_confirmation(self):
        self.make_user("rankadm", "super_admin")
        with self.assertRaises(CommandError):
            call_command("approve_police_ranks", by="nobody", confirm_reviewed=True)
        self.make_user("plain", "read_only", unit="BARI")
        with self.assertRaises(CommandError):
            call_command("approve_police_ranks", by="plain", confirm_reviewed=True)
        with self.assertRaises(CommandError):
            call_command("approve_police_ranks", by="rankadm")
        out = StringIO()
        call_command("approve_police_ranks", by="rankadm", dry_run=True, stdout=out)
        self.assertIn("Would approve 0", out.getvalue())  # nothing left in draft: the ranks are already approved

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
