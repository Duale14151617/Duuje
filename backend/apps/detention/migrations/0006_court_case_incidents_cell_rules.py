import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger

OUTCOMES = [("no_charge", "Released without charge"), ("bail", "Released on bail / guarantee"), ("court_order", "Released on court order"),
            ("sentence_served", "Sentence served"), ("transfer_station", "Transferred to another station"), ("transfer_court", "Handed to the court"),
            ("transfer_prison", "Handed to the prison"), ("died_in_custody", "Died in custody"), ("other", "Other")]
KINDS = [("booked", "Booked in"), ("welfare", "Welfare check"), ("medical", "Medical"), ("visit", "Visit"), ("cell_move", "Moved cell"),
         ("property", "Property"), ("statement", "Statement / interview"), ("note", "Note"), ("review", "Custody review"), ("court", "Court"),
         ("charge", "Charge recorded"), ("incident", "Custody incident"), ("received", "Received from another station"),
         ("released", "Released"), ("transferred", "Transferred"), ("corrected", "Details corrected"), ("voided", "Voided")]


class Migration(migrations.Migration):
    dependencies = [("detention", "0005_facility_last_editor"), ("organization", "0012_departments_and_formation_roles")]

    operations = [
        migrations.AddField(model_name="custodycell", name="reserved_for", field=models.CharField(
            choices=[("any", "Anyone"), ("women", "Women only"), ("juveniles", "Juveniles only"), ("men", "Adult men only")], default="any", max_length=10)),
        migrations.AlterField(model_name="custodycell", name="note", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="detentionrecord", name="case_ref", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="detentionrecord", name="charge", field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name="detentionrecord", name="charged_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="detentionrecord", name="charged_by_username", field=models.CharField(blank=True, max_length=150)),
        migrations.AlterField(model_name="detentionrecord", name="outcome", field=models.CharField(blank=True, choices=OUTCOMES, max_length=20)),
        migrations.AlterField(model_name="detentionevent", name="kind", field=models.CharField(choices=KINDS, max_length=12)),
        migrations.CreateModel(
            name="CourtHearing",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("purpose", models.CharField(choices=[("hearing", "Court hearing"), ("remand", "Remand order"), ("bail", "Bail hearing"), ("sentencing", "Sentencing"), ("other", "Other")], default="hearing", max_length=12)),
                ("hearing_at", models.DateTimeField(blank=True, null=True)),
                ("court", models.CharField(blank=True, max_length=200)),
                ("ordered_by", models.CharField(blank=True, max_length=200)),
                ("order_ref", models.CharField(blank=True, max_length=150)),
                ("remand_until", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("scheduled", "Scheduled"), ("held", "Held"), ("adjourned", "Adjourned"), ("cancelled", "Cancelled")], default="scheduled", max_length=10)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("record", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="hearings", to="detention.detentionrecord")),
            ],
            options={"db_table": "detention_hearings", "ordering": ["hearing_at", "created_at"]},
        ),
        migrations.AddIndex(model_name="courthearing", index=models.Index(fields=["record", "hearing_at"], name="dethear_record_idx")),
        migrations.CreateModel(
            name="CustodyIncident",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("death", "Death in custody"), ("injury", "Injury"), ("use_of_force", "Use of force")], max_length=12)),
                ("occurred_at", models.DateTimeField()),
                ("place", models.CharField(blank=True, max_length=200)),
                ("description", models.CharField(max_length=1000)),
                ("people_involved", models.CharField(blank=True, max_length=300)),
                ("medical_attended", models.BooleanField(default=False)),
                ("medical_note", models.CharField(blank=True, max_length=300)),
                ("reported_by_username", models.CharField(blank=True, max_length=150)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_by_username", models.CharField(blank=True, max_length=150)),
                ("review_note", models.CharField(blank=True, max_length=500)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="custody_incidents", to="organization.organizationalunit")),
                ("record", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incidents", to="detention.detentionrecord")),
            ],
            options={"db_table": "custody_incidents", "ordering": ["-occurred_at"]},
        ),
        migrations.AddIndex(model_name="custodyincident", index=models.Index(fields=["org_unit", "-occurred_at"], name="custinc_unit_idx")),
        no_delete_trigger("detention_hearings"),
        no_delete_trigger("custody_incidents"),
    ]
