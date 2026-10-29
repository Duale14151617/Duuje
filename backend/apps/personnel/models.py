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
        JAILED = "jailed"
        DIED = "died"  # set only by a confirmed death record (personnel/death.py); the profile stays on file permanently
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
    # Reporting line: the person this one reports to. Drives the `personnel.view_team` rule (own record + direct subordinates).
    supervisor = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="subordinates")
    # The login account that belongs to this person (used to find "my own record"). One account per person, and vice versa.
    account = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="personnel_record")
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
        DEATH_EVIDENCE = "death_evidence"  # death certificate or other supporting document for a death record
        ATTENDANCE_SUPPORT = "attendance_support"  # supporting document for an absence
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


class DeathRecord(models.Model):
    """The report and confirmation of a death. Reported by one authorized officer, confirmed by a *different* authorized
    officer once supporting evidence is on file; only confirmation changes the person's status to Died. Rows are never
    deleted (a mistaken report is withdrawn, with a reason) and the personnel profile, history and documents stay."""

    class State(models.TextChoices):
        REPORTED = "reported"
        CONFIRMED = "confirmed"
        WITHDRAWN = "withdrawn"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey(Personnel, on_delete=models.PROTECT, related_name="death_records")
    date_of_death = models.DateField()
    note = models.CharField(max_length=300, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.REPORTED)
    reported_at = models.DateTimeField(auto_now_add=True)
    reported_by_id = models.UUIDField(null=True, blank=True)
    reported_by_username = models.CharField(max_length=150, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by_id = models.UUIDField(null=True, blank=True)
    confirmed_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by_id = models.UUIDField(null=True, blank=True)
    withdrawn_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "personnel_death_records"
        ordering = ["-reported_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["personnel"], condition=~models.Q(state="withdrawn"),
                                    name="death_one_open_record_per_person"),
            models.CheckConstraint(
                condition=~models.Q(state="confirmed") | (models.Q(confirmed_at__isnull=False) & models.Q(confirmed_by_id__isnull=False)),
                name="death_confirmed_has_confirmer"),
        ]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Death records cannot be deleted; withdraw a mistaken report instead.")


class AppointmentType(models.Model):
    """A command appointment title (Taliye Qaybeed, Taliye Urur ...). Data, not code: add or retire titles without a release.
    An appointment is NOT a rank, NOT an organizational assignment and NOT an application role: it records who holds a command
    office, where and since when. It never grants access by itself."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    unit_type = models.ForeignKey("organization.UnitType", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    exclusive = models.BooleanField(default=True, help_text="Only one current holder per unit.")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personnel_appointment_types"
        ordering = ["code"]


class CommandAppointment(models.Model):
    """Who holds which command office in which unit, with effective dates. Never deleted: an appointment is ended (with a
    reason) and the row stays as history. Ending it also revokes the application role assignment it was linked to, so
    access ends when the authority ends."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey(Personnel, on_delete=models.PROTECT, related_name="appointments")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    appointment_type = models.ForeignKey(AppointmentType, on_delete=models.PROTECT, related_name="appointments")
    exclusive = models.BooleanField(default=True)  # copied from the type when created, so the database can enforce it
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    authority_ref = models.CharField(max_length=150, blank=True)  # order / letter that authorizes the appointment
    role_assignment = models.ForeignKey("accounts.RoleAssignment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by_id = models.UUIDField(null=True, blank=True)
    created_by_username = models.CharField(max_length=150, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by_id = models.UUIDField(null=True, blank=True)
    ended_by_username = models.CharField(max_length=150, blank=True)
    end_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "personnel_command_appointments"
        ordering = ["-effective_from", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["org_unit", "appointment_type"], name="appointment_one_open_exclusive",
                                    condition=models.Q(ended_at__isnull=True, exclusive=True)),
            models.CheckConstraint(condition=models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=models.F("effective_from")),
                                   name="appointment_dates_ordered"),
        ]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Appointments cannot be deleted; end the appointment instead.")


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


# ------------------------------------------------------------------ administrative tasks (Operations and other sections)
class UnitTask(models.Model):
    """An authorized administrative task or activity recorded against a unit (a section, Urur or Guuto): what, who is
    responsible, when assigned and due, current status, and a completion report with a document reference. It records
    accountability only; it does not define operational procedure."""

    class Status(models.TextChoices):
        OPEN = "open"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=200)
    description = models.CharField(max_length=1000, blank=True)
    authority_ref = models.CharField(max_length=150)  # the order or instruction that authorizes the task
    assigned_on = models.DateField()
    due_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    responsible = models.ForeignKey(Personnel, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    completion_report = models.CharField(max_length=2000, blank=True)
    document_ref = models.CharField(max_length=150, blank=True)  # reference to a supporting document, kept as text
    cancel_reason = models.CharField(max_length=300, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "unit_tasks"
        ordering = ["due_on", "-created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=~Q(title="") & ~Q(authority_ref=""), name="unittask_title_authority_present"),
            models.CheckConstraint(condition=Q(due_on__isnull=True) | Q(due_on__gte=models.F("assigned_on")), name="unittask_due_after_assigned"),
        ]


class TaskEvent(AppendOnlyModel):
    """What happened to a task and who did it. Written only by the service layer; never changed afterwards."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(UnitTask, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=12)  # created, updated, started, completed, cancelled
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, blank=True)
    note = models.CharField(max_length=300, blank=True)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "unit_task_events"
        ordering = ["created_at", "id"]
