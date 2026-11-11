"""Bring vehicles that were kept as generic logistics assets into the vehicle register.

Dry run by default: nothing is written without --apply. Safe to repeat: an asset already imported (Vehicle.legacy_asset) is skipped.
No values are invented. An asset carries a tag/serial, a unit and a status, so that is all that is imported: the tag goes into the
acquisition reference (it is not guessed to be a plate), the plate is recorded as "unknown", and make/model/driver stay empty.
Retired assets are not imported: decommissioning is a controlled, approved workflow and must not be bypassed by a bulk import.
Because a category is a choice, --vehicle-category is required.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.logistics.models import Asset
from apps.vehicles import services as svc
from apps.vehicles.models import Vehicle, VehicleCategory, VehicleEvent

STATUS_MAP = {"in_stock": "operational", "issued": "operational", "maintenance": "under_maintenance",
              "missing": "out_of_service", "lost": "out_of_service"}


class Command(BaseCommand):
    help = "Import logistics assets of one inventory category into the vehicle register (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--inventory-category", required=True, help="code of the logistics inventory category holding the vehicles")
        parser.add_argument("--vehicle-category", required=True, help="vehicle category code to give every imported vehicle, e.g. hilux_4x4")
        parser.add_argument("--apply", action="store_true", help="write the records (default is a dry run)")

    def handle(self, *args, inventory_category, vehicle_category, apply, **opts):
        cat = VehicleCategory.objects.filter(code=vehicle_category, active=True).first()
        if cat is None:
            raise CommandError(f"Unknown or inactive vehicle category: {vehicle_category}")
        assets = Asset.objects.filter(category__code=inventory_category).select_related("org_unit", "issued_to_unit")
        if not assets.exists():
            raise CommandError(f"No assets found in inventory category: {inventory_category}")
        done = skipped = retired = 0
        for a in assets.order_by("identifier"):
            if Vehicle.objects.filter(legacy_asset=a).exists():
                skipped += 1
                continue
            if a.status == "retired":
                retired += 1
                self.stdout.write(f"  not imported (retired, needs the disposal workflow): {a.identifier}")
                continue
            unit = a.issued_to_unit or a.org_unit
            self.stdout.write(f"  {'import' if apply else 'would import'}: {a.identifier} -> {unit.code} [{STATUS_MAP[a.status]}]")
            if not apply:
                done += 1
                continue
            with transaction.atomic():
                v = Vehicle.objects.create(
                    vehicle_id=svc._next_vehicle_id(), plate_status="unknown", category=cat, org_unit=unit, status=STATUS_MAP[a.status],
                    acquisition_ref=f"Legacy asset {a.identifier}"[:150], notes=(a.description or "")[:1000],
                    created_by_username="legacy-import", legacy_asset=a)
                VehicleEvent.objects.create(vehicle=v, kind="registered", after=svc.snapshot(v), authority_ref="legacy asset import",
                                            reason=f"Imported from logistics asset {a.identifier}", actor_username="legacy-import")
            done += 1
        self.stdout.write(self.style.SUCCESS(
            f"{'Imported' if apply else 'Would import'} {done}; already imported {skipped}; retired and left out {retired}."
            + ("" if apply else " Re-run with --apply to write.")))
