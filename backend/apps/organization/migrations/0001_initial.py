import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ServiceBranch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=32, unique=True)),
                ("name_en", models.CharField(max_length=100)),
                ("name_so", models.CharField(blank=True, max_length=100)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "service_branches", "ordering": ["name_en"]},
        ),
        migrations.CreateModel(
            name="OrganizationalUnit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name_en", models.CharField(max_length=150)),
                ("name_so", models.CharField(blank=True, max_length=150)),
                ("level", models.CharField(choices=[("headquarters", "Hq"), ("region", "Region"), ("branch_command", "Branch"), ("unit", "Unit")], max_length=20)),
                ("path", models.CharField(editable=False, max_length=1000)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="units", to="organization.servicebranch")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="organization.organizationalunit")),
            ],
            options={"db_table": "organizational_units", "ordering": ["path"]},
        ),
        migrations.AddIndex(
            model_name="organizationalunit",
            index=models.Index(fields=["path"], name="org_unit_path_idx", opclasses=["varchar_pattern_ops"]),
        ),
        migrations.AddConstraint(
            model_name="organizationalunit",
            constraint=models.UniqueConstraint(condition=Q(level="headquarters"), fields=("level",), name="org_single_hq"),
        ),
        migrations.AddConstraint(
            model_name="organizationalunit",
            constraint=models.CheckConstraint(
                condition=(Q(level="headquarters", parent__isnull=True) | (~Q(level="headquarters") & Q(parent__isnull=False))),
                name="org_parent_by_level",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationalunit",
            constraint=models.CheckConstraint(
                condition=~Q(level="branch_command") | Q(branch__isnull=False),
                name="org_branch_cmd_has_branch",
            ),
        ),
    ]
