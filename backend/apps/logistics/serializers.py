from rest_framework import serializers

from apps.accounts.serializers import UnitBriefSerializer
from apps.core.concurrency import require_version, versioned_update
from apps.organization.models import OrganizationalUnit

from .models import (Asset, AssetEvent, InventoryCategory, Reconciliation, ReconciliationLine, StockLine,
                     StockTransaction)


def fail(field, code, message="Invalid."):
    return serializers.ValidationError({field: [serializers.ErrorDetail(message, code=code)]})


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryCategory
        fields = ["id", "code", "name_en", "name_so", "kind", "restricted", "approval_status", "approved_at", "active", "version"]
        read_only_fields = ["id", "approval_status", "approved_at", "version"]

    def validate_code(self, value):
        value = value.strip().lower()
        if not value.replace("_", "").isalnum():
            raise serializers.ValidationError("Letters, digits and _ only.", code="invalid_code")
        clash = InventoryCategory.objects.filter(code=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("Code already in use.", code="code_taken")
        return value

    def validate(self, attrs):
        if self.instance is not None:
            for locked in ("kind", "restricted", "code"):
                if locked in attrs and attrs[locked] != getattr(self.instance, locked):
                    raise fail(locked, "immutable_field")
        return attrs

    def update(self, instance, validated_data):
        changes = {k: v for k, v in validated_data.items() if k in ("name_en", "name_so", "active")}
        # Renaming an approved category sends it back for review.
        if instance.approval_status == "approved" and any(k in changes and changes[k] != getattr(instance, k) for k in ("name_en", "name_so")):
            changes.update(approval_status="draft", approved_by=None, approved_at=None)
        return versioned_update(instance, changes, require_version(self.initial_data))


class CategoryBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryCategory
        fields = ["id", "code", "name_en", "name_so", "kind", "restricted"]


class StockLineSerializer(serializers.ModelSerializer):
    category = CategoryBriefSerializer(read_only=True)
    org_unit = UnitBriefSerializer(read_only=True)
    below_reorder = serializers.SerializerMethodField()

    class Meta:
        model = StockLine
        fields = ["id", "category", "org_unit", "uom", "quantity", "reorder_level", "below_reorder", "version", "updated_at"]
        read_only_fields = fields

    def get_below_reorder(self, obj):
        return obj.reorder_level > 0 and obj.quantity <= obj.reorder_level


class StockLineCreateSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=InventoryCategory.objects.all())
    org_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.all())
    uom = serializers.CharField(max_length=16, required=False, allow_blank=True)
    reorder_level = serializers.IntegerField(min_value=0, max_value=10**9, required=False, default=0)


class StockLinePatchSerializer(serializers.Serializer):
    reorder_level = serializers.IntegerField(min_value=0, max_value=10**9)
    uom = serializers.CharField(max_length=16, required=False)


class TransactionInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["receive", "issue", "adjust"])
    quantity = serializers.IntegerField(min_value=-10**9, max_value=10**9)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)
    expected_balance = serializers.IntegerField(min_value=0, required=False)

    def validate(self, attrs):
        q, kind = attrs["quantity"], attrs["kind"]
        if q == 0:
            raise fail("quantity", "quantity_invalid")
        if kind in ("receive", "issue") and q < 0:
            raise fail("quantity", "quantity_invalid")
        if kind == "adjust" and not attrs.get("reason", "").strip():
            raise fail("reason", "reason_required")
        attrs["delta"] = -q if kind == "issue" else q
        return attrs


class TransferInputSerializer(serializers.Serializer):
    to_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.all())
    quantity = serializers.IntegerField(min_value=1, max_value=10**9)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)


class StockTransactionSerializer(serializers.ModelSerializer):
    counterpart_unit = UnitBriefSerializer(read_only=True)

    class Meta:
        model = StockTransaction
        fields = ["id", "kind", "delta", "balance_after", "reason", "counterpart_unit", "external_ref", "authority_ref",
                  "actor_username", "correlation_id", "created_at"]
        read_only_fields = fields


class AssetSerializer(serializers.ModelSerializer):
    category = CategoryBriefSerializer(read_only=True)
    org_unit = UnitBriefSerializer(read_only=True)
    issued_to_unit = UnitBriefSerializer(read_only=True)
    custodian_username = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = ["id", "category", "org_unit", "identifier", "description", "status", "issued_to_unit",
                  "custodian_username", "version", "updated_at"]
        read_only_fields = fields

    def get_custodian_username(self, obj):
        return obj.custodian.username if obj.custodian_id else None


class AssetCreateSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=InventoryCategory.objects.all())
    org_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.all())
    identifier = serializers.CharField(max_length=64)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class AssetChangeSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["issue", "return", "maintenance", "restore", "missing", "lost", "retire", "transfer"])
    to_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.all(), required=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class AssetEventSerializer(serializers.ModelSerializer):
    from_unit = UnitBriefSerializer(read_only=True)
    to_unit = UnitBriefSerializer(read_only=True)

    class Meta:
        model = AssetEvent
        fields = ["id", "kind", "from_status", "to_status", "from_unit", "to_unit", "note", "actor_username", "created_at"]
        read_only_fields = fields


class ReconLineSerializer(serializers.ModelSerializer):
    kind = serializers.SerializerMethodField()

    class Meta:
        model = ReconciliationLine
        fields = ["id", "kind", "label", "expected_quantity", "counted_quantity", "found"]

    def get_kind(self, obj):
        return "stock" if obj.stock_line_id else "asset"


class ReconciliationSerializer(serializers.ModelSerializer):
    org_unit = UnitBriefSerializer(read_only=True)
    started_by_username = serializers.SerializerMethodField()

    class Meta:
        model = Reconciliation
        fields = ["id", "org_unit", "status", "includes_restricted", "notes", "started_by_username", "started_at",
                  "completed_at", "version"]
        read_only_fields = fields

    def get_started_by_username(self, obj):
        return obj.started_by.username if obj.started_by_id else None


class ReconciliationDetailSerializer(ReconciliationSerializer):
    lines = ReconLineSerializer(many=True, read_only=True)

    class Meta(ReconciliationSerializer.Meta):
        fields = ReconciliationSerializer.Meta.fields + ["lines"]
        read_only_fields = fields
