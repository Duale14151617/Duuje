from rest_framework import serializers

from apps.accounts.serializers import UnitBriefSerializer
from apps.core.concurrency import require_version, versioned_update
from apps.personnel.models import Personnel

from .models import Course, TrainingRecord


def fail(field, code, message="Invalid."):
    return serializers.ValidationError({field: [serializers.ErrorDetail(message, code=code)]})


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ["id", "code", "name_en", "name_so", "duration_days", "active", "version"]
        read_only_fields = ["id", "version"]

    def validate_code(self, value):
        value = value.strip().lower()
        if not value.replace("_", "").isalnum():
            raise serializers.ValidationError("Letters, digits and _ only.", code="invalid_code")
        clash = Course.objects.filter(code=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("Code already in use.", code="code_taken")
        return value

    def update(self, instance, validated_data):
        validated_data.pop("code", None)  # codes are permanent identifiers
        return versioned_update(instance, validated_data, require_version(self.initial_data))


class CourseBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ["id", "code", "name_en", "name_so"]


class PersonBriefSerializer(serializers.ModelSerializer):
    """Training staff see a name and unit only. No service number, phone, rank or status."""

    org_unit = UnitBriefSerializer(read_only=True)

    class Meta:
        model = Personnel
        fields = ["id", "full_name", "org_unit"]


class TrainingRecordSerializer(serializers.ModelSerializer):
    course = CourseBriefSerializer(read_only=True)
    personnel = PersonBriefSerializer(read_only=True)

    class Meta:
        model = TrainingRecord
        fields = ["id", "personnel", "course", "status", "start_date", "end_date", "completed_on", "notes",
                  "created_by_username", "version", "updated_at"]
        read_only_fields = fields


class TrainingCreateSerializer(serializers.Serializer):
    personnel = serializers.UUIDField()  # resolved through the caller's scope in the view
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all())
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class TrainingEditSerializer(serializers.Serializer):
    end_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)


class StatusInputSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["in_progress", "completed", "failed", "withdrawn"])
    completed_on = serializers.DateField(required=False, allow_null=True)
