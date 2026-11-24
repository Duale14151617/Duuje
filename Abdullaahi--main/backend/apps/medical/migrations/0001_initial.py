import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger


class Migration(migrations.Migration):
    initial = True

    dependencies = [("personnel", "0008_attendance_support_category")]

    operations = [
        migrations.CreateModel(
            name="MedicalEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("fitness_status", models.CharField(choices=[("fit", "Fit"), ("limited", "Limited"), ("unfit", "Unfit"), ("under_review", "Under review")], max_length=12)),
                ("review_due", models.DateField(blank=True, null=True)),
                ("restriction_enc", models.TextField(blank=True)),
                ("details_enc", models.TextField(blank=True)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("recorded_by_id", models.UUIDField(blank=True, null=True)),
                ("recorded_by_username", models.CharField(blank=True, max_length=150)),
                ("corrects", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="corrections", to="medical.medicalentry")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="medical_entries", to="personnel.personnel")),
            ],
            options={"db_table": "medical_entries", "ordering": ["-recorded_at", "-id"]},
        ),
        migrations.AddIndex(model_name="medicalentry", index=models.Index(fields=["personnel", "-recorded_at"], name="medical_person_idx")),
        append_only_trigger("medical_entries"),
    ]
