import uuid

from django.db import models


class LeaveType(models.Model):
    """Catalogue of leave types (data, editable). `max_days` caps one request when set."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    max_days = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "leave_types"
        ordering = ["code"]


class LeaveRequest(models.Model):
    """One leave request for one person. Decided once: approved or rejected; a pending or approved request can be cancelled.
    Nothing here changes personnel status or attendance."""

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="leave_requests")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")  # unit at request time
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="+")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    requested_by_id = models.UUIDField(null=True, blank=True)
    requested_by_username = models.CharField(max_length=150, blank=True)
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_username = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "leave_requests"
        ordering = ["-start_date", "-created_at"]
        indexes = [models.Index(fields=["org_unit", "start_date"], name="leave_unit_start_idx")]
        constraints = [models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")), name="leave_end_after_start")]


class RosterShift(models.Model):
    """Who is on which duty on which day. One row per person per day; changing it rewrites the row (every change is audited)."""

    class Shift(models.TextChoices):
        DAY = "day"
        NIGHT = "night"
        STANDBY = "standby"
        OFF = "off"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="roster_shifts")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    duty_date = models.DateField()
    shift = models.CharField(max_length=8, choices=Shift.choices)
    post = models.CharField(max_length=100, blank=True)
    set_by_username = models.CharField(max_length=150, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leave_roster_shifts"
        ordering = ["duty_date", "personnel_id"]
        indexes = [models.Index(fields=["org_unit", "duty_date"], name="roster_unit_day_idx")]
        constraints = [models.UniqueConstraint(fields=["personnel", "duty_date"], name="roster_one_per_person_day")]
