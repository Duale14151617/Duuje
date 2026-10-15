"""Server-side scope engine. Every authorization decision goes through here.

A RoleAssignment grants a role's permissions over the subtree rooted at
`org_unit`, optionally limited to units of one service branch. An assignment at
the HQ node with no branch is "global". Nothing is granted by default.
"""
from django.db.models import Q

from apps.organization.models import OrganizationalUnit

from .models import RoleAssignment


def assignments(user):
    """Effective assignments for this user, cached on the user object for one request."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return []
    cached = getattr(user, "_scope_cache", None)
    if cached is None:
        cached = list(
            RoleAssignment.objects.effective()
            .filter(user_id=user.pk)
            .select_related("role", "org_unit", "branch")
            .prefetch_related("role__permissions")
        )
        for a in cached:
            a.perm_codes = {p.code for p in a.role.permissions.all()}
        user._scope_cache = cached
    return cached


def permission_codes(user):
    codes = set()
    for a in assignments(user):
        codes |= a.perm_codes
    return codes


def requires_mfa(user):
    return any(a.role.is_privileged for a in assignments(user))


def is_global(a):
    return a.org_unit.level == OrganizationalUnit.Level.HQ and a.branch_id is None


def covers(a, unit):
    if not unit.path.startswith(a.org_unit.path):
        return False
    return a.branch_id is None or unit.branch_id == a.branch_id


def can(user, code, unit=None):
    """True if `user` holds `code`. With no unit, requires a global (HQ, any-branch) grant."""
    for a in assignments(user):
        if code not in a.perm_codes:
            continue
        if unit is None:
            if is_global(a):
                return True
        elif covers(a, unit):
            return True
    return False


def has_anywhere(user, code):
    return any(code in a.perm_codes for a in assignments(user))


def unit_scope_q(user, code, prefix=""):
    """Q limiting rows to units covered by `code`; `prefix` is the lookup path to the unit
    (e.g. "org_unit__"). Returns None when the user holds `code` nowhere (callers must then
    return nothing)."""
    q = Q()
    granted = False
    for a in assignments(user):
        if code not in a.perm_codes:
            continue
        granted = True
        part = Q(**{f"{prefix}path__startswith": a.org_unit.path})
        if a.branch_id is not None:
            part &= Q(**{f"{prefix}branch_id": a.branch_id})
        q |= part
    return q if granted else None


def scoped_units(user, code):
    """Queryset of units the user may access under `code`. Empty when nothing is granted."""
    q = unit_scope_q(user, code)
    if q is None:
        return OrganizationalUnit.objects.none()
    return OrganizationalUnit.objects.filter(q)
