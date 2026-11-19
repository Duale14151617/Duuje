from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.detention import facilities
from apps.organization.management.commands.seed_police_sample import _sample_mode_allowed


class Command(BaseCommand):
    help = ("DEMONSTRATION ONLY: mark every station's not-yet-verified jail center operational, create three sample cells in each and place "
            "everyone in custody who has no cell. Records say they were pre-approved and not verified on site. Safe to run again. "
            "Needs POLICEHQ_SAMPLE_MODE=1, or --confirm-not-field-verified if you really want it on a non-sample system.")

    def add_arguments(self, parser):
        parser.add_argument("--confirm-not-field-verified", action="store_true",
                            help="Allow this on a non-sample deployment (the jails are still recorded as not verified on site)")

    def handle(self, *args, **opts):
        if not (_sample_mode_allowed() or opts["confirm_not_field_verified"]):
            raise CommandError("Set POLICEHQ_SAMPLE_MODE=1 (sample deployment), or pass --confirm-not-field-verified.")
        with transaction.atomic():
            v, c, p = facilities.preapprove_demo()
        self.stdout.write(self.style.SUCCESS(f"{v} jail centers pre-approved, {c} cells created, {p} detainees placed in cells (a second run adds nothing)."))
