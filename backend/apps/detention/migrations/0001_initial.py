import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger, no_delete_trigger

STATUS = [("in_custody", "In custody"), ("released", "Released"), ("transferred", "Transferred"), ("void", "Void")]
SEX = [("male", "Male"), ("female", "Female"), ("unknown", "Not recorded")]
OUTCOME = [("no_charge", "Released without charge"), ("bail", "Released on bail / guarantee"), ("court_order", "Released on court order"),
           ("sentence_served", "Sentence served"), ("transfer_station", "Transferred to another station"),
           ("transfer_court", "Handed to the court"), ("transfer_prison", "Handed to the prison"), ("other", "Other")]
KIND = [("booked", "Booked in"), ("welfare", "Welfare check"), ("medical", "Medical"), ("visit", "Visit"), ("cell_move", "Moved cell"),
        ("property", "Property"), ("statement", "Statement / interview"), ("note", "Note"), ("released", "Released"),
        ("transferred", "Transferred"), ("corrected", "Details corrected"), ("voided", "Voided")]


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organization", "0012_departments_and_formation_roles"), ("personnel", "0012_strength_snapshot")]

    operations = [
        migrations.CreateModel(
            name="DetentionCounter",
            fields=[
                ("name", models.CharField(max_length=20, primary_key=True, serialize=False)),
                ("last", models.PositiveIntegerField(default=0)),
            ],
            options={"db_table": "detention_counters"},
        ),
        migrations.CreateModel(
            name="DetentionRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("register_no", models.CharField(max_length=20, unique=True)),
                ("detainee_name", models.CharField(max_length=200)),
                ("detainee_alias", models.CharField(blank=True, max_length=200)),
                ("sex", models.CharField(choices=SEX, default="unknown", max_length=8)),
                ("age_years", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("id_ref", models.CharField(blank=True, max_length=80)),
                ("address", models.CharField(blank=True, max_length=200)),
                ("booked_at", models.DateTimeField()),
                ("arrest_place", models.CharField(blank=True, max_length=200)),
                ("arresting_officer_name", models.CharField(blank=True, max_length=200)),
                ("reason", models.CharField(max_length=300)),
                ("authority_ref", models.CharField(blank=True, max_length=150)),
                ("cell", models.CharField(blank=True, max_length=60)),
                ("property_held", models.CharField(blank=True, max_length=500)),
                ("health_note", models.CharField(blank=True, max_length=300)),
                ("status", models.CharField(choices=STATUS, default="in_custody", max_length=12)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("outcome", models.CharField(blank=True, choices=OUTCOME, max_length=20)),
                ("destination", models.CharField(blank=True, max_length=200)),
                ("outcome_note", models.CharField(blank=True, max_length=300)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("ended_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("voided_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_reason", models.CharField(blank=True, max_length=300)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("arresting_officer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="detentions_made", to="personnel.personnel")),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="detention_records", to="organization.organizationalunit")),
            ],
            options={"db_table": "detention_records", "ordering": ["-booked_at"]},
        ),
        migrations.CreateModel(
            name="DetentionEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=KIND, max_length=12)),
                ("occurred_at", models.DateTimeField()),
                ("text", models.CharField(blank=True, max_length=500)),
                ("by_username", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("record", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="detention.detentionrecord")),
            ],
            options={"db_table": "detention_events", "ordering": ["occurred_at", "created_at"]},
        ),
        migrations.AddIndex(model_name="detentionrecord", index=models.Index(fields=["org_unit", "status", "-booked_at"], name="det_unit_status_idx")),
        migrations.AddIndex(model_name="detentionrecord", index=models.Index(fields=["status", "-booked_at"], name="det_status_idx")),
        migrations.AddConstraint(model_name="detentionrecord", constraint=models.CheckConstraint(condition=models.Q(("ended_at__isnull", True), ("ended_at__gte", models.F("booked_at")), _connector="OR"), name="det_end_after_booking")),
        migrations.AddIndex(model_name="detentionevent", index=models.Index(fields=["record", "occurred_at"], name="detevt_record_idx")),
        no_delete_trigger("detention_records"),
        append_only_trigger("detention_events"),
    ]
