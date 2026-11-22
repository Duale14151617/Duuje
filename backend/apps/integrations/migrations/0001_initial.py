import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

U = settings.AUTH_USER_MODEL


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(U), ("organization", "0003_puntland_army_structure")]

    operations = [
        migrations.CreateModel(name="IntegrationClient", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("name", models.CharField(max_length=120)),
            ("description", models.CharField(blank=True, max_length=300)),
            ("key_prefix", models.CharField(max_length=12, unique=True)),
            ("key_hash", models.CharField(editable=False, max_length=64)),
            ("scopes", models.JSONField(default=list)),
            ("expires_at", models.DateTimeField()),
            ("active", models.BooleanField(default=True)),
            ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ("created_by_username", models.CharField(blank=True, max_length=150)),
            ("last_used_at", models.DateTimeField(blank=True, null=True)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
        ], options={"db_table": "integration_clients", "ordering": ["name", "id"]}),
        migrations.CreateModel(name="IntegrationCall", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("at", models.DateTimeField(default=django.utils.timezone.now)),
            ("endpoint", models.CharField(max_length=64)),
            ("status_code", models.PositiveSmallIntegerField()),
            ("outcome", models.CharField(choices=[("success", "Success"), ("denied", "Denied"), ("throttled", "Throttled"), ("error", "Error")], max_length=10)),
            ("correlation_id", models.CharField(blank=True, max_length=64)),
            ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
            ("client", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="calls", to="integrations.integrationclient")),
        ], options={"db_table": "integration_calls", "ordering": ["-at", "-id"]}),
        migrations.AddIndex(model_name="integrationcall", index=models.Index(fields=["client", "-at"], name="intcall_client_at_idx")),
    ]
