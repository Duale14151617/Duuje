import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Organizational structure upgrade. Adds a formation role to unit types, a department catalogue and the departments each
    unit has established. Additive only: no existing row is changed except that the standard Army types are tagged with their
    formation role (blank elsewhere), and no people or posts are created."""

    dependencies = [("organization", "0011_remove_station_level")]

    operations = [
        migrations.AddField(
            model_name="unittype", name="formation_role",
            field=models.CharField(blank=True, choices=[
                ("ghq", "General Headquarters"), ("regional", "Regional command"), ("brigade", "Brigade"),
                ("battalion", "Battalion")], default="", max_length=10),
        ),
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=32, unique=True)),
                ("name_en", models.CharField(max_length=100)),
                ("name_so", models.CharField(blank=True, max_length=100)),
                ("description_en", models.CharField(blank=True, max_length=200)),
                ("description_so", models.CharField(blank=True, max_length=200)),
                ("restricted_roster", models.BooleanField(default=False)),
                ("sort_order", models.PositiveSmallIntegerField(default=100)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "departments", "ordering": ["sort_order", "code"]},
        ),
        migrations.CreateModel(
            name="UnitDepartment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("note", models.CharField(blank=True, max_length=200)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="unit_departments",
                                                 to="organization.department")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="unit_departments",
                                           to="organization.organizationalunit")),
            ],
            options={"db_table": "unit_departments", "ordering": ["department__sort_order", "department__code"]},
        ),
        migrations.AddConstraint(
            model_name="unitdepartment",
            constraint=models.UniqueConstraint(fields=("unit", "department"), name="unit_department_unique"),
        ),
    ]
