import django.db.models.deletion
from django.db import migrations, models

# Existing standard appointment types keep working as before; they are only classed so unit profiles can tell commander from deputy.
ROLE_BY_CODE = {"TALIYE_QAYBEED": "commander", "TALIYE_GUUTO": "commander", "TALIYE_URUR": "commander", "ABAANDUULE": "deputy"}


def class_existing_types(apps, schema_editor):
    AppointmentType = apps.get_model("personnel", "AppointmentType")
    for code, role in ROLE_BY_CODE.items():
        AppointmentType.objects.filter(code=code, role="other").update(role=role)


class Migration(migrations.Migration):
    """Personnel gain an optional department; appointment types gain a role; appointments may name a department (head or
    deputy of a department). Additive: existing personnel keep department empty, existing appointments keep their meaning."""

    dependencies = [
        ("organization", "0012_departments_and_formation_roles"),
        ("personnel", "0010_scale_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="personnel", name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="personnel", to="organization.department"),
        ),
        migrations.AddIndex(model_name="personnel",
                            index=models.Index(fields=["org_unit", "department"], name="personnel_unit_dept")),
        migrations.AlterField(
            model_name="personnelhistory", name="field",
            field=models.CharField(choices=[("rank", "Rank"), ("org_unit", "Org Unit"), ("status", "Status"),
                                            ("department", "Department")], max_length=10),
        ),
        migrations.AddField(
            model_name="appointmenttype", name="role",
            field=models.CharField(choices=[
                ("commander", "Commander"), ("deputy", "Deputy commander"), ("administrative", "Administrative leadership"),
                ("department_head", "Head of department"), ("department_deputy", "Deputy head of department"),
                ("other", "Other")], default="other", max_length=20),
        ),
        migrations.AddField(
            model_name="commandappointment", name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                    to="organization.department"),
        ),
        migrations.RemoveConstraint(model_name="commandappointment", name="appointment_one_open_exclusive"),
        migrations.AddConstraint(
            model_name="commandappointment",
            constraint=models.UniqueConstraint(fields=("org_unit", "appointment_type"), name="appointment_one_open_exclusive",
                                               condition=models.Q(ended_at__isnull=True, exclusive=True, department__isnull=True)),
        ),
        migrations.AddConstraint(
            model_name="commandappointment",
            constraint=models.UniqueConstraint(fields=("org_unit", "appointment_type", "department"),
                                               name="appointment_one_open_exclusive_dept",
                                               condition=models.Q(ended_at__isnull=True, exclusive=True, department__isnull=False)),
        ),
        migrations.RunPython(class_existing_types, migrations.RunPython.noop),
    ]
