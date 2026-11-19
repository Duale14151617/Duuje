"""Equipment Reference Catalogue: what a kind of equipment IS (name, classification, manufacturer, description, photographs,
specifications) and whether HQ has verified that description. It is reference data only.

* It never says the Army owns anything. Owned vehicles stay in the vehicle register (apps.vehicles) and owned weapons in the weapon
  register (apps.weapons); a vehicle only *points at* a catalogue entry (Vehicle.reference_model).
* Vehicle models are classified by the existing VehicleCategory (nothing is duplicated); mounted weapons by MountedWeaponCategory.
* Entries are switched off, never deleted. Changing the described facts of a verified entry puts it back to "unverified".
"""
import uuid

from django.db import models
from django.db.models import Q

from apps.core.appendonly import AppendOnlyError


class MountedWeaponCategory(models.Model):
    """Configurable classification of vehicle-mounted weapons (heavy machine guns, automatic cannons ...)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=100)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equipment_weapon_categories"
        ordering = ["sort_order", "code"]


class EquipmentItem(models.Model):
    class Kind(models.TextChoices):
        VEHICLE_MODEL = "vehicle_model"
        MOUNTED_WEAPON = "mounted_weapon"

    class Verification(models.TextChoices):
        UNVERIFIED = "unverified"      # entered, not yet checked against a source
        VERIFIED = "verified"          # checked by a second person holding equipment.verify
        NEEDS_REVIEW = "needs_review"  # a reviewer found something wrong; the note says what

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    vehicle_category = models.ForeignKey("vehicles.VehicleCategory", null=True, blank=True, on_delete=models.PROTECT, related_name="reference_models")
    weapon_category = models.ForeignKey(MountedWeaponCategory, null=True, blank=True, on_delete=models.PROTECT, related_name="items")
    description = models.CharField(max_length=1000, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    source_ref = models.CharField(max_length=300, blank=True)  # where the facts come from (manual, order, catalogue)
    verification = models.CharField(max_length=14, choices=Verification.choices, default=Verification.UNVERIFIED)
    verification_note = models.CharField(max_length=300, blank=True)
    verified_by_username = models.CharField(max_length=150, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "equipment_items"
        ordering = ["name"]
        indexes = [models.Index(fields=["kind", "active"], name="equip_kind_active_idx")]
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="vehicle_model", weapon_category__isnull=True) | Q(kind="mounted_weapon", vehicle_category__isnull=True)),
                name="equip_classification_matches_kind"),
            models.CheckConstraint(
                condition=Q(verification="verified", verified_at__isnull=False) | ~Q(verification="verified"),
                name="equip_verified_is_dated"),
        ]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Catalogue entries cannot be deleted; switch them off instead.")


class EquipmentSpec(models.Model):
    """One reference specification line (for example 'Crew' / '4'). The whole list of an entry is replaced in one audited step."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(EquipmentItem, on_delete=models.CASCADE, related_name="specs")
    name = models.CharField(max_length=60)
    value = models.CharField(max_length=200)
    unit = models.CharField(max_length=20, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "equipment_specs"
        ordering = ["sort_order", "name"]


class EquipmentPhoto(models.Model):
    """Reference photograph. Bytes encrypted at rest like vehicle documents; withdrawn, never deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(EquipmentItem, on_delete=models.PROTECT, related_name="photos")
    caption = models.CharField(max_length=150, blank=True)
    content_enc = models.BinaryField()
    content_type = models.CharField(max_length=20)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "equipment_photos"
        ordering = ["uploaded_at"]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Photographs are withdrawn, never deleted.")
