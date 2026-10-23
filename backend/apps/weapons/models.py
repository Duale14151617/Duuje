import uuid

from django.db import models

from apps.core.appendonly import AppendOnlyError


class WeaponDetail(models.Model):
    """Weapon-specific facts for an asset in a weapons category. The asset row carries the unique serial number (identifier),
    the holding unit and the unit-level status; this row adds type, make, caliber and condition. Counts are never stored: they are
    derived from the register."""

    class Condition(models.TextChoices):
        SERVICEABLE = "serviceable"
        NEEDS_REPAIR = "needs_repair"
        UNSERVICEABLE = "unserviceable"

    asset = models.OneToOneField("logistics.Asset", primary_key=True, on_delete=models.PROTECT, related_name="weapon")
    weapon_type = models.CharField(max_length=60)
    make_model = models.CharField(max_length=120, blank=True)
    caliber = models.CharField(max_length=40, blank=True)
    condition = models.CharField(max_length=16, choices=Condition.choices, default=Condition.SERVICEABLE)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "weapon_details"


class WeaponCustody(models.Model):
    """A soldier's custody of one weapon, from issue to return. Never edited or deleted: a return closes the row, a new issue
    opens a new one, so the full chain of custody stays. One open custody per weapon (database constraint)."""

    class Outcome(models.TextChoices):
        RETURNED = "returned"
        LOST = "lost"
        MISSING = "missing"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey("logistics.Asset", on_delete=models.PROTECT, related_name="custody")
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="weapon_custody")
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by_id = models.UUIDField(null=True, blank=True)
    issued_by_username = models.CharField(max_length=150, blank=True)
    authority_ref = models.CharField(max_length=150)  # the authorization (order or signed form) for this issue
    issue_condition = models.CharField(max_length=16, choices=WeaponDetail.Condition.choices)
    issue_note = models.CharField(max_length=300, blank=True)
    status_before = models.CharField(max_length=12)  # the asset's unit-level state before the issue, restored on return
    issued_unit_before = models.ForeignKey("organization.OrganizationalUnit", null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by_id = models.UUIDField(null=True, blank=True)
    returned_by_username = models.CharField(max_length=150, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    return_condition = models.CharField(max_length=16, choices=WeaponDetail.Condition.choices, blank=True)
    return_note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "weapon_custody"
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(fields=["asset"], condition=models.Q(returned_at__isnull=True), name="weapon_one_open_custody"),
            models.CheckConstraint(condition=models.Q(returned_at__isnull=True, outcome="") | models.Q(returned_at__isnull=False) & ~models.Q(outcome=""),
                                   name="weapon_custody_closed_has_outcome"),
        ]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Custody records cannot be deleted; they are closed by a return.")
