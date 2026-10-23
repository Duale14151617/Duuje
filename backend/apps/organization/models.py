import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ServiceBranch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name_en = models.CharField(max_length=100)
    name_so = models.CharField(max_length=100, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "service_branches"
        ordering = ["name_en"]

    def __str__(self):
        return self.code


class UnitType(models.Model):
    """Organizational template entry (Taliska Guud, Qayb, Gaas, Guuto, Urur, Horin, Koox, Unug), kept in the database.

    Reference strengths are *establishment figures for comparison*, never constraints: no check blocks a unit
    that is above or below them, and nothing creates personnel to fill a gap.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name_en = models.CharField(max_length=100)
    name_so = models.CharField(max_length=100, blank=True)
    tier = models.PositiveSmallIntegerField(help_text="Position in the standard hierarchy; 1 is the highest.")
    parent_type = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="child_types")
    standard_per_parent = models.PositiveSmallIntegerField(null=True, blank=True)  # e.g. two Gaas under each Qayb
    reference_min = models.PositiveIntegerField(null=True, blank=True)
    reference_max = models.PositiveIntegerField(null=True, blank=True)
    description_en = models.CharField(max_length=200, blank=True)
    description_so = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "unit_types"
        ordering = ["tier", "code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(reference_min__isnull=True) | Q(reference_max__isnull=True)
                | Q(reference_max__gte=models.F("reference_min")), name="unit_type_ref_range_ordered"),
        ]

    def __str__(self):
        return self.code


class SpecialistDesignation(models.Model):
    """Specialist designation of a unit (Sahan = reconnaissance, Sanco = miino baar / bomb squad). Not a rank."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name_en = models.CharField(max_length=100)
    name_so = models.CharField(max_length=100, blank=True)
    description_en = models.CharField(max_length=200, blank=True)
    description_so = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "specialist_designations"
        ordering = ["code"]

    def __str__(self):
        return self.code


class DesignationRule(models.Model):
    """Expected relationship: every `parent_type` unit should have a `child_type` unit below it carrying
    `designation` (for example every Guuto has a Horin Sahan). Checked and reported, never enforced."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_type = models.ForeignKey(UnitType, on_delete=models.PROTECT, related_name="+")
    child_type = models.ForeignKey(UnitType, on_delete=models.PROTECT, related_name="+")
    designation = models.ForeignKey(SpecialistDesignation, on_delete=models.PROTECT, related_name="rules")
    active = models.BooleanField(default=True)
    note = models.CharField(max_length=300, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "designation_rules"
        ordering = ["parent_type__tier", "child_type__tier", "designation__code"]
        constraints = [models.UniqueConstraint(fields=["parent_type", "child_type", "designation"],
                                               name="designation_rule_unique")]


class PlacementError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class OrganizationalUnit(models.Model):
    """Configurable hierarchy: HQ -> region -> branch command -> unit (units may nest); Police commands may also hold stations."""

    class Level(models.TextChoices):
        HQ = "headquarters"
        REGION = "region"
        BRANCH = "branch_command"
        UNIT = "unit"
        STATION = "station"  # Police station: sits directly under a regional Police command and holds personnel

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    name_en = models.CharField(max_length=150)
    name_so = models.CharField(max_length=150, blank=True)
    level = models.CharField(max_length=20, choices=Level.choices)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    branch = models.ForeignKey(ServiceBranch, null=True, blank=True, on_delete=models.PROTECT, related_name="units")
    # Materialised path of ids ("/<hq>/<region>/..."), used for subtree scope checks.
    path = models.CharField(max_length=1000, editable=False)
    unit_type = models.ForeignKey(UnitType, null=True, blank=True, on_delete=models.PROTECT, related_name="units")
    designations = models.ManyToManyField(SpecialistDesignation, blank=True, related_name="units")
    # Approved exception to the reference strength (a variation the institution has accepted). Optional, never required.
    strength_exception_min = models.PositiveIntegerField(null=True, blank=True)
    strength_exception_max = models.PositiveIntegerField(null=True, blank=True)
    strength_exception_note = models.CharField(max_length=300, blank=True)
    strength_exception_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                              on_delete=models.SET_NULL, related_name="+")
    strength_exception_at = models.DateTimeField(null=True, blank=True)
    # Confidential unit (e.g. CID). Records in it (and in units below it) are visible only to roles holding `cid.access`,
    # whatever the rest of their scope is. Enforced server-side in apps/accounts/scope.py.
    restricted = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizational_units"
        ordering = ["path"]
        indexes = [models.Index(fields=["path"], name="org_unit_path_idx", opclasses=["varchar_pattern_ops"])]
        constraints = [
            models.UniqueConstraint(fields=["level"], condition=Q(level="headquarters"), name="org_single_hq"),
            models.CheckConstraint(
                condition=(Q(level="headquarters", parent__isnull=True)
                           | (~Q(level="headquarters") & Q(parent__isnull=False))),
                name="org_parent_by_level",
            ),
            models.CheckConstraint(
                condition=~Q(level="branch_command") | Q(branch__isnull=False),
                name="org_branch_cmd_has_branch",
            ),
        ]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.branch = check_placement(self.level, self.parent, self.branch)
            base = self.parent.path if self.parent else "/"
            self.path = f"{base}{self.pk.hex}/"
        super().save(*args, **kwargs)


def check_placement(level, parent, branch):
    """Validate where a unit may sit. Returns the effective branch."""
    L = OrganizationalUnit.Level
    if level == L.HQ:
        if parent is not None:
            raise PlacementError("hq_has_no_parent")
        if branch is not None:
            raise PlacementError("hq_has_no_branch")
        return None
    if parent is None:
        raise PlacementError("parent_required")
    if level == L.REGION:
        if parent.level != L.HQ:
            raise PlacementError("region_parent_must_be_hq")
        if branch is not None:
            raise PlacementError("region_has_no_branch")
        return None
    if level == L.BRANCH:
        if branch is None:
            raise PlacementError("branch_required")
        # The Army headquarters (Taliska Guud) is an Army command directly under the system headquarters; every other
        # branch command (and all Police/Navy commands) still sits under a region exactly as before.
        if parent.level == L.HQ and branch.code == "ARMY":
            return branch
        if parent.level != L.REGION:
            raise PlacementError("branch_parent_must_be_region")
        return branch
    if level == L.UNIT:
        if parent.level not in (L.BRANCH, L.UNIT):
            raise PlacementError("unit_parent_invalid")
        return parent.branch  # units inherit the service branch of their parent
    if level == L.STATION:
        # Stations exist only under a regional Police command (never under Army/Navy, never under another unit).
        if parent.level != L.BRANCH or parent.branch is None or parent.branch.code != "POLICE":
            raise PlacementError("station_parent_must_be_police_command")
        return parent.branch
    raise PlacementError("invalid_level")


class StructureChange(models.Model):
    """A proposed change to the unit-type catalogue (level names, order, parent/child links, strength standards).

    Nothing in a proposal touches live structure until a different person approves it; approval applies it in one
    transaction. The operations are data (validated, never executed as code)."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        SUBMITTED = "submitted"
        APPROVED = "approved"   # approved and applied atomically
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    rationale = models.TextField(blank=True)
    operations = models.JSONField(default=list)
    impact = models.JSONField(default=dict, blank=True)  # last computed impact report (errors, counts)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    proposed_by_username = models.CharField(max_length=150, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_by_username = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "structure_changes"
        ordering = ["-created_at", "id"]
