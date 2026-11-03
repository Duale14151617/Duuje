"""Vehicles point at the Equipment Reference Catalogue, gain specifications and mounted armament, and a 'photograph' document
category. Existing vehicles keep every value they have; the new link starts empty (nothing is guessed)."""
import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger

EVENT_KINDS = [("registered", "Registered"), ("updated", "Updated"), ("unit_transfer", "Unit Transfer"), ("driver_change", "Driver Change"),
               ("custodian_change", "Custodian Change"), ("status_change", "Status Change"), ("location_change", "Location Change"),
               ("maintenance", "Maintenance"), ("disposal_proposed", "Disposal Proposed"), ("disposal_rejected", "Disposal Rejected"),
               ("decommissioned", "Decommissioned"), ("document", "Document"), ("specification", "Specification"), ("armament", "Armament")]
DOC_CATEGORIES = [("registration", "Registration"), ("service_report", "Service Report"), ("receipt", "Receipt"), ("handover", "Handover"),
                  ("inspection", "Inspection"), ("photograph", "Photograph"), ("other", "Other")]
GROUPS = [("utility", "Utility"), ("personnel_transport", "Personnel Transport"), ("general_transport", "General Transport"),
          ("protected_transport", "Protected Transport"), ("combat_vehicle", "Combat Vehicle"), ("other", "Other")]


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0001_initial"),
        ("logistics", "0006_asset_lifecycle"),
        ("vehicles", "0006_vehicle_ownership"),
    ]

    operations = [
        migrations.AlterField(model_name="vehiclecategory", name="group", field=models.CharField(choices=GROUPS, default="other", max_length=24)),
        migrations.AlterField(model_name="vehicleevent", name="kind", field=models.CharField(choices=EVENT_KINDS, max_length=20)),
        migrations.AlterField(model_name="vehicledocument", name="category", field=models.CharField(choices=DOC_CATEGORIES, max_length=16)),
        migrations.AddField(
            model_name="vehicle", name="reference_model",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vehicles", to="equipment.equipmentitem")),
        migrations.CreateModel(
            name="VehicleSpecification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=60)),
                ("value", models.CharField(max_length=200)),
                ("unit", models.CharField(blank=True, max_length=20)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="specs", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_specs", "ordering": ["sort_order", "name"]},
        ),
        migrations.CreateModel(
            name="VehicleArmament",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("mount_position", models.CharField(blank=True, max_length=80)),
                ("notes", models.CharField(blank=True, max_length=300)),
                ("added_by_username", models.CharField(blank=True, max_length=150)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("removed_at", models.DateTimeField(blank=True, null=True)),
                ("removed_by_username", models.CharField(blank=True, max_length=150)),
                ("removed_reason", models.CharField(blank=True, max_length=300)),
                ("asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vehicle_mounts", to="logistics.asset")),
                ("reference_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="mounts", to="equipment.equipmentitem")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="armament", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_armament", "ordering": ["added_at"]},
        ),
        migrations.AddConstraint(
            model_name="vehiclearmament",
            constraint=models.UniqueConstraint(condition=models.Q(("asset__isnull", False), ("removed_at__isnull", True)), fields=("asset",), name="vehicle_armament_asset_one_mount")),
        no_delete_trigger("vehicle_armament"),
    ]
