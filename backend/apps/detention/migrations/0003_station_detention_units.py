import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger


class Migration(migrations.Migration):
    dependencies = [("detention", "0002_custody_facilities"), ("organization", "0012_departments_and_formation_roles")]

    operations = [
        migrations.AddField(model_name="custodyfacility", name="status", field=models.CharField(
            choices=[("unverified", "Not verified"), ("operational", "Operational"), ("suspended", "Temporarily out of use"), ("closed", "Closed")],
            default="unverified", max_length=12)),
        migrations.AddField(model_name="custodyfacility", name="status_note", field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name="custodyfacility", name="status_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="custodyfacility", name="status_by_username", field=models.CharField(blank=True, max_length=150)),
        migrations.CreateModel(
            name="CustodyCell",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=30)),
                ("name", models.CharField(blank=True, max_length=100)),
                ("capacity", models.PositiveSmallIntegerField()),
                ("note", models.CharField(blank=True, max_length=200)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("facility", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cells", to="detention.custodyfacility")),
            ],
            options={"db_table": "custody_cells", "ordering": ["facility", "code"]},
        ),
        migrations.AddConstraint(model_name="custodycell", constraint=models.UniqueConstraint(fields=("facility", "code"), name="cell_unique_code_per_facility")),
        migrations.AddConstraint(model_name="custodycell", constraint=models.CheckConstraint(condition=models.Q(("capacity__gte", 1)), name="cell_capacity_positive")),
        migrations.AddField(model_name="detentionrecord", name="cell_ref", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="records", to="detention.custodycell")),
        migrations.AddField(model_name="detentionrecord", name="id_ref_key", field=models.CharField(blank=True, editable=False, max_length=80)),
        migrations.AddField(model_name="detentionrecord", name="last_review_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="detentionrecord", name="destination_unit", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="incoming_detentions", to="organization.organizationalunit")),
        migrations.AddField(model_name="detentionrecord", name="outcome_ref", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="detentionrecord", name="received_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="detentionrecord", name="transferred_from", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="received_as", to="detention.detentionrecord")),
        migrations.AlterField(model_name="detentionevent", name="kind", field=models.CharField(choices=[
            ("booked", "Booked in"), ("welfare", "Welfare check"), ("medical", "Medical"), ("visit", "Visit"), ("cell_move", "Moved cell"),
            ("property", "Property"), ("statement", "Statement / interview"), ("note", "Note"), ("review", "Custody review"),
            ("received", "Received from another station"), ("released", "Released"), ("transferred", "Transferred"),
            ("corrected", "Details corrected"), ("voided", "Voided")], max_length=12)),
        no_delete_trigger("custody_cells"),
    ]
