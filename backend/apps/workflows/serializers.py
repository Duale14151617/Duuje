
from rest_framework import serializers

from apps.accounts import scope
from apps.accounts.serializers import UnitBriefSerializer
from apps.core.concurrency import require_version, versioned_update
from apps.organization.models import OrganizationalUnit

from . import services as svc
from .models import FIGURE_KEYS, ApprovalAction, Notification, ReportType, Submission, SubmissionRevision


def fail(field, code, message="Invalid."):
    return serializers.ValidationError({field: [serializers.ErrorDetail(message, code=code)]})


class ReportTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportType
        fields = ["id", "code", "kind", "name_en", "name_so", "figure_keys", "separation_of_duties", "active", "version"]
        read_only_fields = ["id", "version"]

    def validate_code(self, value):
        value = value.strip().lower()
        if not value.replace("_", "").isalnum():
            raise serializers.ValidationError("Letters, digits and _ only.", code="invalid_code")
        clash = ReportType.objects.filter(code=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("Code already in use.", code="code_taken")
        return value

    def validate_figure_keys(self, value):
        if not isinstance(value, list) or any(k not in FIGURE_KEYS for k in value) or len(set(value)) != len(value):
            raise serializers.ValidationError("Unknown figure.", code="unknown_figure")
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.submissions.exists():
            for locked in ("kind", "figure_keys"):
                if locked in attrs and attrs[locked] != getattr(self.instance, locked):
                    raise fail(locked, "type_in_use")
        return attrs

    def update(self, instance, validated_data):
        return versioned_update(instance, validated_data, require_version(self.initial_data))


class TypeBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportType
        fields = ["id", "code", "kind", "name_en", "name_so", "figure_keys"]


class SubmissionListSerializer(serializers.ModelSerializer):
    report_type = TypeBriefSerializer(read_only=True)
    org_unit = UnitBriefSerializer(read_only=True)

    class Meta:
        model = Submission
        fields = ["id", "report_type", "org_unit", "title", "period_start", "period_end", "status", "version",
                  "current_revision", "submitter_username", "submitted_at", "decided_at", "updated_at"]
        read_only_fields = fields


class RevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmissionRevision
        fields = ["revision_no", "title", "period_start", "period_end", "body", "figures", "submitted_by_username", "created_at"]


class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalAction
        fields = ["id", "revision_no", "action", "from_status", "to_status", "actor_username", "comment", "created_at"]


class SubmissionDetailSerializer(SubmissionListSerializer):
    revisions = RevisionSerializer(many=True, read_only=True)
    actions = ActionSerializer(many=True, read_only=True)
    capabilities = serializers.SerializerMethodField()
    approved_revision_no = serializers.SerializerMethodField()

    class Meta(SubmissionListSerializer.Meta):
        fields = SubmissionListSerializer.Meta.fields + [
            "body", "figures", "revisions", "actions", "capabilities", "approved_revision_no"]
        read_only_fields = fields

    def get_capabilities(self, obj):
        return svc.capabilities(self.context["request"].user, obj)

    def get_approved_revision_no(self, obj):
        return obj.approved_revision.revision_no if obj.approved_revision_id else None


class SubmissionWriteSerializer(serializers.Serializer):
    """Content only. Status, submitter, reviewer, version and revision numbers are never accepted from clients."""

    report_type = serializers.PrimaryKeyRelatedField(queryset=ReportType.objects.filter(active=True), required=False)
    org_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.all(), required=False)
    title = serializers.CharField(max_length=200)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    body = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    figures = serializers.DictField(child=serializers.JSONField(), required=False)

    def validate(self, attrs):
        creating = self.instance is None
        if creating:
            for required in ("report_type", "org_unit"):
                if required not in attrs:
                    raise fail(required, "required")
            unit = attrs["org_unit"]
            if unit.level not in ("branch_command", "unit") or not unit.active:
                raise fail("org_unit", "unit_level_invalid")
            if not scope.can(self.context["request"].user, "reports.submit", unit=unit):
                raise fail("org_unit", "out_of_scope")
        else:
            for locked in ("report_type", "org_unit"):
                if locked in attrs and attrs[locked].pk != getattr(self.instance, f"{locked}_id"):
                    raise fail(locked, "immutable_field")
        start = attrs.get("period_start", getattr(self.instance, "period_start", None))
        end = attrs.get("period_end", getattr(self.instance, "period_end", None))
        if not svc.date_ok(start, end):
            raise fail("period_end", "period_invalid")
        rtype = attrs.get("report_type") or self.instance.report_type
        for key, value in (attrs.get("figures") or {}).items():
            if key not in rtype.figure_keys:
                raise fail("figures", "unknown_figure")
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10**9:
                raise fail("figures", "invalid_figure")
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    submission = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "kind", "created_at", "read_at", "submission"]

    def get_submission(self, obj):
        """Only reveal what the recipient may still see today; scope may have changed since it was sent."""
        s = obj.submission
        user = self.context["request"].user
        if s is None or not scope.can(user, "reports.view", unit=s.org_unit):
            return None
        return {"id": str(s.pk), "title": s.title, "status": s.status}
