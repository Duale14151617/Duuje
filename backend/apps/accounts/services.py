import re
import secrets
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.db.models import F
from django.utils import timezone

from apps.organization.models import OrganizationalUnit

from .models import RoleAssignment, User


def revoke_user_sessions(user):
    """Invalidate every session of `user` now (epoch bump) and delete stored sessions."""
    User.objects.filter(pk=user.pk).update(auth_epoch=F("auth_epoch") + 1)
    user.refresh_from_db(fields=["auth_epoch"])
    uid = str(user.pk)
    for s in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if s.get_decoded().get("_auth_user_id") == uid:
            s.delete()


def other_admins_exist(*, excluding_user_id=None, excluding_assignment_id=None):
    """Lock-out guard: is there another effective global user administrator?"""
    qs = RoleAssignment.objects.effective().filter(
        role__permissions__code="users.manage",
        org_unit__level=OrganizationalUnit.Level.HQ,
        branch__isnull=True,
    )
    if excluding_user_id:
        qs = qs.exclude(user_id=excluding_user_id)
    if excluding_assignment_id:
        qs = qs.exclude(pk=excluding_assignment_id)
    return qs.exists()


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")  # lowercase letters, digits, dot, underscore, dash


def _name_tokens(full_name):
    folded = unicodedata.normalize("NFKD", full_name or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z0-9]+", folded) if t]


def suggest_usernames(full_name, limit=5, extra_taken=()):
    """Free `firstname.lastname` usernames for a person, best first.

    Order: first.last, then with each middle name's initial (ali.h.warsame), then with a number (ali.warsame2 ...).
    Only names that are valid and not already taken are returned."""
    tokens = _name_tokens(full_name)
    if not tokens:
        return []
    first, last = tokens[0], tokens[-1]
    base = f"{first}.{last}" if len(tokens) > 1 else first
    names = [base] + [f"{first}.{m[0]}.{last}" for m in tokens[1:-1]] + [f"{base}{n}" for n in range(2, 10)]
    names = [n for n in dict.fromkeys(names) if USERNAME_PATTERN.match(n)]
    taken = set(User.objects.filter(username__in=names).values_list("username", flat=True)) | set(extra_taken)
    return [n for n in names if n not in taken][:limit]


_LOWER, _UPPER, _DIGITS = "abcdefghjkmnpqrstuvwxyz", "ABCDEFGHJKMNPQRSTUVWXYZ", "23456789"  # no look-alikes (i l o 0 1)


def generate_temp_password():
    """Random temporary password like 'Kx7mPq-4tWn9d': 12 letters and digits (no look-alikes) with a dash, easy to read out."""
    rng = secrets.SystemRandom()
    for _ in range(10):
        chars = [secrets.choice(_LOWER) for _ in range(4)] + [secrets.choice(_UPPER) for _ in range(4)] \
            + [secrets.choice(_DIGITS) for _ in range(4)]
        rng.shuffle(chars)
        pw = "".join(chars[:6]) + "-" + "".join(chars[6:])
        try:
            validate_password(pw)
            return pw
        except Exception:  # extremely unlikely (a common-password hit); draw again
            continue
    raise RuntimeError("could not generate a temporary password")


def temp_password_deadline():
    return timezone.now() + timedelta(days=settings.TEMP_PASSWORD_DAYS)


def sensitive_role(role):
    """A role that is privileged, or lets its holder manage accounts / hand out roles / override switches."""
    from . import scope
    return role.is_privileged or bool(scope.ADMIN_PERMS & set(role.permissions.values_list("code", flat=True)))


def user_admin_emails(exclude_user_id=None):
    """Verified email addresses of every active whole-system user administrator."""
    qs = RoleAssignment.objects.effective().filter(
        role__permissions__code="users.manage", org_unit__level=OrganizationalUnit.Level.HQ, branch__isnull=True,
        user__email_verified_at__isnull=False).exclude(user__email="")
    if exclude_user_id:
        qs = qs.exclude(user_id=exclude_user_id)
    return sorted(set(qs.values_list("user__email", flat=True)))


def alert_privileged_grant(actor, target, role, unit):
    """Tell the other user administrators (by email) that a privileged role was handed out. Never raises, never includes secrets.
    The audit event is written by the caller; this is the second pair of eyes."""
    from django.core.mail import send_mail
    body = (f"{actor.username} gave the account {target.username} ({target.full_name}) the role {role.code} "
            f"over {unit.name_en} [{unit.code}]. This role is privileged or can manage accounts. "
            "If you did not expect this, tell your administrator now and review the account.")
    sent = 0
    for address in user_admin_emails(exclude_user_id=actor.pk):
        try:
            sent += send_mail("Puntland Defence Forces HQ: privileged access granted", body, None, [address], fail_silently=False)
        except Exception:
            continue
    return sent


def close_login(user):
    """End the login of someone who has left service: disable it and sign out every session. The link to their personnel
    record is kept. Returns "closed", "already" (it was off), or "blocked_last_admin" (it is the only user administrator, so
    closing it would lock everybody out of account management; a human must decide)."""
    if not user.is_active:
        return "already"
    is_admin = RoleAssignment.objects.effective().filter(
        user=user, role__permissions__code="users.manage", org_unit__level=OrganizationalUnit.Level.HQ, branch__isnull=True).exists()
    if is_admin and not other_admins_exist(excluding_user_id=user.pk):
        return "blocked_last_admin"
    User.objects.filter(pk=user.pk).update(is_active=False, updated_at=timezone.now())
    revoke_user_sessions(user)
    return "closed"
