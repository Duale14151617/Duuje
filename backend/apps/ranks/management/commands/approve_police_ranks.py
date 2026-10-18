"""Approve the Police rank catalogue as an accountable, named administrator (alternative to clicking Approve 15 times).

  python manage.py approve_police_ranks --by <username> --confirm-reviewed [--dry-run]

What it does: for each DRAFT Police rank whose class and name match Article 23 (Order of Precedence) of Law No. 2 of
23 December 1972 exactly, it sets the rank APPROVED with `approved_by` = the named user and writes a `rank.approve` audit
event (via=management_command, source=Article 23). Nothing else changes; ranks that were edited, renamed or are not in the
law are left as draft and reported.

Guards: the user must exist, be active and hold `ranks.approve` through a global (headquarters) assignment, exactly as the
Ranks page requires; and --confirm-reviewed must be given, meaning that person has reviewed the list against CURRENT Puntland
Police rules (the 1972 law is a historical baseline). Without --confirm-reviewed nothing is written.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts import scope
from apps.accounts.models import User
from apps.audit.services import record
from apps.ranks.models import Rank
from apps.ranks.police_catalogue import ARTICLE_23


class Command(BaseCommand):
    help = "Approve the draft Police ranks that match Article 23 of Law No. 2 of 1972, as a named administrator."

    def add_arguments(self, parser):
        parser.add_argument("--by", required=True, help="username of the authorised administrator approving")
        parser.add_argument("--confirm-reviewed", action="store_true",
                            help="that administrator has reviewed the ranks against current Puntland Police rules")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        user = User.objects.filter(username=opts["by"].lower(), is_active=True).first()
        if user is None or not scope.can(user, "ranks.approve"):
            raise CommandError("That user does not exist, is inactive, or does not hold ranks.approve at headquarters.")
        if not opts["confirm_reviewed"] and not opts["dry_run"]:
            raise CommandError("Add --confirm-reviewed once the list has been reviewed against current Puntland Police rules "
                               "(or use --dry-run to see what would change).")
        law = {(category, name) for category, name in ARTICLE_23}
        done = skipped = 0
        for rank in Rank.objects.select_for_update().filter(branch__code="POLICE", approval_status=Rank.Approval.DRAFT, active=True):
            if (rank.category, rank.name_en) not in law:
                skipped += 1
                self.stdout.write(f"Left as draft (not in Article 23 as written): {rank.code} {rank.name_en}")
                continue
            if not opts["dry_run"]:
                rank.approval_status = Rank.Approval.APPROVED
                rank.approved_by, rank.approved_at = user, timezone.now()
                rank.version += 1
                rank.save(update_fields=["approval_status", "approved_by", "approved_at", "version", "updated_at"])
                record("rank.approve", actor=user, entity_type="rank", entity_id=rank.pk,
                       metadata={"via": "management_command", "source": "Law No. 2 of 23 Dec 1972, Article 23"})
            done += 1
        verb = "Would approve" if opts["dry_run"] else "Approved"
        self.stdout.write(self.style.SUCCESS(f"{verb} {done} Police rank(s); {skipped} left as draft."))
