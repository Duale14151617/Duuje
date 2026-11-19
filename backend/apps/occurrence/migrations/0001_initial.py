import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger, no_delete_trigger

CATEGORY = [("complaint", "Complaint / report made"), ("arrest", "Arrest"), ("incident", "Incident"), ("accident", "Traffic accident"),
            ("theft_loss", "Theft / loss reported"), ("found_property", "Found property"), ("custody", "Custody (release / transfer)"),
            ("patrol", "Patrol / duty"), ("duty_change", "Change of duty officer"), ("visitor", "Visitor / enquiry"), ("other", "Other")]
KIND = [("update", "Update"), ("correction", "Correction"), ("outcome", "Outcome / closed"), ("voided", "Voided")]


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organization", "0012_departments_and_formation_roles"), ("detention", "0002_custody_facilities")]

    operations = [
        migrations.CreateModel(
            name="OccurrenceCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.PositiveSmallIntegerField()),
                ("last", models.PositiveIntegerField(default=0)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
            ],
            options={"db_table": "occurrence_counters"},
        ),
        migrations.AddConstraint(model_name="occurrencecounter", constraint=models.UniqueConstraint(fields=("org_unit", "year"), name="ob_counter_unit_year")),
        migrations.CreateModel(
            name="OccurrenceEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("ob_year", models.PositiveSmallIntegerField()),
                ("ob_seq", models.PositiveIntegerField()),
                ("ob_number", models.CharField(max_length=20)),
                ("category", models.CharField(choices=CATEGORY, max_length=16)),
                ("occurred_at", models.DateTimeField()),
                ("location", models.CharField(blank=True, max_length=200)),
                ("reported_by", models.CharField(blank=True, max_length=200)),
                ("summary", models.CharField(max_length=300)),
                ("details", models.TextField(blank=True, max_length=3000)),
                ("status", models.CharField(choices=[("recorded", "Recorded"), ("void", "Void")], default="recorded", max_length=10)),
                ("recorded_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("voided_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_reason", models.CharField(blank=True, max_length=300)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("detention_record", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="occurrence_entries", to="detention.detentionrecord")),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="occurrence_entries", to="organization.organizationalunit")),
            ],
            options={"db_table": "occurrence_entries", "ordering": ["-occurred_at", "-ob_seq"]},
        ),
        migrations.AddConstraint(model_name="occurrenceentry", constraint=models.UniqueConstraint(fields=("org_unit", "ob_year", "ob_seq"), name="ob_number_unique_per_station_year")),
        migrations.AddIndex(model_name="occurrenceentry", index=models.Index(fields=["org_unit", "-occurred_at"], name="ob_unit_time_idx")),
        migrations.AddIndex(model_name="occurrenceentry", index=models.Index(fields=["category", "-occurred_at"], name="ob_cat_time_idx")),
        migrations.CreateModel(
            name="OccurrenceFollowUp",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=KIND, max_length=10)),
                ("occurred_at", models.DateTimeField()),
                ("text", models.CharField(max_length=500)),
                ("by_username", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("entry", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="follow_ups", to="occurrence.occurrenceentry")),
            ],
            options={"db_table": "occurrence_follow_ups", "ordering": ["occurred_at", "created_at"]},
        ),
        no_delete_trigger("occurrence_entries"),
        append_only_trigger("occurrence_follow_ups"),
    ]
