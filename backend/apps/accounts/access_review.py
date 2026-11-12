"""Access review: the short list of accounts that need a human decision. Read-only, no secrets.

The full access report (access_report.py) says what everyone can do. This says who to look at: dormant or never-used logins,
privileged roles without MFA, temporary passwords that expired unused, assignments about to end, and whether there are at least
two user administrators. Every finding lists at most CAP names plus the true count."""
from datetime import timedelta

from django.utils import timezone

from apps.organization.models import OrganizationalUnit

from . import scope
from .models import Role, RoleAssignment, User

CAP = 100
NEVER_USED_DAYS = 14
DORMANT_DAYS = 90
ENDING_DAYS = 30


def _finding(names):
    names = list(names)
    return {"count": len(names), "items": names[:CAP]}


def review():
    now, today = timezone.now(), timezone.localdate()
    active = User.objects.filter(is_active=True)
    eff = RoleAssignment.objects.effective().select_related("user", "role", "org_unit")
    with_role = set(eff.values_list("user_id", flat=True))
    sensitive_ids = set(Role.objects.filter(is_privileged=True).values_list("pk", flat=True)) | set(
        Role.objects.filter(permissions__code__in=scope.ADMIN_PERMS).values_list("pk", flat=True))
    glob = [a for a in eff if a.org_unit.level == OrganizationalUnit.Level.HQ and a.branch_id is None]
    admins = {a.user_id for a in eff.filter(role__permissions__code="users.manage",
                                             org_unit__level=OrganizationalUnit.Level.HQ, branch__isnull=True)}
    findings = {
        "no_role": _finding(u.username for u in active.exclude(pk__in=with_role).order_by("username")),
        "privileged_no_mfa": _finding(f"{a.user.username}: {a.role.code}" for a in eff.filter(role_id__in=sensitive_ids)
                                      if not a.user.mfa_enabled),
        "global_access": _finding(sorted(f"{a.user.username}: {a.role.code}" for a in glob)),
        "ending_soon": _finding(f"{a.user.username}: {a.role.code} until {a.valid_until}" for a in
                                eff.filter(valid_until__isnull=False, valid_until__lte=today + timedelta(days=ENDING_DAYS))),
        "never_signed_in": _finding(u.username for u in active.filter(
            last_login__isnull=True, created_at__lt=now - timedelta(days=NEVER_USED_DAYS)).order_by("username")),
        "dormant": _finding(f"{u.username}: {u.last_login:%Y-%m-%d}" for u in active.filter(
            last_login__lt=now - timedelta(days=DORMANT_DAYS)).order_by("last_login")),
        "temp_expired": _finding(u.username for u in active.filter(
            must_change_password=True, temp_password_expires_at__lt=now).order_by("username")),
        "email_unverified": _finding(u.username for u in active.filter(pk__in=with_role, email_verified_at__isnull=True).order_by("username")),
        "leaver_active": _finding(f"{u.username}: {u.personnel_record.status}" for u in active.filter(
            personnel_record__status__in=("retired", "discharged", "died")).select_related("personnel_record").order_by("username")),
        "locked": _finding(u.username for u in active.filter(locked_until__gt=now).order_by("username")),
        "few_admins": _finding([str(len(admins))] if len(admins) < 2 else []),
    }
    return {"generated_at": now.isoformat(), "users": User.objects.count(), "active_users": active.count(),
            "findings": findings, "needs_attention": sum(1 for k, v in findings.items() if v["count"] and k != "global_access")}
