import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.concurrency import require_version, versioned_update
from apps.organization.models import OrganizationalUnit, ServiceBranch

from .models import Role, RoleAssignment, User

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")


def check_password_strength(password, user=None):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(
            [serializers.ErrorDetail(m, code="weak_password") for m in exc.messages])
    return password


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=64)
    password = serializers.CharField(max_length=256, trim_whitespace=False)
    otp = serializers.CharField(max_length=8, required=False, allow_blank=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)


class PasswordResetRedeemSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=64)
    code = serializers.CharField(max_length=32)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class MfaConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=8)


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")

    class Meta:
        model = Role
        fields = ["id", "code", "name_en", "name_so", "is_privileged", "requires_branch",
                  "allowed_scope_levels", "permissions"]


class RoleBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name_en", "name_so", "is_privileged"]


class UnitBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationalUnit
        fields = ["id", "code", "name_en", "name_so", "level", "unit_type"]


class BranchBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceBranch
        fields = ["id", "code", "name_en", "name_so"]


class AssignmentSerializer(serializers.ModelSerializer):
    role = RoleBriefSerializer(read_only=True)
    org_unit = UnitBriefSerializer(read_only=True)
    branch = BranchBriefSerializer(read_only=True)

    class Meta:
        model = RoleAssignment
        fields = ["id", "role", "org_unit", "branch", "valid_from", "valid_until", "revoked_at", "created_at"]


class AssignmentCreateSerializer(serializers.Serializer):
    role = serializers.SlugRelatedField(slug_field="code", queryset=Role.objects.all())
    org_unit = serializers.PrimaryKeyRelatedField(queryset=OrganizationalUnit.objects.filter(active=True))
    branch = serializers.PrimaryKeyRelatedField(
        queryset=ServiceBranch.objects.filter(active=True), required=False, allow_null=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        role, unit, branch = attrs["role"], attrs["org_unit"], attrs.get("branch")
        if role.allowed_scope_levels and unit.level not in role.allowed_scope_levels:
            raise serializers.ValidationError({"org_unit": [
                serializers.ErrorDetail("This role cannot be held at that level.", code="scope_level_not_allowed")]})
        if role.requires_branch and branch is None:
            raise serializers.ValidationError({"branch": [
                serializers.ErrorDetail("This role needs a service branch.", code="branch_required")]})
        if branch is not None and unit.branch_id and unit.branch_id != branch.pk:
            raise serializers.ValidationError({"branch": [
                serializers.ErrorDetail("Branch does not match the unit.", code="branch_mismatch")]})
        vf, vu = attrs.get("valid_from"), attrs.get("valid_until")
        if vf and vu and vu < vf:
            raise serializers.ValidationError({"valid_until": [
                serializers.ErrorDetail("End date is before start date.", code="invalid_range")]})
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "full_name", "email", "preferred_language", "is_active",
                  "mfa_enabled", "must_change_password", "last_login", "created_at", "version"]
        read_only_fields = fields


class UserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=64)
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    preferred_language = serializers.ChoiceField(choices=["en", "so"], default="en")
    initial_password = serializers.CharField(trim_whitespace=False)

    def validate_username(self, value):
        value = value.lower()
        if not USERNAME_RE.match(value):
            raise serializers.ValidationError("3-64 chars: a-z, 0-9, _ . -", code="invalid_username")
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username is taken.", code="username_taken")
        return value

    def validate(self, attrs):
        check_password_strength(attrs["initial_password"], user=User(username=attrs["username"], full_name=attrs["full_name"]))
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("initial_password")
        return User.objects.create_user(password=password, must_change_password=True, **validated_data)


class UserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    preferred_language = serializers.ChoiceField(choices=["en", "so"], required=False)

    def update(self, instance, validated_data):
        expected = require_version(self.initial_data)
        return versioned_update(instance, validated_data, expected)


class PasswordResetSerializer(serializers.Serializer):
    temporary_password = serializers.CharField(trim_whitespace=False)

    def validate_temporary_password(self, value):
        return check_password_strength(value)
