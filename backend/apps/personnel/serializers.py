from datetime import date

from rest_framework import serializers

from apps.accounts import scope
from apps.accounts.serializers import BranchBriefSerializer, UnitBriefSerializer
from apps.core.concurrency import require_version, versioned_update
from apps.organization.models import OrganizationalUnit
from apps.ranks.models import Rank

from . import services as svc
from .models import Personnel, PersonnelHistory


def fail(field, code, message="Invalid."):
    return serializers.ValidationError({field: [serializers.ErrorDetail(message, code=code)]})


class RankBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rank
        fields = ["id", "code", "name_en", "name_so", "approval_status"]


class PersonnelSerializer(serializers.ModelSerializer):
    branch = BranchBriefSerializer(read_only=True)
    org_unit = UnitBriefSerializer(read_only=True)
    rank = RankBriefSerializer(read_only=True)

    class Meta:
        model = Personnel
        fields = ["id", "service_number", "full_name", "phone", "branch", "org_unit", "rank", "status",
                  "version", "created_at", "updated_at"]
        read_only_fields = fields


class HistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonnelHistory
        fields = ["id", "field", "old_label", "new_label", "effective_date", "reason", "recorded_at",
                  "recorded_by_username"]
        read_only_fields = fields


class _Basics(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=24, required=False, allow_blank=True)
    service_number = serializers.CharField(max_length=32, required=False, allow_blank=True, allow_null=True)

    def validate_phone(self, value):
        if value and not svc.PHONE_RE.match(value):
            raise serializers.ValidationError("Invalid phone number.", code="phone_invalid")
        return value

    def validate_service_number(self, value):
        value = (value or "").strip()
        if value and not svc.SERVICE_NO_RE.match(value):
            raise serializers.ValidationError("Invalid service number.", code="service_number_invalid")
        return value or None


class PersonnelCreateSerializer(_Basics):
    org_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.all())
    rank = serializers.PrimaryKeyRelatedField(queryset=Rank.objects.all())
    status = serializers.ChoiceField(choices=sorted(svc.STATUSES), default="active")
    effective_date = serializers.DateField(required=False, allow_null=True)
    confirm_duplicate = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        user = self.context["request"].user
        unit = attrs["org_unit"]
        if not scope.can(user, "personnel.manage", unit=unit):
            raise fail("org_unit", "out_of_scope")
        try:
            svc.check_assignment(unit, attrs["rank"])
        except svc.RuleError as exc:
            raise fail(exc.field, exc.code)
        if attrs.get("effective_date") and attrs["effective_date"] > date.today():
            raise fail("effective_date", "future_date")
        if svc.service_number_taken(attrs.get("service_number")):
            raise fail("service_number", "service_number_taken")
        found = svc.duplicate_check(svc.normalize_name(attrs["full_name"]), svc.normalize_phone(attrs.get("phone")), unit)
        self._enforce_duplicate(found, attrs)
        return attrs

    def _enforce_duplicate(self, found, attrs):
        """A serving person in another service is blocked outright (confirm_duplicate cannot override); other matches are flags."""
        if found == "duplicate_identity":
            svc.audit_denied_duplicate(self.context["request"], "cross_service")
            raise fail("full_name", "duplicate_identity")
        if found and not attrs.get("confirm_duplicate"):
            raise fail("full_name", found)


class PersonnelUpdateSerializer(_Basics):
    full_name = serializers.CharField(max_length=150, required=False)
    confirm_duplicate = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        p = self.instance
        if svc.service_number_taken(attrs.get("service_number"), exclude_pk=p.pk):
            raise fail("service_number", "service_number_taken")
        name = attrs.get("full_name", p.full_name)
        phone = attrs.get("phone", p.phone)
        changed = "full_name" in attrs or "phone" in attrs
        if changed:
            found = svc.duplicate_check(svc.normalize_name(name), svc.normalize_phone(phone), p.org_unit, exclude_pk=p.pk)
            if found == "duplicate_identity":
                svc.audit_denied_duplicate(self.context["request"], "cross_service")
                raise fail("full_name", "duplicate_identity")
            if found and not attrs.get("confirm_duplicate"):
                raise fail("full_name", found)
        return attrs

    def update(self, instance, validated_data):
        expected = require_version(self.initial_data)
        validated_data.pop("confirm_duplicate", None)
        changes = dict(validated_data)
        if "full_name" in changes:
            changes["name_key"] = svc.normalize_name(changes["full_name"])
        if "phone" in changes:
            changes["phone_key"] = svc.normalize_phone(changes["phone"])
        return versioned_update(instance, changes, expected)


class _Workflow(serializers.Serializer):
    effective_date = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate_effective_date(self, value):
        if value and value > date.today():
            raise serializers.ValidationError("Future-dated changes are not supported.", code="future_date")
        return value


class TransferSerializer(_Workflow):
    org_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.all())

    def validate(self, attrs):
        user, p, unit = self.context["request"].user, self.instance, attrs["org_unit"]
        if unit.pk == p.org_unit_id:
            raise fail("org_unit", "no_change")
        if not scope.can(user, "personnel.manage", unit=unit):
            raise fail("org_unit", "out_of_scope")
        if unit.branch_id != p.branch_id:
            raise fail("org_unit", "branch_change_not_supported")
        try:
            svc.check_assignment(unit, p.rank)
        except svc.RuleError as exc:
            raise fail(exc.field if exc.field != "rank" else "org_unit", exc.code)
        return attrs


class RankChangeSerializer(_Workflow):
    rank = serializers.PrimaryKeyRelatedField(queryset=Rank.objects.all())

    def validate(self, attrs):
        p, rank = self.instance, attrs["rank"]
        if rank.pk == p.rank_id:
            raise fail("rank", "no_change")
        try:
            svc.check_assignment(p.org_unit, rank)
        except svc.RuleError as exc:
            raise fail("rank" if exc.field == "rank" else exc.field, exc.code)
        return attrs


class StatusChangeSerializer(_Workflow):
    status = serializers.ChoiceField(choices=sorted(svc.STATUSES))

    def validate(self, attrs):
        if attrs["status"] == self.instance.status:
            raise fail("status", "no_change")
        return attrs
