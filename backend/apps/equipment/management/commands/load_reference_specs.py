"""Fill the Equipment Reference Catalogue with published, sourced specifications (see apps/equipment/reference_specs.py).

Dry run by default; add --apply to write. Safe to run twice: it only fills entries that have no specifications yet, never overwrites
an edit, never marks anything verified, and writes one audit event per entry it changes."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.services import record
from apps.equipment.models import EquipmentItem, EquipmentSpec, MountedWeaponCategory
from apps.equipment.reference import seed_catalogue
from apps.equipment.reference_specs import EXTRA_WEAPON_CATEGORIES, PLACEHOLDER_SOURCE, SPECS, WEAPONS
from apps.vehicles.models import VehicleCategory


def _rows(item, specs):
    return [EquipmentSpec(item=item, name=n, value=v, unit=u, sort_order=i) for i, (n, v, u) in enumerate(specs)]


class Command(BaseCommand):
    help = "Load sourced specifications and mounted-weapon reference entries into the Equipment Reference Catalogue."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="write the changes (default: only report them)")

    def handle(self, *args, apply=False, **opts):
        done = skipped = missing = 0
        with transaction.atomic():
            seed_catalogue(VehicleCategory, MountedWeaponCategory, EquipmentItem)  # makes sure categories and base entries exist
            for code, en, order in EXTRA_WEAPON_CATEGORIES:
                MountedWeaponCategory.objects.get_or_create(code=code, defaults={"name_en": en, "sort_order": order})
            for code, (source, specs) in SPECS.items():
                item = EquipmentItem.objects.filter(code=code).first()
                if item is None:
                    missing += 1
                    self.stdout.write(f"  not in the catalogue, skipped: {code}")
                    continue
                if item.specs.exists():
                    skipped += 1
                    self.stdout.write(f"  already has specifications, left alone: {code}")
                    continue
                self.stdout.write(f"  {'fill' if apply else 'would fill'}: {item.name} ({len(specs)} lines)")
                if apply:
                    EquipmentSpec.objects.bulk_create(_rows(item, specs))
                    if not item.source_ref or item.source_ref.startswith(PLACEHOLDER_SOURCE):
                        item.source_ref = source[:300]
                    item.version += 1
                    item.save()
                    record("equipment.reference_loaded", entity_type="equipment_item", entity_id=item.pk, metadata={"source": source, "lines": len(specs)})
                done += 1
            for code, name, wcat, maker, desc, source, specs in WEAPONS:
                if EquipmentItem.objects.filter(code=code).exists():
                    skipped += 1
                    self.stdout.write(f"  already in the catalogue, left alone: {code}")
                    continue
                cat = MountedWeaponCategory.objects.filter(code=wcat).first()
                if cat is None:
                    missing += 1
                    self.stdout.write(f"  weapon category missing, skipped: {code}")
                    continue
                self.stdout.write(f"  {'add' if apply else 'would add'}: {name} ({len(specs)} lines)")
                if apply:
                    item = EquipmentItem.objects.create(code=code, name=name, kind="mounted_weapon", weapon_category=cat, manufacturer=maker,
                                                        description=desc, source_ref=source[:300], created_by_username="reference-load")
                    EquipmentSpec.objects.bulk_create(_rows(item, specs))
                    record("equipment.reference_loaded", entity_type="equipment_item", entity_id=item.pk, metadata={"source": source, "lines": len(specs), "created": True})
                done += 1
            if not apply:
                transaction.set_rollback(True)  # seed_catalogue may have created base rows; a dry run must leave nothing behind
        self.stdout.write(self.style.SUCCESS(
            f"{'Loaded' if apply else 'Would load'} {done}; left alone {skipped}; not found {missing}."
            + ("" if apply else " Re-run with --apply to write.")))
