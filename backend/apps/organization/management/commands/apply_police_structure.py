from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.services import record
from apps.organization import police_structure, profiles
from apps.organization.models import OrganizationalUnit, ServiceBranch, UnitType
from apps.personnel.models import AppointmentType


class Command(BaseCommand):
    help = ("Create the Police organizational structure: unit types, appointment titles, Police Headquarters with its directorates "
            "(CID, Traffic, Tax collection) and one regional command per region. Districts, stations and Kooxo are added with the "
            "normal unit tools. Safe to run again; without --apply it only reports what it would do.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (default is a dry run).")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        with transaction.atomic():
            lines = police_structure.apply(OrganizationalUnit, UnitType, ServiceBranch, AppointmentType, dry_run=not apply)
            if apply and any(a != "blocked" for a, _ in lines):
                record("org.police_structure_applied", entity_type="organization", metadata={"actions": [f"{a}: {d}" for a, d in lines][:50]})
        if apply and not any(a == "blocked" for a, _ in lines):
            with transaction.atomic():
                made = profiles.establish_standard_departments()
                if made:
                    record("org.departments_established", entity_type="organization", metadata={"count": made})
        for action, detail in lines:
            self.stdout.write(f"{'APPLIED' if apply and action != 'blocked' else 'WOULD' if not apply else 'NOTE'} {action}: {detail}")
        if not lines:
            self.stdout.write("Nothing to do: the Police structure is already in place.")
