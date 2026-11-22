"""Sensitive-item inventory (weapons). A physical count of every serial-numbered weapon a unit should hold: someone checks each
serial number against the register, a DIFFERENT person signs the count off, and every shortage or mismatch must be explained
before the sign-off is accepted. Modelled on the cyclic and change-of-command sensitive-item inventories of Western armies.

The register itself is never changed by a count. A count records what was found; fixing the register (marking a weapon lost,
returning it, correcting a serial) stays in the weapon-register workflow, so those actions keep their own approvals."""
import uuid

from django.db import models


class InventoryCount(models.Model):
    class Kind(models.TextChoices):
        CYCLIC = "cyclic"                          # the regular scheduled count
        CHANGE_OF_COMMAND = "change_of_command"   # before a new commander takes responsibility
        SPOT = "spot"                              # an unannounced check

    class Status(models.TextChoices):
        OPEN = "open"
        SUBMITTED = "submitted"
        SIGNED = "signed"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CYCLIC)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    note = models.CharField(max_length=300, blank=True)
    opened_by_id = models.UUIDField(null=True, blank=True)
    opened_by_username = models.CharField(max_length=150, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    submitted_by_id = models.UUIDField(null=True, blank=True)
    submitted_by_username = models.CharField(max_length=150, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    signed_by_id = models.UUIDField(null=True, blank=True)
    signed_by_username = models.CharField(max_length=150, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    sign_note = models.CharField(max_length=300, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inventory_counts"
        ordering = ["-opened_at"]


class InventoryLine(models.Model):
    class Result(models.TextChoices):
        PENDING = "pending"
        VERIFIED = "verified"      # the serial number was read off the item and matches the register
        MISSING = "missing"        # the register lists it, but it could not be found
        MISMATCH = "mismatch"      # an item is there but its serial number differs from the register
        UNLISTED = "unlisted"      # an item was found that the register does not list for this unit

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    count = models.ForeignKey(InventoryCount, on_delete=models.PROTECT, related_name="lines")
    asset = models.ForeignKey("logistics.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    expected_identifier = models.CharField(max_length=64, blank=True)   # snapshot at the time the count was opened
    expected_type = models.CharField(max_length=120, blank=True)
    expected_holder = models.CharField(max_length=200, blank=True)
    expected_status = models.CharField(max_length=12, blank=True)
    result = models.CharField(max_length=10, choices=Result.choices, default=Result.PENDING)
    observed_identifier = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=300, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    checked_by_username = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "inventory_lines"
        ordering = ["expected_identifier", "id"]
        indexes = [models.Index(fields=["count", "result"], name="inv_line_count_result_idx")]
