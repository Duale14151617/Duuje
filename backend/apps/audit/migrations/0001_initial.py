import uuid

import django.utils.timezone
from django.db import migrations, models



class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("actor_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("actor_username", models.CharField(blank=True, max_length=150)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("entity_type", models.CharField(blank=True, max_length=64)),
                ("entity_id", models.CharField(blank=True, max_length=64)),
                ("outcome", models.CharField(choices=[("success", "Success"), ("failure", "Failure"), ("denied", "Denied")], max_length=16)),
                ("correlation_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={"db_table": "audit_events", "ordering": ["-occurred_at"]},
        ),
        migrations.AddIndex(
            model_name="auditevent",
            index=models.Index(fields=["entity_type", "entity_id"], name="audit_entity_idx"),
        ),
    ]
