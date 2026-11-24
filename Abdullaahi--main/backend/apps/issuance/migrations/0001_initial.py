import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organization", "0015_remove_stray_draft_structure_change"),
        ("personnel", "0012_strength_snapshot"),
    ]
    operations = [
        migrations.CreateModel(
            name="IssuedDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("id_card", "Id Card"), ("letter", "Letter")], max_length=10)),
                ("code", models.CharField(editable=False, max_length=16, unique=True)),
                ("reference", models.CharField(editable=False, max_length=40)),
                ("subject", models.CharField(blank=True, max_length=200)),
                ("recipient", models.CharField(blank=True, max_length=200)),
                ("body", models.TextField(blank=True)),
                ("snapshot", models.JSONField(blank=True, default=dict)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("expires_on", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("valid", "Valid"), ("revoked", "Revoked")], default="valid", max_length=8)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_reason", models.CharField(blank=True, max_length=300)),
                ("issued_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
                ("personnel", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="personnel.personnel")),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "issued_documents", "ordering": ["-issued_at"]},
        ),
        migrations.AddIndex(model_name="issueddocument", index=models.Index(fields=["personnel", "kind", "status"], name="issued_person_kind_status")),
        migrations.AddIndex(model_name="issueddocument", index=models.Index(fields=["org_unit", "-issued_at"], name="issued_unit_date")),
    ]
