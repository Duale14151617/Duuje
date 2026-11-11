"""Remove the Navy branch and the Karkaar region from a database that was seeded before they were dropped from this build.

  python manage.py remove_legacy_structure                 dry run: only reports what it would do
  python manage.py remove_legacy_structure --apply         switch them off (idempotent; safe to run at every start-up)
  python manage.py remove_legacy_structure --apply --purge also DELETE the rows nothing refers to

Army personnel who sit in the Karkaar region are first transferred into the Bari Army command (a normal, audited transfer:
a history entry is written for each person, and deceased files are left alone). Then the units are switched off, which hides
them from trees, lists and drop-downs; the legacy branch is closed, its ranks deactivated and role assignments held at those
units revoked. Personnel records, history and audit rows are never deleted: a unit that still holds people (for example
people of the legacy branch, or deceased files) or ever had a role assignment stays switched off and is reported. A fresh
database never has any of these rows, so the command then reports that there is nothing to do.
"""
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models import F, ProtectedError
from django.utils import timezone

BRANCH_CODES = ("NAVY",)
REGION_CODES = ("KARKAAR",)
MERGE_INTO = "BARI-ARMY"  # Army command that receives the people of the removed region
MERGE_REASON = "Region merged into Bari"


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
        mover_qs = self._movers(Personnel, OU, ids)
        target = OU.objects.filter(code=MERGE_INTO, active=True).first()
        people = Personnel.objects.filter(org_unit_id__in=ids).count() + Personnel.objects.filter(branch_id__in=bids).count()
        assignments = RoleAssignment.objects.filter(org_unit_id__in=ids, revoked_at__isnull=True)
        self.stdout.write(f"Legacy structure: {len(branches)} branches, {len(units)} units, {ranks.count()} ranks, "
                          f"{assignments.count()} active role assignments, {people} personnel records concerned.")
        self.stdout.write(f"{mover_qs.count()} Army personnel would move to {MERGE_INTO}." if target else
                          f"{mover_qs.count()} Army personnel would need moving, but {MERGE_INTO} is missing or inactive.")
        if not apply:
            self.stdout.write("Dry run: nothing changed. Run again with --apply.")
            return

        now = timezone.now()
        moved = self._move_people(mover_qs, target, now) if target else 0
        if moved:
            self.stdout.write(f"Moved {moved} Army personnel to {MERGE_INTO}.")
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
    def _movers(Personnel, OU, unit_ids):
        """Army personnel in the removed region who can still be changed (deceased files are closed)."""
        region_ids = [u.pk for u in OU.objects.filter(code__in=REGION_CODES)]
        paths = [u.path for u in OU.objects.filter(pk__in=region_ids)]
        in_region = [u.pk for u in OU.objects.filter(pk__in=unit_ids) if any(u.path.startswith(p) for p in paths)]
        return Personnel.objects.filter(org_unit_id__in=in_region, branch__code="ARMY").exclude(status=Personnel.Status.DIED)

    @staticmethod
    def _move_people(qs, target, now):
        from apps.audit.services import record
        from apps.personnel import services as svc
        from apps.personnel.models import Personnel
        moved = 0
        for person in qs.select_related("org_unit"):
            with transaction.atomic():
                old = person.org_unit
                Personnel.objects.filter(pk=person.pk).update(org_unit=target, branch=target.branch,
                                                              version=F("version") + 1, updated_at=now)
                svc.add_history(person, "org_unit", str(old.pk), str(target.pk), old.name_en, target.name_en,
                                now.date(), MERGE_REASON, None)
                record("personnel.region_merge_transfer", entity_type="personnel", entity_id=person.pk,
                       metadata={"from": str(old.pk), "to": str(target.pk)})
            moved += 1
        return moved

    @staticmethod
    def _delete(obj, gone, kept):
        try:
            with transaction.atomic():
                obj.delete()
            return gone + 1, kept
        except (ProtectedError, IntegrityError):
            return gone, kept + 1
