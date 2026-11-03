"""Equipment Reference Catalogue: mounted-weapon categories, catalogue entries, reference specifications and photographs."""
import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger


class Migration(migrations.Migration):
    initial = True

    dependencies = [("vehicles", "0006_vehicle_ownership")]

    operations = [
        migrations.CreateModel(
            name="MountedWeaponCategory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name_en", models.CharField(max_length=120)),
                ("name_so", models.CharField(blank=True, max_length=120)),
                ("sort_order", models.PositiveSmallIntegerField(default=100)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "equipment_weapon_categories", "ordering": ["sort_order", "code"]},
        ),
        migrations.CreateModel(
            name="EquipmentItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=60, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("kind", models.CharField(choices=[("vehicle_model", "Vehicle Model"), ("mounted_weapon", "Mounted Weapon")], max_length=16)),
                ("description", models.CharField(blank=True, max_length=1000)),
                ("manufacturer", models.CharField(blank=True, max_length=120)),
                ("source_ref", models.CharField(blank=True, max_length=300)),
                ("verification", models.CharField(choices=[("unverified", "Unverified"), ("verified", "Verified"), ("needs_review", "Needs Review")], default="unverified", max_length=14)),
                ("verification_note", models.CharField(blank=True, max_length=300)),
                ("verified_by_username", models.CharField(blank=True, max_length=150)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("active", models.BooleanField(default=True)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("vehicle_category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reference_models", to="vehicles.vehiclecategory")),
                ("weapon_category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="items", to="equipment.mountedweaponcategory")),
            ],
            options={"db_table": "equipment_items", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="EquipmentSpec",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=60)),
                ("value", models.CharField(max_length=200)),
                ("unit", models.CharField(blank=True, max_length=20)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="specs", to="equipment.equipmentitem")),
            ],
            options={"db_table": "equipment_specs", "ordering": ["sort_order", "name"]},
        ),
        migrations.CreateModel(
            name="EquipmentPhoto",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("caption", models.CharField(blank=True, max_length=150)),
                ("content_enc", models.BinaryField()),
                ("content_type", models.CharField(max_length=20)),
                ("size_bytes", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("uploaded_by_username", models.CharField(blank=True, max_length=150)),
                ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                ("withdrawn_by_username", models.CharField(blank=True, max_length=150)),
                ("withdrawn_reason", models.CharField(blank=True, max_length=300)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="photos", to="equipment.equipmentitem")),
            ],
            options={"db_table": "equipment_photos", "ordering": ["uploaded_at"]},
        ),
        migrations.AddIndex(model_name="equipmentitem", index=models.Index(fields=["kind", "active"], name="equip_kind_active_idx")),
        migrations.AddConstraint(
            model_name="equipmentitem",
            constraint=models.CheckConstraint(
                condition=models.Q(models.Q(("kind", "vehicle_model"), ("weapon_category__isnull", True)), models.Q(("kind", "mounted_weapon"), ("vehicle_category__isnull", True)), _connector="OR"),
                name="equip_classification_matches_kind"),
        ),
        migrations.AddConstraint(
            model_name="equipmentitem",
            constraint=models.CheckConstraint(
                condition=models.Q(models.Q(("verification", "verified"), ("verified_at__isnull", False)), models.Q(("verification", "verified"), _negated=True), _connector="OR"),
                name="equip_verified_is_dated"),
        ),
        no_delete_trigger("equipment_items"),
        no_delete_trigger("equipment_photos"),
    ]
