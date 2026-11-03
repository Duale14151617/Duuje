import uuid

from django.db import models
from django.utils import timezone


class AuditImmutableError(Exception):
    pass


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditImmutableError("Audit events cannot be modified.")

    def delete(self):
        raise AuditImmutableError("Audit events cannot be deleted.")

    def bulk_update(self, *args, **kwargs):
        raise AuditImmutableError("Audit events cannot be modified.")


class AuditEvent(models.Model):
    """Append-only. Enforced in Python here and by a PostgreSQL trigger (migration 0002)."""

    class Outcome(models.TextChoices):
        SUCCESS = "success"
        FAILURE = "failure"
        DENIED = "denied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        db_table = "audit_events"
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["entity_type", "entity_id"], name="audit_entity_idx")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditImmutableError("Audit events cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditImmutableError("Audit events cannot be deleted.")
