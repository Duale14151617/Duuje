"""Retire the Police service from a running database. Nothing is deleted.

The Police code was removed from this build (it is kept in police-archive/). Databases created before that still hold a
POLICE branch, regional Police commands, Police ranks and the Police appointment titles. This command switches all of them
off (active = False) so they stop showing, and can first write a JSON copy of that structure so it can be restored later.

  python manage.py retire_police                         dry run: only reports what it would switch off
  python manage.py retire_police --apply                 switch them off (idempotent; safe to run at every start-up)
  python manage.py retire_police --apply --export f.json also write the structure to f.json first

Personnel records, history and audit rows are never touched. To bring Police back: restore police-archive/ (see its README)
and run `python manage.py retire_police --restore`.
"""
from django.core import serializers
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.organization.models import OrganizationalUnit as OU
from apps.organization.models import ServiceBranch
from apps.personnel.models import AppointmentType, Personnel
from apps.ranks.models import Rank

POLICE_APPOINTMENT_CODES = ("CHIEF_OF_POLICE", "STATION_COMMANDER", "POLICE_CHIEF", "POLICE_STATION_LEAD")


class Command(BaseCommand):
    help = "Switch the Police branch, units, ranks and appointment titles off (no deletion). Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="make the change (default: dry run)")
        parser.add_argument("--export", metavar="FILE", help="write the Police structure to this JSON file first")
        parser.add_argument("--restore", action="store_true", help="switch everything back on (needs the archived code)")
        parser.add_argument("--purge", action="store_true", help="with --apply: also DELETE the Police rows nothing refers to (irreversible; use --export first to keep a copy)")

    def retire_accounts(self, branch, apply):
        """Revoke the role assignments that belong to Police/CID (by role, or by a Police unit/branch) and disable the accounts that
        are left with no other active role. Nothing is deleted; every change is audited; other people's accounts are untouched."""
        from django.utils import timezone

        from apps.accounts.models import RoleAssignment, User
        from apps.accounts.services import is_police_label, police_role_ids, revoke_user_sessions
        from apps.audit.services import record

        role_ids = police_role_ids()
        q = Q(role_id__in=role_ids)
        if branch is not None:
            q |= Q(org_unit__branch=branch) | Q(branch=branch)
        police = list(RoleAssignment.objects.filter(q, revoked_at__isnull=True).select_related("user", "role"))
        users = {a.user_id: a.user for a in police}
        for u in User.objects.filter(is_active=True):  # accounts named after the Police service with no role left to lose
            if u.pk not in users and (is_police_label(u.username) or is_police_label(u.full_name)):
                users[u.pk] = u
        self.stdout.write(f"Police accounts: {len(police)} role assignments and {len(users)} accounts concerned.")
        if not apply:
            return
        now = timezone.now()
        with transaction.atomic():
            for a in police:
                a.revoked_at = now
                a.save(update_fields=["revoked_at"])
            for u in users.values():
                still_has_role = RoleAssignment.objects.filter(user=u, revoked_at__isnull=True).exists()
                if still_has_role or not u.is_active:
                    continue
                u.is_active = False
                u.save(update_fields=["is_active"])
                revoke_user_sessions(u)
                record("user.retire_police", entity_type="user", entity_id=u.pk, metadata={"username": u.username})
            if police:
                record("role_assignment.retire_police", entity_type="role_assignment", metadata={"count": len(police)})

    def police_units(self, branch):
        """Units of the Police branch, any unit named or coded after the Police/CID service, and everything below them."""
        from apps.accounts.services import is_police_label

        ids, paths = set(), []
        for u in OU.objects.only("pk", "path", "code", "name_en", "name_so", "branch_id"):
            if (branch is not None and u.branch_id == branch.pk) or is_police_label(u.code) or is_police_label(u.name_en) or is_police_label(u.name_so):
                ids.add(u.pk)
                paths.append(u.path)
        if paths:
            for u in OU.objects.only("pk", "path"):
                if u.pk not in ids and any(u.path.startswith(x) for x in paths):
                    ids.add(u.pk)
        return OU.objects.filter(pk__in=ids)

    def purge(self, branch, units, ranks, titles):
        """Delete what nothing refers to any more (deepest units first). Anything still referenced (people, history, requests) is
        kept, already switched off, and reported."""
        from django.db import DatabaseError

        gone = kept = 0
        victims = sorted(units, key=lambda u: len(u.path), reverse=True) + list(titles) + list(ranks) + ([branch] if branch else [])
        for obj in victims:
            try:
                with transaction.atomic():
                    obj.delete()
                gone += 1
            except (DatabaseError, Exception) as exc:  # protected by a person, a record or a rule: leave it switched off
                kept += 1
                self.stdout.write(f"  kept {obj.__class__.__name__} {getattr(obj, 'code', obj.pk)}: still in use ({exc.__class__.__name__})")
        self.stdout.write(self.style.SUCCESS(f"Police purge: {gone} deleted, {kept} kept because they are still referenced (they stay switched off and hidden)."))

    def handle(self, *args, **opts):
        branch = ServiceBranch.objects.filter(code="POLICE").first()
        if not opts["restore"]:
            self.retire_accounts(branch, apply=opts["apply"])
        flag = bool(opts["restore"])  # the value `active` is moved to
        units = self.police_units(branch)
        sets = {"units": units, "appointment titles": AppointmentType.objects.filter(code__in=POLICE_APPOINTMENT_CODES)}
        if branch is not None:
            sets = {"branch": ServiceBranch.objects.filter(pk=branch.pk), **sets, "ranks": Rank.objects.filter(branch=branch)}
        todo = {name: qs.exclude(active=flag).count() for name, qs in sets.items()}
        if not any(qs.exists() for qs in sets.values()):
            self.stdout.write("Police: nothing to retire (no Police branch, units, ranks or titles in this database).")
            return
        people = Personnel.objects.filter(org_unit__in=units).count()
        verb = "switched on" if flag else "switched off"
        self.stdout.write("Police " + ("restore" if flag else "retire") + ": " +
                          ", ".join(f"{n} {name}" for name, n in todo.items()) + f" to be {verb}; {people} personnel records stay untouched.")
        if opts["export"]:
            objs = [o for qs in sets.values() for o in qs]
            with open(opts["export"], "w", encoding="utf-8") as fh:
                serializers.serialize("json", objs, stream=fh, indent=1)
            self.stdout.write(f"Structure written to {opts['export']} ({len(objs)} rows).")
        if not opts["apply"] and not flag:
            self.stdout.write("Dry run. Add --apply to make the change.")
            return
        with transaction.atomic():
            for qs in sets.values():
                qs.exclude(active=flag).update(active=flag)
        self.stdout.write(self.style.SUCCESS(f"Police: done, everything {verb}."))
        if opts["purge"] and not flag:
            self.purge(branch, list(units), list(sets.get("ranks", [])), list(sets["appointment titles"]))
