import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.appendonly import AppendOnlyModel


class Personnel(models.Model):
    """Minimal approved fields only. No medical, family or biometric data in this release."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        ON_LEAVE = "on_leave"
        SUSPENDED = "suspended"
        RETIRED = "retired"
        DISCHARGED = "discharged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_number = models.CharField(max_length=32, null=True, blank=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=24, blank=True)
    name_key = models.CharField(max_length=150, db_index=True, editable=False)   # normalised, for duplicate checks
    phone_key = models.CharField(max_length=24, blank=True, editable=False)      # digits only
    branch = models.ForeignKey("organization.ServiceBranch", on_delete=models.PROTECT, related_name="+")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="personnel")
    rank = models.ForeignKey("ranks.Rank", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personnel"
        ordering = ["full_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["service_number"], condition=Q(service_number__isnull=False),
                                    name="personnel_service_number_unique"),
        ]


class PersonnelHistory(AppendOnlyModel):
    """Effective-dated record of rank / unit / status changes. Written only by the service layer."""

    class Field(models.TextChoices):
        RANK = "rank"
        ORG_UNIT = "org_unit"
        STATUS = "status"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey(Personnel, on_delete=models.PROTECT, related_name="history")
    field = models.CharField(max_length=10, choices=Field.choices)
    old_ref = models.CharField(max_length=64, blank=True)
    new_ref = models.CharField(max_length=64)
    old_label = models.CharField(max_length=200, blank=True)  # human-readable snapshot (English)
    new_label = models.CharField(max_length=200)
    effective_date = models.DateField()
    reason = models.CharField(max_length=300, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_username = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "personnel_history"
        ordering = ["-effective_date", "-recorded_at"]
        indexes = [models.Index(fields=["personnel", "field"], name="phist_person_field_idx")]


class ImportBatch(models.Model):
    """Server-side holding area between CSV preview and commit. Rows are wiped on commit/expiry."""

    class Status(models.TextChoices):
        PREVIEW = "preview"
        COMMITTED = "committed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREVIEW)
    rows = models.JSONField(default=list)
    total = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "personnel_import_batches"
