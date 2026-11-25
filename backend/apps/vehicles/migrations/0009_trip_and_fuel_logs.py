import importlib
import uuid

import django.db.models.deletion
from django.db import migrations, models

no_delete_trigger = importlib.import_module("apps.vehicles.migrations.0002_integrity_triggers").no_delete_trigger


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0008_police_vehicles_group"), ("personnel", "0008_attendance_support_category")]

    operations = [
        migrations.CreateModel(
            name="VehicleTrip",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("purpose", models.CharField(max_length=200)),
                ("origin", models.CharField(blank=True, max_length=150)),
                ("destination", models.CharField(blank=True, max_length=150)),
                ("authority_ref", models.CharField(blank=True, max_length=150)),
                ("started_at", models.DateTimeField()),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("start_odometer", models.PositiveIntegerField()),
                ("end_odometer", models.PositiveIntegerField(blank=True, null=True)),
                ("state", models.CharField(choices=[("open", "Open"), ("completed", "Completed"), ("void", "Void")], default="open", max_length=10)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("ended_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("voided_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_reason", models.CharField(blank=True, max_length=300)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("driver", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vehicle_trips", to="personnel.personnel")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="trips", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_trips", "ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="FuelEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("filled_on", models.DateField()),
                ("fuel_type", models.CharField(choices=[("diesel", "Diesel"), ("petrol", "Petrol"), ("other", "Other")], default="diesel", max_length=8)),
                ("litres", models.DecimalField(decimal_places=2, max_digits=8)),
                ("odometer", models.PositiveIntegerField()),
                ("full_tank", models.BooleanField(default=True)),
                ("cost", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("currency", models.CharField(blank=True, max_length=3)),
                ("station", models.CharField(blank=True, max_length=150)),
                ("receipt_ref", models.CharField(blank=True, max_length=150)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("voided_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_reason", models.CharField(blank=True, max_length=300)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("driver", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vehicle_fuel_entries", to="personnel.personnel")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="fuel_entries", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_fuel", "ordering": ["-filled_on", "-created_at"]},
        ),
        migrations.AddIndex(model_name="vehicletrip", index=models.Index(fields=["vehicle", "-started_at"], name="vehtrip_vehicle_idx")),
        migrations.AddConstraint(model_name="vehicletrip", constraint=models.UniqueConstraint(fields=["vehicle"], condition=models.Q(state="open"), name="vehtrip_one_open_per_vehicle")),
        migrations.AddConstraint(model_name="vehicletrip", constraint=models.CheckConstraint(condition=models.Q(("end_odometer__isnull", True), ("end_odometer__gte", models.F("start_odometer")), _connector="OR"), name="vehtrip_odometer_order")),
        migrations.AddIndex(model_name="fuelentry", index=models.Index(fields=["vehicle", "-filled_on"], name="vehfuel_vehicle_idx")),
        migrations.AddConstraint(model_name="fuelentry", constraint=models.CheckConstraint(condition=models.Q(litres__gt=0), name="vehfuel_litres_positive")),
        migrations.AddConstraint(model_name="fuelentry", constraint=models.CheckConstraint(condition=models.Q(("cost__isnull", True), ("cost__gte", 0), _connector="OR"), name="vehfuel_cost_nonneg")),
        no_delete_trigger("vehicle_trips"),
        no_delete_trigger("vehicle_fuel"),
    ]
