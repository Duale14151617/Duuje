import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("weapons", "0003_soldier_rounds_store_link"),
        ("organization", "0006_station_level"),
    ]

    operations = [
        migrations.CreateModel(
            name="AmmoEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=150)),
                ("event_date", models.DateField()),
                ("status", models.CharField(choices=[("open", "Open"), ("closed", "Closed")], default="open", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("closed_by_username", models.CharField(blank=True, max_length=150)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
            ],
            options={"db_table": "ammo_events", "ordering": ["-event_date", "-created_at"]},
        ),
        migrations.AddField(
            model_name="soldierrounds",
            name="event",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="rounds", to="weapons.ammoevent"),
        ),
        migrations.AddField(
            model_name="soldierrounds",
            name="lot",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
