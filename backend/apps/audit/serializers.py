from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id", "occurred_at", "actor_id", "actor_username", "action", "entity_type",
            "entity_id", "outcome", "correlation_id", "ip_address", "metadata",
        ]
        read_only_fields = fields
