import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organization", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("username", models.CharField(max_length=64, unique=True)),
                ("full_name", models.CharField(max_length=150)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("preferred_language", models.CharField(choices=[("en", "English"), ("so", "Soomaali")], default="en", max_length=2)),
                ("is_active", models.BooleanField(default=True)),
                ("must_change_password", models.BooleanField(default=False)),
                ("mfa_enabled", models.BooleanField(default=False)),
                ("mfa_secret_enc", models.TextField(blank=True)),
                ("auth_epoch", models.PositiveIntegerField(default=1)),
                ("failed_login_count", models.PositiveSmallIntegerField(default=0)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "users", "ordering": ["username"]},
        ),
        migrations.CreateModel(
            name="Permission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=64, unique=True)),
                ("description", models.CharField(blank=True, max_length=200)),
            ],
            options={"db_table": "permissions", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=48, unique=True)),
                ("name_en", models.CharField(max_length=100)),
                ("name_so", models.CharField(blank=True, max_length=100)),
                ("is_privileged", models.BooleanField(default=False)),
                ("requires_branch", models.BooleanField(default=False)),
                ("allowed_scope_levels", models.JSONField(blank=True, default=list)),
                ("permissions", models.ManyToManyField(db_table="role_permissions", related_name="roles", to="accounts.permission")),
            ],
            options={"db_table": "roles", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="RoleAssignment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("valid_from", models.DateField(blank=True, null=True)),
                ("valid_until", models.DateField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("branch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.servicebranch")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
                ("role", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assignments", to="accounts.role")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "user_role_assignments", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="roleassignment",
            constraint=models.CheckConstraint(
                condition=Q(valid_from__isnull=True) | Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="assignment_valid_range",
            ),
        ),
    ]
