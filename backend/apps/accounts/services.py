import re
import unicodedata

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


def suggest_usernames(full_name, limit=5):
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
    taken = set(User.objects.filter(username__in=names).values_list("username", flat=True))
    return [n for n in names if n not in taken][:limit]
