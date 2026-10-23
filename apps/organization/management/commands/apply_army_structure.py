from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.services import record
from apps.organization import army_structure
from apps.organization.models import OrganizationalUnit, ServiceBranch, UnitType
from apps.personnel.models import Personnel


class Command(BaseCommand):
    help = ("Apply the Army organizational structure supplied by army personnel (Taliska Guud with directorates, the four "
            "regional commands, Guuto and Urur units for Bari and Sanaag, Urur office types). Army only. Dry run by default; pass --apply to write. Idempotent.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (default is a dry run).")
        parser.add_argument("--guuto-per-command", type=int, default=army_structure.DEFAULT_GUUTO_PER_COMMAND,
                            help="Guuto (brigades) in each of Bari and Sanaag. Raise it later to add more; nothing is ever removed.")
        parser.add_argument("--urur-per-guuto", type=int, default=army_structure.DEFAULT_URUR_PER_GUUTO,
                            help="Urur (battalions) in each Guuto. Raise it later to add more; nothing is ever removed.")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        for name in ("guuto_per_command", "urur_per_guuto"):
            if not 1 <= opts[name] <= army_structure.MAX_PER_PARENT:
                raise CommandError(f"--{name.replace('_', '-')} must be between 1 and {army_structure.MAX_PER_PARENT}.")
        with transaction.atomic():
            lines = army_structure.apply(OrganizationalUnit, UnitType, ServiceBranch, Personnel, dry_run=not apply,
                                         guuto_per_command=opts["guuto_per_command"], urur_per_guuto=opts["urur_per_guuto"])
            if apply and any(a != "blocked" for a, _ in lines):
                record("org.army_structure_applied", entity_type="organization",
                       metadata={"actions": [f"{a}: {d}" for a, d in lines][:50]})
        for action, detail in lines:
            self.stdout.write(f"{'APPLIED' if apply and action != 'blocked' else 'WOULD' if not apply else 'NOTE'} {action}: {detail}")
        if not lines:
            self.stdout.write("Army structure already matches. Nothing to do.")
        elif not apply:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to write these changes."))
