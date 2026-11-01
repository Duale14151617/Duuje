import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

U = settings.AUTH_USER_MODEL


class Migration(migrations.Migration):
    dependencies = [migrations.swappable_dependency(U), ("organization", "0003_puntland_army_structure")]

    operations = [
        migrations.CreateModel(name="StructureChange", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("title", models.CharField(max_length=150)),
            ("rationale", models.TextField(blank=True)),
            ("operations", models.JSONField(default=list)),
            ("impact", models.JSONField(blank=True, default=dict)),
            ("status", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="draft", max_length=10)),
            ("proposed_by_username", models.CharField(blank=True, max_length=150)),
            ("submitted_at", models.DateTimeField(blank=True, null=True)),
            ("decided_by_username", models.CharField(blank=True, max_length=150)),
            ("decided_at", models.DateTimeField(blank=True, null=True)),
            ("decision_note", models.CharField(blank=True, max_length=500)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("proposed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
        ], options={"db_table": "structure_changes", "ordering": ["-created_at", "id"]}),
    ]
