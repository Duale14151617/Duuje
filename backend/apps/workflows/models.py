import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.appendonly import AppendOnlyModel

FIGURE_KEYS = ["personnel_strength", "personnel_on_leave", "personnel_in_training", "open_requests"]


class ReportType(models.Model):
    """Configurable kind of request/report. Figures are whitelisted numeric fields that roll up into summaries."""

    class Kind(models.TextChoices):
        REPORT = "report"
        REQUEST = "request"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=48, unique=True)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    figure_keys = models.JSONField(default=list, blank=True)
    separation_of_duties = models.BooleanField(default=True)  # submitter may never approve their own
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "report_types"
        ordering = ["code"]


class Submission(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        SUBMITTED = "submitted"
        UNDER_REVIEW = "under_review"
        APPROVED = "approved"
        REJECTED = "rejected"
        RETURNED = "returned"
        AMENDED = "amended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report_type = models.ForeignKey(ReportType, on_delete=models.PROTECT, related_name="submissions")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=200)
    period_start = models.DateField()
    period_end = models.DateField()
    body = models.TextField(blank=True)
    figures = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    version = models.PositiveIntegerField(default=1)
    current_revision = models.PositiveIntegerField(default=0)
    approved_revision = models.ForeignKey("workflows.SubmissionRevision", null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name="+")
    submitter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    submitter_username = models.CharField(max_length=150)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "submissions"
        ordering = ["-updated_at", "id"]
        constraints = [models.CheckConstraint(condition=Q(period_end__gte=F("period_start")), name="submission_period_valid")]


class SubmissionRevision(AppendOnlyModel):
    """Immutable snapshot taken each time a submission is (re)submitted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name="revisions")
    revision_no = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    period_start = models.DateField()
    period_end = models.DateField()
    body = models.TextField(blank=True)
    figures = models.JSONField(default=dict, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    submitted_by_username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "submission_revisions"
        ordering = ["revision_no"]
        constraints = [models.UniqueConstraint(fields=["submission", "revision_no"], name="revision_unique_per_submission")]


class ApprovalAction(AppendOnlyModel):
    """Who did what, when and why. Written only by the workflow service."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name="actions")
    revision_no = models.PositiveIntegerField(default=0)
    action = models.CharField(max_length=16)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_username = models.CharField(max_length=150)
    comment = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "approval_actions"
        ordering = ["created_at", "id"]


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=24)
    submission = models.ForeignKey(Submission, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at", "id"]
        indexes = [models.Index(fields=["recipient", "read_at"], name="notif_recipient_read_idx")]
