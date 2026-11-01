"""Inbound integration clients (2.0). A client is a machine credential that can read *aggregate analytics only*,
inside one organizational subtree, for a limited time. Only a hash of the key is stored."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.appendonly import AppendOnlyModel


class IntegrationClient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    key_prefix = models.CharField(max_length=12, unique=True)  # public identifier: ahq_<prefix>_<secret>
    key_hash = models.CharField(max_length=64, editable=False)  # SHA-256 of the full key (256-bit random secret)
    scopes = models.JSONField(default=list)                       # analytics sections this client may read
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    expires_at = models.DateTimeField()
    active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by_username = models.CharField(max_length=150, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "integration_clients"
        ordering = ["name", "id"]

    def __str__(self):
        return self.key_prefix

    def unusable_reason(self, now=None):
        now = now or timezone.now()
        if self.revoked_at is not None or not self.active:
            return "key_revoked"
        if self.expires_at <= now:
            return "key_expired"
        return None


class IntegrationCall(AppendOnlyModel):
    """One row per authenticated call (metadata only: never parameters' values beyond the endpoint, never data)."""

    class Outcome(models.TextChoices):
        SUCCESS = "success"
        DENIED = "denied"
        THROTTLED = "throttled"
        ERROR = "error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(IntegrationClient, on_delete=models.PROTECT, related_name="calls")
    at = models.DateTimeField(default=timezone.now)
    endpoint = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    correlation_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "integration_calls"
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["client", "-at"], name="intcall_client_at_idx")]
