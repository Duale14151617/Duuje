"""Logistics inventory. Deliberately has NO link to personnel records: equipment is accounted to
organizational units and accountable custodians, never as a person-by-person assignment directory."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.appendonly import AppendOnlyModel


class InventoryCategory(models.Model):
    class Kind(models.TextChoices):
        STOCK = "stock"   # quantity-tracked (consumables, supplies)
        ASSET = "asset"   # individually tracked items

    class Approval(models.TextChoices):
        DRAFT = "draft"
        APPROVED = "approved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=48, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    restricted = models.BooleanField(default=False)  # sensitive equipment accountability workflow
    approval_status = models.CharField(max_length=10, choices=Approval.choices, default=Approval.DRAFT)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_categories"
        ordering = ["code"]


class StockLine(models.Model):
    """Quantity of one stock category held by one unit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(InventoryCategory, on_delete=models.PROTECT, related_name="+")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    uom = models.CharField(max_length=16, default="units")
    quantity = models.PositiveIntegerField(default=0)  # DB-level CHECK >= 0 as a backstop against negative stock
    reorder_level = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_lines"
        ordering = ["category__code", "org_unit__path"]
        constraints = [models.UniqueConstraint(fields=["category", "org_unit"], name="stockline_unique_per_unit")]


class StockTransaction(AppendOnlyModel):
    class Kind(models.TextChoices):
        RECEIVE = "receive"
        ISSUE = "issue"
        ADJUST = "adjust"
        TRANSFER_OUT = "transfer_out"
        TRANSFER_IN = "transfer_in"
        # Ammunition ledger (see ammunition.py): an opening balance, returns, recorded expenditure, losses and damage.
        OPENING = "opening"
        RETURN = "return"
        EXPENDITURE = "expenditure"
        LOSS = "loss"
        DAMAGE = "damage"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock_line = models.ForeignKey(StockLine, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    delta = models.IntegerField()
    balance_after = models.PositiveIntegerField()
    reason = models.CharField(max_length=300, blank=True)
    counterpart_unit = models.ForeignKey("organization.OrganizationalUnit", null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="+")
    group = models.UUIDField(null=True, blank=True)  # pairs the two sides of a transfer
    external_ref = models.CharField(max_length=60, blank=True)  # voucher / delivery note / issue note number: stops one movement being entered twice
    authority_ref = models.CharField(max_length=150, blank=True)  # documented authorization (adjustments, losses, damage)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_username = models.CharField(max_length=150, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_transactions"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=~Q(delta=0), name="stocktxn_nonzero_delta"),
            # The direction of a movement follows from its kind; only an adjustment may go either way.
            models.CheckConstraint(
                condition=(Q(kind__in=["opening", "receive", "return", "transfer_in"], delta__gt=0)
                           | Q(kind__in=["issue", "expenditure", "loss", "damage", "transfer_out"], delta__lt=0)
                           | Q(kind="adjust")),
                name="stocktxn_delta_sign_by_kind"),
            # The same voucher cannot be booked twice for the same kind of movement on a line.
            models.UniqueConstraint(fields=["stock_line", "kind", "external_ref"], condition=~Q(external_ref=""),
                                    name="stocktxn_unique_voucher"),
            models.UniqueConstraint(fields=["stock_line"], condition=Q(kind="opening"), name="stocktxn_one_opening"),
        ]


class Asset(models.Model):
    class Status(models.TextChoices):
        IN_STOCK = "in_stock"
        ISSUED = "issued"
        MAINTENANCE = "maintenance"
        MISSING = "missing"
        LOST = "lost"
        RETIRED = "retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(InventoryCategory, on_delete=models.PROTECT, related_name="+")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    identifier = models.CharField(max_length=64)  # serial / tag, unique within the category
    description = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_STOCK)
    issued_to_unit = models.ForeignKey("organization.OrganizationalUnit", null=True, blank=True,
                                       on_delete=models.PROTECT, related_name="+")  # a UNIT, never a person
    custodian = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets"
        ordering = ["category__code", "identifier"]
        constraints = [
            models.UniqueConstraint(fields=["category", "identifier"], name="asset_identifier_unique"),
            models.CheckConstraint(
                condition=(Q(status="issued", issued_to_unit__isnull=False)
                           | (~Q(status="issued") & Q(issued_to_unit__isnull=True))),
                name="asset_issue_consistent"),
        ]


class AssetEvent(AppendOnlyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=24)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, blank=True)
    from_unit = models.ForeignKey("organization.OrganizationalUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_unit = models.ForeignKey("organization.OrganizationalUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=300, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "asset_events"
        ordering = ["-created_at", "-id"]


class Reconciliation(models.Model):
    class Status(models.TextChoices):
        OPEN = "open"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    includes_restricted = models.BooleanField(default=False)
    notes = models.CharField(max_length=300, blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reconciliations"
        ordering = ["-started_at", "id"]
        constraints = [models.UniqueConstraint(fields=["org_unit"], condition=Q(status="open"),
                                               name="recon_one_open_per_unit")]


class ReconciliationLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reconciliation = models.ForeignKey(Reconciliation, on_delete=models.CASCADE, related_name="lines")
    stock_line = models.ForeignKey(StockLine, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    label = models.CharField(max_length=200)
    expected_quantity = models.PositiveIntegerField(null=True, blank=True)
    counted_quantity = models.PositiveIntegerField(null=True, blank=True)
    found = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "reconciliation_lines"
        ordering = ["label", "id"]
        constraints = [models.CheckConstraint(
            condition=(Q(stock_line__isnull=False, asset__isnull=True) | Q(stock_line__isnull=True, asset__isnull=False)),
            name="reconline_one_target")]


# ------------------------------------------------------------------ food stores (suppliers, batches, allocations)
class Supplier(models.Model):
    """A food supplier on file. Records are never deleted; a supplier that is no longer used is switched off."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=200, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "food_suppliers"
        ordering = ["name"]


class FoodBatch(models.Model):
    """One delivery (or one part of an allocation) of food in a store, with its expiry date.

    `remaining` is reduced earliest-expiry-first when food leaves the store through the food module. The stock ledger stays the
    source of truth for the quantity; a store whose batches do not add up to its ledger balance is flagged in the warnings."""

    class Source(models.TextChoices):
        RECEIPT = "receipt"        # received from a supplier
        ALLOCATION = "allocation"  # received from another store
        OPENING = "opening"        # opening balance entered by spreadsheet import (one ledger entry per store, many batches)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock_line = models.ForeignKey(StockLine, on_delete=models.PROTECT, related_name="batches")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    batch_ref = models.CharField(max_length=60, blank=True)
    quantity = models.PositiveIntegerField()
    remaining = models.PositiveIntegerField()
    received_on = models.DateField()
    expires_on = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.RECEIPT)
    delivery_note_ref = models.CharField(max_length=60, blank=True)
    authority_ref = models.CharField(max_length=150, blank=True)
    txn = models.ForeignKey(StockTransaction, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "food_batches"
        ordering = ["expires_on", "received_on", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0) & Q(remaining__lte=models.F("quantity")), name="foodbatch_quantities"),
            models.UniqueConstraint(fields=["supplier", "delivery_note_ref"], condition=Q(source="receipt"),
                                    name="foodbatch_one_receipt_per_delivery_note"),
        ]


class FoodAllocation(models.Model):
    """Food sent from one store to another unit on an Army order. The stock leaves the sending store when it is issued and
    reaches the receiving unit only when an HQ administrator records the signed delivery note (so nothing is credited that has
    not arrived). An undelivered allocation can be cancelled, which returns the stock to the sending store."""

    class Status(models.TextChoices):
        ISSUED = "issued"
        DELIVERED = "delivered"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    from_line = models.ForeignKey(StockLine, on_delete=models.PROTECT, related_name="+")
    to_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED, db_index=True)
    order_ref = models.CharField(max_length=150)
    issuing_officer = models.CharField(max_length=150)
    order_date = models.DateField()
    issue_note_ref = models.CharField(max_length=60)
    group = models.UUIDField(default=uuid.uuid4, editable=False)
    consumed = models.JSONField(default=list)  # [{"batch": id, "qty": n}] taken from the sending store, earliest expiry first
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    issued_by_username = models.CharField(max_length=150, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    received_by_name = models.CharField(max_length=150, blank=True)  # the person who signed for it
    receipt_note_ref = models.CharField(max_length=60, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    acknowledged_by_username = models.CharField(max_length=150, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "food_allocations"
        ordering = ["-issued_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="foodalloc_positive"),
            models.CheckConstraint(condition=~Q(order_ref="") & ~Q(issuing_officer="") & ~Q(issue_note_ref=""), name="foodalloc_order_present"),
        ]
