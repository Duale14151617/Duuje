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

    def handle(self, *args, **opts):
        branch = ServiceBranch.objects.filter(code="POLICE").first()
        if branch is None:
            self.stdout.write("Police: nothing to retire (no POLICE branch in this database).")
            return
        flag = bool(opts["restore"])  # the value `active` is moved to
        sets = {"branch": ServiceBranch.objects.filter(pk=branch.pk), "units": OU.objects.filter(branch=branch),
                "ranks": Rank.objects.filter(branch=branch),
                "appointment titles": AppointmentType.objects.filter(code__in=POLICE_APPOINTMENT_CODES)}
        todo = {name: qs.exclude(active=flag).count() for name, qs in sets.items()}
        people = Personnel.objects.filter(org_unit__branch=branch).count()
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
