import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.appendonly import AppendOnlyError, AppendOnlyModel


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


class PersonnelProfile(models.Model):
    """Sensitive extras for one person: photo, blood type, weapon ID, date of birth, emergency contact...

    Everything personal is encrypted at rest (Fernet, FIELD_ENCRYPTION_KEY): the text fields as one JSON blob
    and the photo as encrypted JPEG bytes. weapon_key is a keyed hash of the weapon ID so the database can
    guarantee one weapon is never assigned to two people without storing the ID in the clear.
    """

    personnel = models.OneToOneField(Personnel, primary_key=True, on_delete=models.CASCADE, related_name="profile")
    data_enc = models.TextField(blank=True, default="")
    photo_enc = models.BinaryField(null=True, blank=True)
    photo_updated_at = models.DateTimeField(null=True, blank=True)
    weapon_key = models.CharField(max_length=64, null=True, blank=True, editable=False, unique=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personnel_profile"


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


class DisciplinaryRecord(AppendOnlyModel):
    """One entry in a person's disciplinary history. APPEND-ONLY: an entry is never edited or deleted.

    A correction is a new entry whose `corrects` points at the entry it replaces (the original stays visible, marked
    superseded). Everything descriptive (category, incident date, summary, outcome, whether the entry withdraws the one
    it corrects) lives in `data_enc`, encrypted with FIELD_ENCRYPTION_KEY. The row itself holds only ids and who/when.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey(Personnel, on_delete=models.PROTECT, related_name="disciplinary_records")
    corrects = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections")
    data_enc = models.TextField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_username = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "personnel_disciplinary"
        ordering = ["-recorded_at", "-id"]
        indexes = [models.Index(fields=["personnel", "-recorded_at"], name="pdisc_person_idx")]


class PersonnelDocument(models.Model):
    """A service document (scan or PDF) on a personnel file. The bytes and the descriptive text (title, original file
    name, note) are encrypted at rest. Documents are never deleted: a mistaken upload is *withdrawn* (hidden from the
    list and from download, kept for the audit trail). The database also refuses DELETE on this table."""

    class Category(models.TextChoices):
        SERVICE_RECORD = "service_record"
        APPOINTMENT = "appointment"
        TRAINING_CERTIFICATE = "training_certificate"
        COMMENDATION = "commendation"
        IDENTITY = "identity"
        OTHER = "other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey(Personnel, on_delete=models.PROTECT, related_name="documents")
    category = models.CharField(max_length=24, choices=Category.choices)
    meta_enc = models.TextField()
    content_enc = models.BinaryField()
    content_type = models.CharField(max_length=40)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)  # of the plaintext file, so an integrity check is possible after restore
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by_id = models.UUIDField(null=True, blank=True)
    uploaded_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by_id = models.UUIDField(null=True, blank=True)
    withdrawn_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_reason_enc = models.TextField(blank=True, default="")

    class Meta:
        db_table = "personnel_documents"
        ordering = ["-uploaded_at", "-id"]
        indexes = [models.Index(fields=["personnel", "-uploaded_at"], name="pdoc_person_idx")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Service documents cannot be deleted; withdraw them instead.")


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
