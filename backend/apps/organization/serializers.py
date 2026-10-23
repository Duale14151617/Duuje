from rest_framework import serializers

from apps.accounts import scope
from apps.core.concurrency import require_version, versioned_update

import re

from django.utils import timezone

from . import structure_changes
from .models import (DesignationRule, OrganizationalUnit, PlacementError, ServiceBranch, SpecialistDesignation,
                     StructureChange, UnitType)


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceBranch
        fields = ["id", "code", "name_en", "name_so", "active", "version"]
        read_only_fields = ["id", "version"]

    def update(self, instance, validated_data):
        expected = require_version(self.initial_data)
        return versioned_update(instance, validated_data, expected)


BRANCH_LEVEL_TYPES = {"TALISKA_GUUD", "QAYB"}


class UnitSerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(
        queryset=OrganizationalUnit.objects.all(), required=False, allow_null=True)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=ServiceBranch.objects.all(), required=False, allow_null=True)
    unit_type = serializers.PrimaryKeyRelatedField(queryset=UnitType.objects.all(), required=False, allow_null=True)
    designations = serializers.PrimaryKeyRelatedField(
        queryset=SpecialistDesignation.objects.all(), many=True, required=False)
    depth = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationalUnit
        fields = ["id", "code", "name_en", "name_so", "level", "parent", "branch", "unit_type", "designations",
                  "strength_exception_min", "strength_exception_max", "strength_exception_note",
                  "strength_exception_at", "depth", "active", "version", "created_at"]
        read_only_fields = ["id", "depth", "version", "created_at", "strength_exception_at"]
        extra_kwargs = {"code": {"validators": []}, "level": {"validators": []}}  # codes are reported by validate_code / validate()
        validators = []  # the one-headquarters rule is reported by validate() (hq_exists)

    def get_depth(self, obj):
        return obj.path.strip("/").count("/")  # HQ = 0, region = 1, ...

    def validate_code(self, value):
        if not value.replace("-", "").replace("_", "").isalnum():
            raise serializers.ValidationError("Letters, digits, - and _ only.", code="invalid_code")
        value = value.upper()
        clash = OrganizationalUnit.objects.filter(code=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("Code already in use.", code="code_taken")
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        if self.instance is None:
            parent = attrs.get("parent")
            # Creating under a parent requires org.manage covering that parent (server-side scope).
            if parent is not None and not scope.can(user, "org.manage", unit=parent):
                raise serializers.ValidationError({"parent": [
                    serializers.ErrorDetail("Parent is outside your scope.", code="out_of_scope")]})
            if parent is None and not scope.can(user, "org.manage"):
                raise serializers.ValidationError({"parent": [
                    serializers.ErrorDetail("Only headquarters administrators can do this.", code="out_of_scope")]})
            if attrs.get("level") == OrganizationalUnit.Level.HQ and \
                    OrganizationalUnit.objects.filter(level=OrganizationalUnit.Level.HQ).exists():
                raise serializers.ValidationError({"level": [
                    serializers.ErrorDetail("Headquarters already exists.", code="hq_exists")]})
            try:
                from .models import check_placement
                attrs["branch"] = check_placement(attrs.get("level"), parent, attrs.get("branch"))
            except PlacementError as exc:
                raise serializers.ValidationError({"level": [serializers.ErrorDetail("Invalid placement.", code=exc.code)]})
        else:
            for locked in ("parent", "level", "branch"):
                if locked in attrs and attrs[locked] != getattr(self.instance, locked):
                    raise serializers.ValidationError({locked: [
                        serializers.ErrorDetail("Cannot be changed after creation.", code="immutable_field")]})
            if attrs.get("active") is False and self.instance.children.filter(active=True).exists():
                raise serializers.ValidationError({"active": [
                    serializers.ErrorDetail("Deactivate child units first.", code="has_active_children")]})
        self._validate_template(attrs)
        return attrs

    # --- organizational template (unit type, designations, approved strength exception) -----------------------
    @staticmethod
    def _fail(field, code, message="Invalid."):
        return serializers.ValidationError({field: [serializers.ErrorDetail(message, code=code)]})

    def _validate_template(self, attrs):
        inst = self.instance
        level = attrs.get("level") or (inst.level if inst else None)
        parent = attrs.get("parent") if inst is None else inst.parent
        utype = attrs["unit_type"] if "unit_type" in attrs else (inst.unit_type if inst else None)
        if utype is not None:
            if not utype.active and (inst is None or inst.unit_type_id != utype.pk):
                raise self._fail("unit_type", "unit_type_inactive")
            # Taliska Guud (Army headquarters) and Qayb (regional command) are commands at branch-command level; Qayb may
            # also be a nested unit (older structures). Every other level of the template is a unit.
            on_branch = level == OrganizationalUnit.Level.BRANCH
            if on_branch and utype.code not in BRANCH_LEVEL_TYPES or not on_branch and utype.code == "TALISKA_GUUD":
                raise self._fail("unit_type", "unit_type_level_mismatch")
            if parent is not None and parent.unit_type_id and parent.unit_type.tier >= utype.tier:
                raise self._fail("unit_type", "unit_type_tier_order")  # a Qayb cannot sit below a Koox, etc.
            if inst is not None:
                shallowest = inst.children.filter(unit_type__isnull=False).order_by("unit_type__tier").first()
                if shallowest is not None and shallowest.unit_type.tier <= utype.tier:
                    raise self._fail("unit_type", "unit_type_tier_order")
        if attrs.get("designations") and level != OrganizationalUnit.Level.UNIT:
            raise self._fail("designations", "designation_level_mismatch")
        for d in attrs.get("designations") or []:
            if not d.active and (inst is None or not inst.designations.filter(pk=d.pk).exists()):
                raise self._fail("designations", "designation_inactive")
        lo = attrs["strength_exception_min"] if "strength_exception_min" in attrs else (inst.strength_exception_min if inst else None)
        hi = attrs["strength_exception_max"] if "strength_exception_max" in attrs else (inst.strength_exception_max if inst else None)
        note = attrs["strength_exception_note"] if "strength_exception_note" in attrs else (inst.strength_exception_note if inst else "")
        if lo is not None or hi is not None:
            if lo is not None and hi is not None and hi < lo:
                raise self._fail("strength_exception_max", "range_order")
            if not (note or "").strip():
                raise self._fail("strength_exception_note", "exception_note_required")  # who accepted it, and why
        elif "strength_exception_note" in attrs and (attrs["strength_exception_note"] or "").strip():
            raise self._fail("strength_exception_min", "exception_range_required")  # a note with no range

    def _exception_changes(self, data, current=None):
        """Stamp who recorded or cleared an exception, and when."""
        keys = ("strength_exception_min", "strength_exception_max", "strength_exception_note")
        if not any(k in data for k in keys):
            return {}
        changes = {k: data[k] for k in keys if k in data}
        merged = {k: changes.get(k, getattr(current, k) if current else None) for k in keys}
        if merged["strength_exception_min"] is None and merged["strength_exception_max"] is None:
            changes.update(strength_exception_note="", strength_exception_by=None, strength_exception_at=None)
        else:
            changes.update(strength_exception_by=self.context["request"].user, strength_exception_at=timezone.now())
        return changes

    def create(self, validated_data):
        designations = validated_data.pop("designations", [])
        validated_data.update(self._exception_changes(validated_data))
        unit = super().create(validated_data)
        if designations:
            unit.designations.set(designations)
        return unit

    def update(self, instance, validated_data):
        expected = require_version(self.initial_data)
        allowed = ("code", "name_en", "name_so", "active", "unit_type", "strength_exception_min",
                   "strength_exception_max", "strength_exception_note")
        changes = {k: v for k, v in validated_data.items() if k in allowed}
        changes.update(self._exception_changes(validated_data, instance))
        designations = validated_data.get("designations")
        unit = versioned_update(instance, changes, expected)
        if designations is not None:
            unit.designations.set(designations)
        return unit


class UnitTypeSerializer(serializers.ModelSerializer):
    parent_type = serializers.PrimaryKeyRelatedField(queryset=UnitType.objects.all(), required=False, allow_null=True)

    class Meta:
        model = UnitType
        fields = ["id", "code", "name_en", "name_so", "tier", "parent_type", "standard_per_parent", "reference_min",
                  "reference_max", "description_en", "description_so", "active", "version"]
        read_only_fields = ["id", "version"]
        extra_kwargs = {"code": {"validators": []}}
        validators = []

    def validate_code(self, value):
        value = value.strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9_]{1,31}$", value):
            raise serializers.ValidationError("Letters, digits and _ only.", code="invalid_code")
        if UnitType.objects.filter(code=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("Code already in use.", code="code_taken")
        return value

    def validate(self, attrs):
        inst = self.instance
        if inst is not None and "code" in attrs and attrs["code"] != inst.code:
            raise self._f("code", "immutable_field")
        get = lambda k: attrs[k] if k in attrs else (getattr(inst, k) if inst else None)  # noqa: E731
        lo, hi = get("reference_min"), get("reference_max")
        if lo is not None and hi is not None and hi < lo:
            raise self._f("reference_max", "range_order")
        parent = get("parent_type")
        if parent is not None and (parent.tier >= (get("tier") or 0) or (inst is not None and parent.pk == inst.pk)):
            raise self._f("parent_type", "tier_order")
        if inst is not None and attrs.get("active") is False and inst.units.filter(active=True).exists():
            raise self._f("active", "type_in_use")
        return attrs

    @staticmethod
    def _f(field, code):
        return serializers.ValidationError({field: [serializers.ErrorDetail("Invalid.", code=code)]})

    def update(self, instance, validated_data):
        return versioned_update(instance, validated_data, require_version(self.initial_data))


class DesignationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpecialistDesignation
        fields = ["id", "code", "name_en", "name_so", "description_en", "description_so", "active", "version"]
        read_only_fields = ["id", "version"]
        extra_kwargs = {"code": {"validators": []}}

    def validate_code(self, value):
        value = value.strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9_]{1,31}$", value):
            raise serializers.ValidationError("Letters, digits and _ only.", code="invalid_code")
        if SpecialistDesignation.objects.filter(code=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("Code already in use.", code="code_taken")
        return value

    def validate(self, attrs):
        inst = self.instance
        if inst is not None:
            if "code" in attrs and attrs["code"] != inst.code:
                raise serializers.ValidationError({"code": [serializers.ErrorDetail("Invalid.", code="immutable_field")]})
            if attrs.get("active") is False and inst.units.filter(active=True).exists():
                raise serializers.ValidationError({"active": [serializers.ErrorDetail("Invalid.", code="designation_in_use")]})
        return attrs

    def update(self, instance, validated_data):
        return versioned_update(instance, validated_data, require_version(self.initial_data))


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DesignationRule
        fields = ["id", "parent_type", "child_type", "designation", "active", "note", "version"]
        read_only_fields = ["id", "version"]
        validators = []

    def validate(self, attrs):
        inst = self.instance
        if inst is not None:
            for k in ("parent_type", "child_type", "designation"):
                if k in attrs and attrs[k] != getattr(inst, k):
                    raise serializers.ValidationError({k: [serializers.ErrorDetail("Invalid.", code="immutable_field")]})
            return attrs
        if attrs["parent_type"].tier >= attrs["child_type"].tier:
            raise serializers.ValidationError({"child_type": [serializers.ErrorDetail("Invalid.", code="tier_order")]})
        if DesignationRule.objects.filter(parent_type=attrs["parent_type"], child_type=attrs["child_type"],
                                          designation=attrs["designation"]).exists():
            raise serializers.ValidationError({"designation": [serializers.ErrorDetail("Invalid.", code="rule_exists")]})
        return attrs

    def update(self, instance, validated_data):
        return versioned_update(instance, validated_data, require_version(self.initial_data))


class StructureChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StructureChange
        fields = ["id", "title", "rationale", "operations", "impact", "status", "proposed_by_username", "submitted_at",
                  "decided_by_username", "decided_at", "decision_note", "version", "created_at"]
        read_only_fields = ["id", "impact", "status", "proposed_by_username", "submitted_at", "decided_by_username",
                            "decided_at", "decision_note", "version", "created_at"]

    def validate_title(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Title is too short.", code="title_too_short")
        return value

    def validate_operations(self, value):
        return structure_changes.normalize(value)

    def create(self, validated_data):
        user = self.context["request"].user
        impact = structure_changes.evaluate(validated_data["operations"])
        return StructureChange.objects.create(proposed_by=user, proposed_by_username=user.username, impact=impact, **validated_data)

    def update(self, instance, validated_data):
        expected = require_version(self.initial_data)
        if instance.status != StructureChange.Status.DRAFT:
            raise serializers.ValidationError({"status": [serializers.ErrorDetail("Only a draft can be edited.", code="not_a_draft")]})
        if "operations" in validated_data:
            validated_data["impact"] = structure_changes.evaluate(validated_data["operations"])
        return versioned_update(instance, validated_data, expected)
