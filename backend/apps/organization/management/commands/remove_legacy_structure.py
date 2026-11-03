"""Remove the Navy branch and the Karkaar region from a database that was seeded before they were dropped from this build.

  python manage.py remove_legacy_structure                 dry run: only reports what it would do
  python manage.py remove_legacy_structure --apply         switch them off (idempotent; safe to run at every start-up)
  python manage.py remove_legacy_structure --apply --purge also DELETE the rows nothing refers to

Switching off hides the units from trees, lists and drop-downs, closes the branch, deactivates its ranks and revokes role
assignments held at those units. Personnel records, history and audit rows are never touched or deleted: a unit that still
holds people (or ever had a role assignment) stays switched off and is reported, so the people can be transferred with the
normal tools. A fresh database never has any of these rows, so the command then reports that there is nothing to do.
"""
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models import F, ProtectedError
from django.utils import timezone

BRANCH_CODES = ("NAVY",)
REGION_CODES = ("KARKAAR",)


class Command(BaseCommand):
    help = "Switch off (and optionally delete) the legacy Navy branch and Karkaar region. Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="make the changes (default is a dry run)")
        parser.add_argument("--purge", action="store_true", help="with --apply: also delete rows nothing refers to (irreversible)")

    def handle(self, *args, **opts):
        from apps.accounts.models import RoleAssignment
        from apps.organization.models import OrganizationalUnit as OU, ServiceBranch
        from apps.personnel.models import Personnel
        from apps.ranks.models import Rank

        apply, purge = opts["apply"], opts["purge"] and opts["apply"]
        branches = list(ServiceBranch.objects.filter(code__in=BRANCH_CODES))
        bids = [b.pk for b in branches]
        units = {u.pk: u for u in OU.objects.filter(branch_id__in=bids)}
        for region in OU.objects.filter(code__in=REGION_CODES, level="region"):
            for u in OU.objects.filter(path__startswith=region.path):
                units[u.pk] = u
        ranks = Rank.objects.filter(branch_id__in=bids)
        if not branches and not units:
            self.stdout.write("Legacy structure: nothing to remove.")
            return
        ids = list(units)
        people = Personnel.objects.filter(org_unit_id__in=ids).count() + Personnel.objects.filter(branch_id__in=bids).count()
        assignments = RoleAssignment.objects.filter(org_unit_id__in=ids, revoked_at__isnull=True)
        self.stdout.write(f"Legacy structure: {len(branches)} branches, {len(units)} units, {ranks.count()} ranks, "
                          f"{assignments.count()} active role assignments, {people} personnel records concerned.")
        if not apply:
            self.stdout.write("Dry run: nothing changed. Run again with --apply.")
            return

        now = timezone.now()
        with transaction.atomic():
            assignments.update(revoked_at=now)
            OU.objects.filter(pk__in=ids, active=True).update(active=False, version=F("version") + 1, updated_at=now)
            ranks.filter(active=True).update(active=False, version=F("version") + 1, updated_at=now)
            ServiceBranch.objects.filter(pk__in=bids, active=True).update(active=False, version=F("version") + 1, updated_at=now)
        self.stdout.write("Switched off.")

        if purge:
            gone = kept = 0
            for u in sorted(units.values(), key=lambda x: len(x.path), reverse=True):  # children before parents
                gone, kept = self._delete(u, gone, kept)
            for r in ranks:
                gone, kept = self._delete(r, gone, kept)
            for b in branches:
                gone, kept = self._delete(b, gone, kept)
            self.stdout.write(f"Purge: {gone} deleted, {kept} kept because something still refers to them (they stay switched off).")
        remaining = Personnel.objects.filter(org_unit_id__in=ids).count()
        if remaining:
            self.stdout.write(self.style.WARNING(
                f"{remaining} personnel records still sit in switched-off units; transfer them with the normal transfer tools."))

    @staticmethod
    def _delete(obj, gone, kept):
        try:
            with transaction.atomic():
                obj.delete()
            return gone + 1, kept
        except (ProtectedError, IntegrityError):
            return gone, kept + 1
