import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Course(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=48, unique=True)
    name_en = models.CharField(max_length=150)
    name_so = models.CharField(max_length=150, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "training_courses"
        ordering = ["code"]


class TrainingRecord(models.Model):
    class Status(models.TextChoices):
        ENROLLED = "enrolled"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        FAILED = "failed"
        WITHDRAWN = "withdrawn"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="+")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="records")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ENROLLED, db_index=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "training_records"
        ordering = ["-start_date", "id"]
        constraints = [
            models.UniqueConstraint(fields=["personnel", "course", "start_date"], name="training_record_unique"),
            models.CheckConstraint(condition=Q(end_date__isnull=True) | Q(end_date__gte=F("start_date")), name="training_dates_valid"),
            models.CheckConstraint(
                condition=(Q(status="completed", completed_on__isnull=False) | (~Q(status="completed") & Q(completed_on__isnull=True))),
                name="training_completed_has_date"),
        ]
