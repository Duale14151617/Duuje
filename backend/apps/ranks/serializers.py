import re

from rest_framework import serializers

from apps.core.concurrency import require_version, versioned_update

from .models import Rank

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,15}$")
IDENTITY_FIELDS = ("code", "category", "name_en", "name_so")


class RankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rank
        fields = ["id", "branch", "category", "code", "name_en", "name_so", "sort_order",
                  "approval_status", "approved_at", "active", "version"]
        read_only_fields = ["id", "approval_status", "approved_at", "version"]
        validators = []  # uniqueness handled in validate() so the error code is stable

    def validate_code(self, value):
        value = value.strip().upper()
        if not CODE_RE.match(value):
            raise serializers.ValidationError("Use letters, digits and -.", code="invalid_code")
        return value

    def validate(self, attrs):
        if self.instance is not None and "branch" in attrs and attrs["branch"] != self.instance.branch:
            raise serializers.ValidationError({"branch": [
                serializers.ErrorDetail("Cannot be changed after creation.", code="immutable_field")]})
        branch = attrs.get("branch") or (self.instance.branch if self.instance else None)
        code = attrs.get("code") or (self.instance.code if self.instance else None)
        clash = Rank.objects.filter(branch=branch, code=code)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError({"code": [
                serializers.ErrorDetail("This rank code already exists for the branch.", code="rank_code_taken")]})
        self._keep_reporting_lines_valid(attrs)
        return attrs

    def _keep_reporting_lines_valid(self, attrs):
        """sort_order is the seniority order (higher = more senior) and reporting lines depend on it, so it cannot be
        changed in a way that leaves someone reporting to a person of equal or lower rank."""
        inst = self.instance
        if inst is None or "sort_order" not in attrs or attrs["sort_order"] == inst.sort_order:
            return
        from apps.personnel.models import Personnel  # local import: personnel depends on ranks
        new = attrs["sort_order"]
        broken = (Personnel.objects.filter(rank=inst, supervisor__rank__active=True, supervisor__rank__sort_order__lte=new)
                  | Personnel.objects.filter(supervisor__rank=inst, rank__active=True, rank__sort_order__gte=new))
        if inst.active and broken.exists():
            raise serializers.ValidationError({"sort_order": [serializers.ErrorDetail(
                "This order would put someone at or above their own supervisor.", code="breaks_reporting_lines")]})

    def update(self, instance, validated_data):
        expected = require_version(self.initial_data)
        changes = {k: v for k, v in validated_data.items() if k != "branch"}
        # Changing what a rank *is* voids its approval; the change must be re-approved.
        if instance.approval_status == Rank.Approval.APPROVED and any(
                k in changes and changes[k] != getattr(instance, k) for k in IDENTITY_FIELDS):
            changes.update(approval_status=Rank.Approval.DRAFT, approved_by=None, approved_at=None)
        return versioned_update(instance, changes, expected)
