import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("personnel", "0001_initial")]

    operations = [
        migrations.CreateModel(name="Course", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("code", models.CharField(max_length=48, unique=True)),
            ("name_en", models.CharField(max_length=150)),
            ("name_so", models.CharField(blank=True, max_length=150)),
            ("duration_days", models.PositiveSmallIntegerField(blank=True, null=True)),
            ("active", models.BooleanField(default=True)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"db_table": "training_courses", "ordering": ["code"]}),
        migrations.CreateModel(name="TrainingRecord", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("status", models.CharField(choices=[("enrolled", "Enrolled"), ("in_progress", "In Progress"), ("completed", "Completed"), ("failed", "Failed"), ("withdrawn", "Withdrawn")], db_index=True, default="enrolled", max_length=12)),
            ("start_date", models.DateField()),
            ("end_date", models.DateField(blank=True, null=True)),
            ("completed_on", models.DateField(blank=True, null=True)),
            ("notes", models.CharField(blank=True, max_length=300)),
            ("created_by_username", models.CharField(blank=True, max_length=150)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("course", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="records", to="training.course")),
            ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="personnel.personnel")),
        ], options={"db_table": "training_records", "ordering": ["-start_date", "id"]}),
        migrations.AddConstraint(model_name="trainingrecord", constraint=models.UniqueConstraint(fields=("personnel", "course", "start_date"), name="training_record_unique")),
        migrations.AddConstraint(model_name="trainingrecord", constraint=models.CheckConstraint(condition=Q(end_date__isnull=True) | Q(end_date__gte=F("start_date")), name="training_dates_valid")),
        migrations.AddConstraint(model_name="trainingrecord", constraint=models.CheckConstraint(
            condition=(Q(status="completed", completed_on__isnull=False) | (~Q(status="completed") & Q(completed_on__isnull=True))),
            name="training_completed_has_date")),
    ]
