"""Occurrence Book (OB): the station's running daily log of everything that happens, in the order it happens.

* Each station numbers its own entries per year (OB 0001/2026, OB 0002/2026 ...). A number is never reused and never skipped silently.
* An entry is never edited or deleted. A mistake is corrected with a follow-up line, or the entry is voided with a reason.
* Follow-ups (updates, corrections, outcomes) are append-only, like the custody log.
* An entry can point at a detention record (an arrest is normally entered in the OB as well as the detention register).
"""
import uuid

from django.db import models

from apps.core.appendonly import AppendOnlyError, AppendOnlyModel


class OccurrenceCounter(models.Model):
    """Next-number holder per station and year (locked with SELECT ... FOR UPDATE)."""

    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    year = models.PositiveSmallIntegerField()
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "occurrence_counters"
        constraints = [models.UniqueConstraint(fields=["org_unit", "year"], name="ob_counter_unit_year")]


class OccurrenceEntry(models.Model):
    class Category(models.TextChoices):
        COMPLAINT = "complaint", "Complaint / report made"
        ARREST = "arrest", "Arrest"
        INCIDENT = "incident", "Incident"
        ACCIDENT = "accident", "Traffic accident"
        THEFT_LOSS = "theft_loss", "Theft / loss reported"
        FOUND_PROPERTY = "found_property", "Found property"
        CUSTODY = "custody", "Custody (release / transfer)"
        PATROL = "patrol", "Patrol / duty"
        DUTY_CHANGE = "duty_change", "Change of duty officer"
        VISITOR = "visitor", "Visitor / enquiry"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        RECORDED = "recorded", "Recorded"
        VOID = "void", "Void"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="occurrence_entries")
    ob_year = models.PositiveSmallIntegerField()
    ob_seq = models.PositiveIntegerField()
    ob_number = models.CharField(max_length=20)  # "OB 0001/2026"
    category = models.CharField(max_length=16, choices=Category.choices)
    occurred_at = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True)
    reported_by = models.CharField(max_length=200, blank=True)  # complainant / informant / person who came to the station
    summary = models.CharField(max_length=300)
    details = models.TextField(blank=True, max_length=3000)
    detention_record = models.ForeignKey("detention.DetentionRecord", null=True, blank=True, on_delete=models.PROTECT, related_name="occurrence_entries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECORDED)
    recorded_by_username = models.CharField(max_length=150, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by_username = models.CharField(max_length=150, blank=True)
    voided_reason = models.CharField(max_length=300, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "occurrence_entries"
        ordering = ["-occurred_at", "-ob_seq"]
        constraints = [models.UniqueConstraint(fields=["org_unit", "ob_year", "ob_seq"], name="ob_number_unique_per_station_year")]
        indexes = [models.Index(fields=["org_unit", "-occurred_at"], name="ob_unit_time_idx"), models.Index(fields=["category", "-occurred_at"], name="ob_cat_time_idx")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Occurrence Book entries cannot be deleted.")


class OccurrenceFollowUp(AppendOnlyModel):
    class Kind(models.TextChoices):
        UPDATE = "update", "Update"
        CORRECTION = "correction", "Correction"
        OUTCOME = "outcome", "Outcome / closed"
        VOIDED = "voided", "Voided"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(OccurrenceEntry, on_delete=models.PROTECT, related_name="follow_ups")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    occurred_at = models.DateTimeField()
    text = models.CharField(max_length=500)
    by_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "occurrence_follow_ups"
        ordering = ["occurred_at", "created_at"]
