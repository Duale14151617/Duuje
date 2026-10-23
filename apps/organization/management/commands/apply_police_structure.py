from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.services import record
from apps.organization import police_structure
from apps.organization.models import OrganizationalUnit, ServiceBranch
from apps.personnel.models import AppointmentType
from apps.personnel.police_appointments import ensure_types


class Command(BaseCommand):
    help = ("Create the Puntland Police structure as working units: regional Police commands (including Sanaag), the seven departments "
            "(CID restricted) and Police stations. Police only. Dry run by default; pass --apply to write. Idempotent and additive. "
            "Does nothing while POLICE_MODULE_ENABLED is off.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (default is a dry run).")
        parser.add_argument("--stations-per-command", type=int, default=police_structure.DEFAULT_STATIONS_PER_COMMAND,
                            help="Police stations in each regional command. Raise it later to add more; nothing is ever removed.")

    def handle(self, *args, **opts):
        if not settings.POLICE_MODULE_ENABLED:
            self.stdout.write("Police module is OFF (POLICE_MODULE_ENABLED): nothing to do.")
            return
        if not 1 <= opts["stations_per_command"] <= police_structure.MAX_STATIONS:
            raise CommandError(f"--stations-per-command must be between 1 and {police_structure.MAX_STATIONS}.")
        apply = opts["apply"]
        with transaction.atomic():
            lines = police_structure.apply(OrganizationalUnit, ServiceBranch, dry_run=not apply,
                                           stations_per_command=opts["stations_per_command"])
            if apply and ensure_types(AppointmentType):  # Chief of Police / Station Commander titles
                lines.append(("create_appointment_types", "CHIEF_OF_POLICE, STATION_COMMANDER"))
            if apply and any(a != "blocked" for a, _ in lines):
                record("org.police_structure_applied", entity_type="organization", metadata={"actions": [f"{a}: {d}" for a, d in lines][:50]})
        for action, detail in lines:
            self.stdout.write(f"{'APPLIED' if apply and action != 'blocked' else 'WOULD' if not apply else 'NOTE'} {action}: {detail}")
        if not lines:
            self.stdout.write("Police structure already matches. Nothing to do.")
        elif not apply:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to write these changes."))
