"""Vehicle and traffic taxes (cash, paper receipt).

* These are CIVILIAN vehicles and the people who pay for them: a separate register from the Army vehicle fleet (apps.vehicles).
* A payment is one paper receipt. The receipt number is written on the receipt book page by hand and typed in here; the same number
  cannot be used twice in a station. Payments are voided with a reason, never deleted, and cannot be voided once handed over.
* Cash handover: a collector hands over the unit's uncollected receipts as one batch; a DIFFERENT person counts the cash and confirms
  it. Any difference between the receipts and the cash counted is kept on the record and needs a note.
* Amounts are never invented: tax types are created without amounts, and HQ sets the default amount of each type.
"""
import uuid

from django.db import models
from django.db.models import Q

from apps.core.appendonly import AppendOnlyError


class TaxCounter(models.Model):
    name = models.CharField(max_length=20, primary_key=True)
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "tax_counters"


class TaxType(models.Model):
    class Kind(models.TextChoices):
        LICENCE = "licence", "Vehicle licence"
        ROAD_TAX = "road_tax", "Road tax"
        FINE = "fine", "Traffic fine"
        FEE = "fee", "Fee / permit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FEE)
    default_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    recurring = models.BooleanField(default=False)  # True: a payment covers a period and the vehicle can fall overdue
    period_months = models.PositiveSmallIntegerField(default=12)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tax_types"
        ordering = ["sort_order", "code"]
        constraints = [models.CheckConstraint(condition=Q(default_amount__isnull=True) | Q(default_amount__gt=0), name="taxtype_amount_positive")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Tax rows cannot be deleted.")


class TaxVehicle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plate = models.CharField(max_length=20)
    plate_key = models.CharField(max_length=20, unique=True, editable=False)  # upper-case, no spaces/dashes
    owner_name = models.CharField(max_length=200)
    owner_phone = models.CharField(max_length=40, blank=True)
    id_ref = models.CharField(max_length=80, blank=True)
    vehicle_kind = models.CharField(max_length=60, blank=True)  # car, truck, motorbike, bajaj ...
    make_model = models.CharField(max_length=120, blank=True)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="tax_vehicles")  # registering station
    active = models.BooleanField(default=True)
    notes = models.CharField(max_length=300, blank=True)
    created_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tax_vehicles"
        ordering = ["plate_key"]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Tax rows cannot be deleted.")


class TaxHandover(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Waiting to be counted"
        CONFIRMED = "confirmed", "Counted and confirmed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=20, unique=True)  # HO-000001
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="tax_handovers")
    currency = models.CharField(max_length=3)
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2)
    payments_count = models.PositiveIntegerField()
    handed_by_username = models.CharField(max_length=150)
    handed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    counted_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    confirmed_by_username = models.CharField(max_length=150, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "tax_handovers"
        ordering = ["-handed_at"]
        constraints = [models.CheckConstraint(condition=Q(expected_amount__gte=0), name="taxho_expected_nonneg")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Tax rows cannot be deleted.")


class TaxPayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt_no = models.CharField(max_length=40)  # number printed on the paper receipt
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="tax_payments")  # collecting station
    vehicle = models.ForeignKey(TaxVehicle, on_delete=models.PROTECT, related_name="payments")
    tax_type = models.ForeignKey(TaxType, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    paid_on = models.DateField()
    period_from = models.DateField(null=True, blank=True)  # recurring types: the period this payment covers
    period_to = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=150, blank=True)  # fine ticket / offence number
    collected_by = models.ForeignKey("personnel.Personnel", null=True, blank=True, on_delete=models.PROTECT, related_name="tax_collections")
    collected_by_username = models.CharField(max_length=150, blank=True)
    handover = models.ForeignKey(TaxHandover, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by_username = models.CharField(max_length=150, blank=True)
    voided_reason = models.CharField(max_length=300, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tax_payments"
        ordering = ["-paid_on", "-created_at"]
        indexes = [models.Index(fields=["vehicle", "tax_type", "-period_to"], name="taxpay_cover_idx"),
                   models.Index(fields=["org_unit", "handover"], name="taxpay_unit_ho_idx")]
        constraints = [
            models.UniqueConstraint(fields=["org_unit", "receipt_no"], condition=Q(voided_at__isnull=True), name="taxpay_receipt_unique_live"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="taxpay_amount_positive"),
            models.CheckConstraint(condition=Q(period_from__isnull=True) | Q(period_to__isnull=True) | Q(period_to__gte=models.F("period_from")), name="taxpay_period_order"),
        ]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Tax rows cannot be deleted.")
