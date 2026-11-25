from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.services import record
from apps.vehicles import police_fleet
from apps.vehicles.models import Vehicle, VehicleCategory


class Command(BaseCommand):
    help = ("Create the Police vehicle types (Transport, Pickup, Tactical, Armored, Motorcycles, Prisoner Transport) under the main "
            "category Police Vehicles, and retire unused military-only categories. Safe to run again; without --apply it only reports.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (default is a dry run).")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        with transaction.atomic():
            lines = police_fleet.apply(VehicleCategory, Vehicle, dry_run=not apply)
            if apply and lines:
                record("vehicle.police_fleet_applied", entity_type="vehicle_category", metadata={"actions": [f"{a}: {d}" for a, d in lines][:50]})
        for action, detail in lines:
            self.stdout.write(f"{'APPLIED' if apply else 'WOULD'} {action}: {detail}")
        if not lines:
            self.stdout.write("Nothing to do: the Police vehicle types are already in place.")
        elif not apply:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to write these changes."))
