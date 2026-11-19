import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger


class Migration(migrations.Migration):
    dependencies = [("organization", "0012_departments_and_formation_roles"), ("detention", "0007_offline_client_refs")]

    operations = [
        migrations.CreateModel(
            name="ShiftHandover",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("shift_ended_at", models.DateTimeField()),
                ("custody_snapshot", models.JSONField(default=list)),
                ("custody_note", models.CharField(blank=True, max_length=1000)),
                ("pending", models.CharField(max_length=2000)),
                ("watch", models.CharField(max_length=2000)),
                ("written_by_username", models.CharField(max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="shift_handovers", to="organization.organizationalunit")),
            ],
            options={"db_table": "shift_handovers", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="shifthandover", index=models.Index(fields=["org_unit", "-created_at"], name="handover_unit_idx")),
        migrations.CreateModel(
            name="ShiftHandoverAck",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("acknowledged_by_username", models.CharField(max_length=150)),
                ("acknowledged_at", models.DateTimeField(auto_now_add=True)),
                ("comment", models.CharField(blank=True, max_length=300)),
                ("handover", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="ack", to="detention.shifthandover")),
            ],
            options={"db_table": "shift_handover_acks"},
        ),
        append_only_trigger("shift_handovers"),
        append_only_trigger("shift_handover_acks"),
    ]
