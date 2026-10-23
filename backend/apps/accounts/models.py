import uuid

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra):
        if not username:
            raise ValueError("username is required")
        user = self.model(username=username.lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """No is_superuser/is_staff: all authority comes from scoped role assignments."""

    LANGUAGES = [("en", "English"), ("so", "Soomaali")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=64, unique=True)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    preferred_language = models.CharField(max_length=2, choices=LANGUAGES, default="en")
    is_active = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret_enc = models.TextField(blank=True)  # Fernet-encrypted TOTP secret
    # Bumped on disable / role change / password change; sessions carry the value
    # they were created with and are rejected when it no longer matches.
    auth_epoch = models.PositiveIntegerField(default=1)
    mfa_last_step = models.BigIntegerField(default=0)  # newest TOTP time-step accepted (blocks code replay)
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        ordering = ["username"]

    def __str__(self):
        return self.username


class Permission(models.Model):
    code = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "permissions"
        ordering = ["code"]

    def __str__(self):
        return self.code


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=48, unique=True)
    name_en = models.CharField(max_length=100)
    name_so = models.CharField(max_length=100, blank=True)
    is_privileged = models.BooleanField(default=False)  # privileged roles require MFA
    requires_branch = models.BooleanField(default=False)
    allowed_scope_levels = models.JSONField(default=list, blank=True)  # [] = any level
    permissions = models.ManyToManyField(Permission, related_name="roles", db_table="role_permissions")

    class Meta:
        db_table = "roles"
        ordering = ["code"]

    def __str__(self):
        return self.code


class RoleAssignmentQuerySet(models.QuerySet):
    def effective(self, on=None):
        today = on or timezone.localdate()
        return (
            self.filter(revoked_at__isnull=True, user__is_active=True)
            .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        )


class RoleAssignment(models.Model):
    """A role held over a subtree of the organization, optionally limited to one service branch."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    branch = models.ForeignKey("organization.ServiceBranch", null=True, blank=True,
                               on_delete=models.PROTECT, related_name="+")
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RoleAssignmentQuerySet.as_manager()

    class Meta:
        db_table = "user_role_assignments"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True) | Q(valid_until__isnull=True)
                | Q(valid_until__gte=models.F("valid_from")),
                name="assignment_valid_range",
            )
        ]


class PasswordResetToken(models.Model):
    """One-time, short-lived recovery code issued by an administrator. Only a hash is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "password_reset_tokens"
        ordering = ["-created_at"]
