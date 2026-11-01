import uuid

from django.conf import settings
from django.db import models


class Rank(models.Model):
    """Service-specific rank catalogue. Entries stay DRAFT until institutionally approved."""

    class Category(models.TextChoices):
        ENLISTED = "enlisted"
        WARRANT = "warrant"
        OFFICER = "officer"
        UNSPECIFIED = "unspecified"  # the official Puntland Army list is not split into these classes
        # Police classes from Article 23 (Order of Precedence), Law No. 2 of 23 Dec 1972 - historical baseline only.
        GENERAL_OFFICER = "general_officer"
        SENIOR_OFFICER = "senior_officer"
        JUNIOR_OFFICER = "junior_officer"
        INSPECTOR = "inspector"
        NCO = "nco"
        ASKARI = "askari"

    class Approval(models.TextChoices):
        DRAFT = "draft"
        APPROVED = "approved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey("organization.ServiceBranch", on_delete=models.PROTECT, related_name="ranks")
    category = models.CharField(max_length=16, choices=Category.choices)
    code = models.CharField(max_length=16)
    name_en = models.CharField(max_length=100)
    name_so = models.CharField(max_length=100, blank=True)
    # Order of precedence inside the service: HIGHER = MORE SENIOR (Army: 1 = Dable ... 18 = President). Reporting lines
    # (Personnel.supervisor) rely on it. Retired ranks are inactive and parked at 1000+, and are never compared.
    sort_order = models.PositiveSmallIntegerField(default=0)
    approval_status = models.CharField(max_length=10, choices=Approval.choices, default=Approval.DRAFT)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ranks"
        ordering = ["branch__code", "sort_order"]
        constraints = [models.UniqueConstraint(fields=["branch", "code"], name="rank_unique_code_per_branch")]

    def __str__(self):
        return f"{self.branch_id}:{self.code}"
