"""Military vehicle registry. One persistent record per Army vehicle, a stable system-generated Vehicle ID, and append-only history.

* The registration plate is an attribute, never the identifier: plates can change, the Vehicle ID cannot.
* Category (Ambulance, Armored truck, Hilux 4x4 ...) is configurable data and is stored apart from make/model.
* Current assignment lives on the Vehicle row (unit, driver, custodian, location, status); every change also writes an
  append-only VehicleEvent holding before/after values, so history is never lost and never mistaken for current ownership.
* Drivers and custodians are existing Personnel rows. Units are existing OrganizationalUnit rows. Nothing is duplicated.
* Counts are never stored: they are derived from these rows (see services.fleet_summary).
"""
import uuid

from django.db import models
from django.db.models import Q

from apps.core.appendonly import AppendOnlyError, AppendOnlyModel


class VehicleCategory(models.Model):
    """Configurable category. Seeded with the categories named by the Army; seeding does not assert the Army owns any."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=100)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vehicle_categories"
        ordering = ["sort_order", "code"]


class VehicleStatusType(models.Model):
    """Configurable operational status. The six system statuses are built in (the rules for maintenance and decommissioning refer to
    them) and cannot be renamed away or switched off; HQ can add further statuses and say whether a vehicle in them is available."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=30, unique=True)
    name_en = models.CharField(max_length=120)
    name_so = models.CharField(max_length=120, blank=True)
    available = models.BooleanField(default=True)  # False: counted as "unavailable for normal use"
    is_system = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vehicle_status_types"
        ordering = ["sort_order", "code"]


SYSTEM_STATUSES = [  # code, name_en, name_so, available, sort
    ("operational", "Operational", "Shaqeynaya", True, 10), ("under_maintenance", "Under maintenance", "Dayactir hoostiisa", False, 20),
    ("under_repair", "Under repair", "Hagaajin hoostiisa", False, 30), ("out_of_service", "Out of service", "Shaqada ka baxay", False, 40),
    ("awaiting_inspection", "Awaiting inspection", "Hubin sugaya", False, 50), ("decommissioned", "Decommissioned", "Laga saaray adeegga", False, 90),
]


class VehicleCounter(models.Model):
    """Single row that hands out Vehicle ID numbers (locked with SELECT ... FOR UPDATE), so IDs are never reused or duplicated."""

    name = models.CharField(max_length=20, primary_key=True)
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "vehicle_counters"


class Vehicle(models.Model):
    class Status(models.TextChoices):
        OPERATIONAL = "operational"
        UNDER_MAINTENANCE = "under_maintenance"
        UNDER_REPAIR = "under_repair"
        OUT_OF_SERVICE = "out_of_service"
        AWAITING_INSPECTION = "awaiting_inspection"
        DECOMMISSIONED = "decommissioned"

    class Condition(models.TextChoices):
        GOOD = "good"
        FAIR = "fair"
        POOR = "poor"
        UNSERVICEABLE = "unserviceable"
        UNKNOWN = "unknown"

    class PlateStatus(models.TextChoices):
        REGISTERED = "registered"
        NONE = "none"          # explicitly: this vehicle carries no plate
        UNKNOWN = "unknown"    # not yet established; never filled with an invented value

    UNAVAILABLE = ("under_maintenance", "under_repair", "out_of_service", "awaiting_inspection", "decommissioned")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle_id = models.CharField(max_length=20, unique=True, editable=False)
    plate = models.CharField(max_length=32, blank=True)
    plate_key = models.CharField(max_length=32, null=True, blank=True, editable=False)  # upper-case, no spaces/dashes
    plate_status = models.CharField(max_length=12, choices=PlateStatus.choices, default=PlateStatus.UNKNOWN)
    category = models.ForeignKey(VehicleCategory, on_delete=models.PROTECT, related_name="vehicles")
    vehicle_type = models.CharField(max_length=60, blank=True)
    make = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=60, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="vehicles")
    driver = models.ForeignKey("personnel.Personnel", null=True, blank=True, on_delete=models.PROTECT, related_name="driven_vehicles")
    custodian = models.ForeignKey("personnel.Personnel", null=True, blank=True, on_delete=models.PROTECT, related_name="vehicles_in_custody")
    location = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=30, default=Status.OPERATIONAL)  # a VehicleStatusType.code, validated by the services
    condition = models.CharField(max_length=14, choices=Condition.choices, default=Condition.UNKNOWN)
    acquired_on = models.DateField(null=True, blank=True)
    acquisition_ref = models.CharField(max_length=150, blank=True)
    notes = models.CharField(max_length=1000, blank=True)
    # Controlled disposal: proposed by one user (vehicles.dispose), approved by a different one (vehicles.approve).
    disposal_requested_at = models.DateTimeField(null=True, blank=True)
    disposal_requested_by = models.CharField(max_length=150, blank=True)
    disposal_reason = models.CharField(max_length=300, blank=True)
    disposal_authority_ref = models.CharField(max_length=150, blank=True)
    decommissioned_at = models.DateTimeField(null=True, blank=True)
    decommissioned_by = models.CharField(max_length=150, blank=True)
    legacy_asset = models.OneToOneField("logistics.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="vehicle_record")
    created_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vehicles"
        ordering = ["vehicle_id"]
        indexes = [models.Index(fields=["org_unit", "status"], name="vehicle_unit_status_idx"),
                   models.Index(fields=["category"], name="vehicle_category_idx")]
        constraints = [
            models.UniqueConstraint(fields=["plate_key"], condition=Q(plate_key__isnull=False), name="vehicle_unique_plate"),
            # One driver drives one vehicle at a time; a vehicle row never double-books a person.
            models.UniqueConstraint(fields=["driver"], condition=Q(driver__isnull=False), name="vehicle_one_vehicle_per_driver"),
            models.CheckConstraint(condition=Q(status="decommissioned", decommissioned_at__isnull=False) | ~Q(status="decommissioned"),
                                   name="vehicle_decommission_dated"),
            models.CheckConstraint(condition=Q(plate_status="registered", plate_key__isnull=False) | ~Q(plate_status="registered"),
                                   name="vehicle_registered_has_plate"),
        ]

    def delete(self, *args, **kwargs):  # history is kept: decommission instead of deleting (PostgreSQL also refuses it)
        raise AppendOnlyError("Vehicle register rows cannot be deleted.")



class VehicleEvent(AppendOnlyModel):
    class Kind(models.TextChoices):
        REGISTERED = "registered"
        UPDATED = "updated"
        UNIT_TRANSFER = "unit_transfer"
        DRIVER_CHANGE = "driver_change"
        CUSTODIAN_CHANGE = "custodian_change"
        STATUS_CHANGE = "status_change"
        LOCATION_CHANGE = "location_change"
        MAINTENANCE = "maintenance"
        DISPOSAL_PROPOSED = "disposal_proposed"
        DISPOSAL_REJECTED = "disposal_rejected"
        DECOMMISSIONED = "decommissioned"
        DOCUMENT = "document"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=300, blank=True)
    authority_ref = models.CharField(max_length=150, blank=True)  # order / handover note / approval reference
    effective_date = models.DateField(null=True, blank=True)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vehicle_events"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["vehicle", "kind", "-created_at"], name="vehevent_vehicle_kind_idx")]


class MaintenanceRecord(models.Model):
    class Kind(models.TextChoices):
        SERVICE = "service"
        REPAIR = "repair"
        INSPECTION = "inspection"

    class State(models.TextChoices):
        OPEN = "open"
        COMPLETED = "completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="maintenance")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)
    performed_on = models.DateField()
    reported_issue = models.CharField(max_length=500, blank=True)
    work_performed = models.CharField(max_length=1000, blank=True)
    workshop = models.CharField(max_length=150, blank=True)
    next_due_date = models.DateField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # visible only with vehicles.cost
    currency = models.CharField(max_length=3, blank=True)
    reference = models.CharField(max_length=150, blank=True)  # service report / receipt number
    created_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vehicle_maintenance"
        ordering = ["-performed_on", "-created_at"]
        indexes = [models.Index(fields=["vehicle", "next_due_date"], name="vehmaint_due_idx")]
        constraints = [models.CheckConstraint(condition=Q(cost__isnull=True) | Q(cost__gte=0), name="vehmaint_cost_nonneg")]

    def delete(self, *args, **kwargs):  # history is kept: decommission instead of deleting (PostgreSQL also refuses it)
        raise AppendOnlyError("Vehicle register rows cannot be deleted.")



class VehicleDocument(models.Model):
    """Registration papers, service reports, receipts. Bytes encrypted at rest; withdrawn, never deleted."""

    class Category(models.TextChoices):
        REGISTRATION = "registration"
        SERVICE_REPORT = "service_report"
        RECEIPT = "receipt"
        HANDOVER = "handover"
        INSPECTION = "inspection"
        OTHER = "other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="documents")
    maintenance = models.ForeignKey(MaintenanceRecord, null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    category = models.CharField(max_length=16, choices=Category.choices)
    title = models.CharField(max_length=150)
    content_enc = models.BinaryField()
    content_type = models.CharField(max_length=40)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by_username = models.CharField(max_length=150, blank=True)
    withdrawn_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "vehicle_documents"
        ordering = ["-uploaded_at"]

    def delete(self, *args, **kwargs):  # history is kept: decommission instead of deleting (PostgreSQL also refuses it)
        raise AppendOnlyError("Vehicle register rows cannot be deleted.")

