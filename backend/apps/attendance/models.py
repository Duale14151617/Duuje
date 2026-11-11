import uuid

from django.db import models

from apps.core.appendonly import AppendOnlyError


class AbsenceReason(models.Model):
    """Catalogue of absence reasons (data, editable). `requires_document` makes a supporting document mandatory for it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    requires_document = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "attendance_absence_reasons"
        ordering = ["code"]


class AttendanceRecord(models.Model):
    """One soldier, one day. Attendance is NOT personnel status: an absent soldier never becomes Suspended or Jailed because
    of this table. Rows are never edited or deleted: an amendment writes a new row that supersedes the old one (reason required),
    and the old row stays as history."""

    class Status(models.TextChoices):
        PRESENT = "present"
        ABSENT = "absent"
        ON_LEAVE = "on_leave"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="attendance")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")  # assignment at the time
    report_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    reason = models.ForeignKey(AbsenceReason, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=300, blank=True)
    document = models.ForeignKey("personnel.PersonnelDocument", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reported_by_id = models.UUIDField(null=True, blank=True)
    reported_by_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # submission timestamp
    supersedes = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="amendments")
    superseded_at = models.DateTimeField(null=True, blank=True)
    amend_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "attendance_records"
        ordering = ["-report_date", "personnel_id", "-created_at"]
        indexes = [models.Index(fields=["org_unit", "report_date"], name="attendance_unit_day_idx")]
        constraints = [
            models.UniqueConstraint(fields=["personnel", "report_date"], condition=models.Q(superseded_at__isnull=True),
                                    name="attendance_one_current_per_day"),
            models.CheckConstraint(condition=models.Q(status="absent") | models.Q(reason__isnull=True),
                                   name="attendance_reason_only_when_absent"),
        ]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Attendance records cannot be deleted; amend them instead.")
