"""Protective equipment (PPE) accountability: what each member of personnel holds, issued from the unit's PPE store.

The unit-level quantity and procurement stay in the logistics stock ledger (StockLine / StockTransaction, categories whose code starts
with "ppe"). This app adds the person-level layer, as append-only ledgers: a holder's balance is the sum of their rows, nothing is
typed in, and nothing is edited or deleted. Logistics itself keeps no link to individual personnel; only this ledger does."""
import uuid

from django.db import models

from apps.core.appendonly import AppendOnlyModel


class PpeMovement(AppendOnlyModel):
    class Kind(models.TextChoices):
        ISSUE = "issue"          # from the store to the person
        RETURN = "return"        # serviceable item handed back to the store
        DAMAGED = "damaged"      # written off the person as damaged (not back in store)
        LOST = "lost"            # written off as lost
        RETIRED = "retired"      # worn out / expired, withdrawn from service

    class Condition(models.TextChoices):
        NEW = "new"
        GOOD = "good"
        FAIR = "fair"
        POOR = "poor"
        UNSERVICEABLE = "unserviceable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="ppe_ledger")
    stock_line = models.ForeignKey("logistics.StockLine", on_delete=models.PROTECT, related_name="ppe_movements")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    delta = models.IntegerField()
    size = models.CharField(max_length=20, blank=True)
    serial = models.CharField(max_length=64, blank=True)  # optional item serial (e.g. body-armour plate number)
    condition = models.CharField(max_length=16, choices=Condition.choices, default=Condition.NEW)
    reference = models.CharField(max_length=60, blank=True)  # issue / return voucher number (same number as in the unit ledger)
    authority_ref = models.CharField(max_length=150, blank=True)
    note = models.CharField(max_length=300, blank=True)
    group = models.UUIDField(null=True, blank=True)  # pairs the two rows of a replacement
    store_transaction = models.ForeignKey("logistics.StockTransaction", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="ppe_movements")
    actor_id = models.UUIDField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ppe_movements"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["personnel", "stock_line"], name="ppe_move_person_line"),
                   models.Index(fields=["stock_line", "kind"], name="ppe_move_line_kind"),
                   models.Index(fields=["created_at"], name="ppe_move_created")]
        constraints = [
            models.CheckConstraint(condition=~models.Q(delta=0), name="ppe_move_nonzero"),
            models.CheckConstraint(
                condition=models.Q(kind="issue", delta__gt=0) | models.Q(kind__in=["return", "damaged", "lost", "retired"], delta__lt=0),
                name="ppe_move_sign_by_kind"),
            models.UniqueConstraint(fields=["store_transaction"], condition=models.Q(store_transaction__isnull=False),
                                    name="ppe_move_one_per_store_txn"),
            models.CheckConstraint(condition=models.Q(kind__in=["issue", "return"]) | models.Q(store_transaction__isnull=True),
                                   name="ppe_move_writeoff_not_in_store"),
        ]


class PpeInspection(AppendOnlyModel):
    """An inspection of the PPE a person holds (one line of equipment): the condition found and when the next one is due."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="ppe_inspections")
    stock_line = models.ForeignKey("logistics.StockLine", on_delete=models.PROTECT, related_name="ppe_inspections")
    inspected_on = models.DateField()
    condition = models.CharField(max_length=16, choices=PpeMovement.Condition.choices)
    next_due = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ppe_inspections"
        ordering = ["-inspected_on", "-created_at"]
        indexes = [models.Index(fields=["personnel", "stock_line", "-inspected_on"], name="ppe_insp_person_line")]
