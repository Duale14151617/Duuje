from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from apps.accounts import scope
from apps.analytics.services import SECTION_PERMISSION, SECTIONS
from apps.core.concurrency import require_version, versioned_update
from apps.core.errors import field_error
from apps.organization.models import OrganizationalUnit

from .models import IntegrationCall, IntegrationClient


class IntegrationClientSerializer(serializers.ModelSerializer):
    org_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.filter(active=True))
    org_unit_code = serializers.CharField(source="org_unit.code", read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationClient
        fields = ["id", "name", "description", "key_prefix", "scopes", "org_unit", "org_unit_code", "expires_at",
                  "status", "revoked_at", "last_used_at", "created_by_username", "version", "created_at"]
        read_only_fields = ["id", "key_prefix", "revoked_at", "last_used_at", "created_by_username", "version", "created_at"]

    def get_status(self, obj):
        return obj.unusable_reason(timezone.now()) or "active"

    def validate_name(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Name is too short.", code="name_too_short")
        return value

    def validate_scopes(self, value):
        if not isinstance(value, list) or not value or len(set(value)) != len(value) or any(v not in SECTIONS for v in value):
            raise serializers.ValidationError("Choose one or more valid sections.", code="invalid_scope")
        return value

    def validate_expires_at(self, value):
        now = timezone.now()
        if value <= now + timedelta(minutes=1):
            raise serializers.ValidationError("Expiry must be in the future.", code="expiry_invalid")
        if value > now + timedelta(days=settings.INTEGRATION_MAX_DAYS):
            raise serializers.ValidationError("Expiry is too far ahead.", code="expiry_too_far")
        return value

    def validate(self, attrs):
        inst = self.instance
        if inst is not None and inst.unusable_reason() == "key_revoked":
            raise field_error("name", "client_revoked", "A revoked client cannot be changed.")
        user = self.context["request"].user
        if inst is None:
            for required in ("name", "scopes", "org_unit", "expires_at"):
                if required not in attrs:
                    raise field_error(required, "required", "This field is required.")
        if "scopes" in attrs or "org_unit" in attrs:
            scopes = attrs.get("scopes", inst.scopes if inst else [])
            unit = attrs.get("org_unit", inst.org_unit if inst else None)
            # No privilege amplification: you cannot hand a machine access you do not hold yourself.
            for section in scopes:
                if not scope.can(user, SECTION_PERMISSION[section], unit=unit):
                    raise field_error("scopes", "scope_not_held", "You do not hold that access for this unit.")
        return attrs

    def update(self, instance, validated_data):
        expected = require_version(self.initial_data)
        return versioned_update(instance, validated_data, expected)


class IntegrationCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationCall
        fields = ["id", "at", "endpoint", "status_code", "outcome", "correlation_id", "ip_address"]
