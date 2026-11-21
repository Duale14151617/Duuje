import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger


class Migration(migrations.Migration):
    dependencies = [("detention", "0001_initial"), ("organization", "0012_departments_and_formation_roles")]

    operations = [
        migrations.CreateModel(
            name="CustodyFacility",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=64, unique=True)),
                ("kind", models.CharField(choices=[("jail_center", "Jail center (army lock-up)"), ("prison", "Prison")], max_length=12)),
                ("name_en", models.CharField(max_length=150)),
                ("name_so", models.CharField(blank=True, max_length=150)),
                ("location", models.CharField(blank=True, max_length=200)),
                ("capacity", models.PositiveIntegerField(blank=True, null=True)),
                ("operated_by", models.CharField(blank=True, max_length=150)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("org_unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="custody_facilities", to="organization.organizationalunit")),
            ],
            options={"db_table": "custody_facilities", "ordering": ["kind", "name_en"]},
        ),
        migrations.AddConstraint(model_name="custodyfacility", constraint=models.CheckConstraint(condition=models.Q(("kind", "jail_center"), _negated=True) | models.Q(("org_unit__isnull", False)), name="facility_jail_has_station")),
        migrations.AddConstraint(model_name="custodyfacility", constraint=models.CheckConstraint(condition=models.Q(("kind", "prison"), _negated=True) | models.Q(("org_unit__isnull", True)), name="facility_prison_no_station")),
        migrations.AddField(model_name="detentionrecord", name="facility", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="records", to="detention.custodyfacility")),
        migrations.AddField(model_name="detentionrecord", name="destination_facility", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="received", to="detention.custodyfacility")),
        no_delete_trigger("custody_facilities"),
    ]
