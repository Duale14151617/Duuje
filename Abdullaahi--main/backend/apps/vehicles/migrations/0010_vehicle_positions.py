import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0009_trip_and_fuel_logs")]

    operations = [
        migrations.CreateModel(
            name="VehiclePosition",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("accuracy_m", models.PositiveIntegerField(blank=True, null=True)),
                ("place", models.CharField(blank=True, max_length=150)),
                ("source", models.CharField(choices=[("manual", "Typed in"), ("phone", "Phone location"), ("tracker", "Vehicle tracker")], default="manual", max_length=8)),
                ("recorded_at", models.DateTimeField()),
                ("note", models.CharField(blank=True, max_length=200)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("voided_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_reason", models.CharField(blank=True, max_length=300)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("trip", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="positions", to="vehicles.vehicletrip")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="positions", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_positions", "ordering": ["-recorded_at"]},
        ),
        migrations.AddIndex(model_name="vehicleposition", index=models.Index(fields=["vehicle", "-recorded_at"], name="vehpos_vehicle_idx")),
        migrations.AddConstraint(model_name="vehicleposition", constraint=models.CheckConstraint(condition=models.Q(("latitude__gte", -90), ("latitude__lte", 90), ("longitude__gte", -180), ("longitude__lte", 180)), name="vehpos_valid_coordinates")),
        migrations.CreateModel(
            name="VehicleTracker",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("device_ref", models.CharField(max_length=60)),
                ("key_prefix", models.CharField(editable=False, max_length=8, unique=True)),
                ("key_hash", models.CharField(editable=False, max_length=64)),
                ("active", models.BooleanField(default=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("switched_off_at", models.DateTimeField(blank=True, null=True)),
                ("switched_off_by_username", models.CharField(blank=True, max_length=150)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="trackers", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_trackers", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(model_name="vehicletracker", constraint=models.UniqueConstraint(condition=models.Q(("active", True)), fields=("device_ref",), name="vehtracker_one_active_per_device")),
        no_delete_trigger("vehicle_positions"),
        no_delete_trigger("vehicle_trackers"),
    ]
