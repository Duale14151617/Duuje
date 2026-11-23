import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0011_position_archives")]

    operations = [
        migrations.CreateModel(
            name="Geofence",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100)),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("radius_m", models.PositiveIntegerField()),
                ("alert_on", models.CharField(choices=[("enter", "Entering"), ("exit", "Leaving"), ("both", "Entering and leaving")], default="both", max_length=5)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "vehicle_geofences", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="geofence",
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower("name"), name="vehicle_geofence_name_ci_unique"),
        ),
        migrations.CreateModel(
            name="GeofenceState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("inside", models.BooleanField()),
                ("as_of", models.DateTimeField()),
                ("geofence", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="states", to="vehicles.geofence")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="geofence_states", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_geofence_states"},
        ),
        migrations.AddConstraint(
            model_name="geofencestate",
            constraint=models.UniqueConstraint(fields=("geofence", "vehicle"), name="vehicle_geofence_state_unique"),
        ),
        migrations.CreateModel(
            name="GeofenceEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("enter", "Entered"), ("exit", "Left")], max_length=5)),
                ("occurred_at", models.DateTimeField()),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("position_id", models.UUIDField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("geofence", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="vehicles.geofence")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="geofence_events", to="vehicles.vehicle")),
            ],
            options={"db_table": "vehicle_geofence_events", "ordering": ["-occurred_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="geofenceevent",
            index=models.Index(fields=["vehicle", "-occurred_at"], name="veh_gfevent_vehicle_idx"),
        ),
        migrations.AddIndex(
            model_name="geofenceevent",
            index=models.Index(fields=["occurred_at"], name="veh_gfevent_time_idx"),
        ),
        append_only_trigger("vehicle_geofence_events"),
    ]
