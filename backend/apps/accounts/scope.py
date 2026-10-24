"""Server-side scope engine. Every authorization decision goes through here.

A RoleAssignment grants a role's permissions over the subtree rooted at
`org_unit`, optionally limited to units of one service branch. An assignment at
the HQ node with no branch is "global". Nothing is granted by default.
"""
from django.conf import settings
from django.db.models import Q

from apps.organization.models import OrganizationalUnit, ServiceBranch

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


# Permission families that touch personnel data. Two extra server-side rules apply to them (see _blocked / unit_scope_q):
#  1. Police units are invisible while POLICE_MODULE_ENABLED is off (the pilot can be switched off without a deploy of code).
#  2. Police units are reachable only from an assignment limited to the POLICE branch, or from a role holding
#     `police.cross_access` (command authority: President / Commander of the Puntland Defense Forces, and super_admin).
#     Army roles and any branch-less regional/HQ role therefore never reach Police records by default.
#  3. Restricted units (CID) need `cid.access` in the same assignment - belonging to the Police branch is not enough.
GATED_PREFIXES = ("personnel.", "reports.", "training.", "logistics.", "analytics.", "cid.", "disciplinary.", "documents.", "payroll.", "survivor.", "payment.", "arrears.")


def _gates(user):
    g = getattr(user, "_module_gates", None)
    if g is None:
        g = {"police": ServiceBranch.objects.filter(code="POLICE").values_list("pk", flat=True).first(),
             "restricted": list(OrganizationalUnit.objects.filter(restricted=True).values_list("path", flat=True))}
        user._module_gates = g
    return g


FULL_ACCESS = "system.full_access"  # maintenance override held by super_admin: module switches and gates never hide data from it


def _blocked(user, a, code, unit):
    if not code.startswith(GATED_PREFIXES) or FULL_ACCESS in a.perm_codes:
        return False
    g = _gates(user)
    if g["police"] is not None and unit.branch_id == g["police"]:
        if not settings.POLICE_MODULE_ENABLED:
            return True
        if a.branch_id != g["police"] and "police.cross_access" not in a.perm_codes:
            return True
    return "cid.access" not in a.perm_codes and any(unit.path.startswith(p) for p in g["restricted"])


def can(user, code, unit=None):
    """True if `user` holds `code`. With no unit, requires a global (HQ, any-branch) grant."""
    for a in assignments(user):
        if code not in a.perm_codes:
            continue
        if unit is None:
            if is_global(a):
                return True
        elif covers(a, unit) and not _blocked(user, a, code, unit):
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
        if code.startswith(GATED_PREFIXES) and FULL_ACCESS not in a.perm_codes:
            g = _gates(user)
            if g["police"] is not None and (
                    not settings.POLICE_MODULE_ENABLED
                    or (a.branch_id != g["police"] and "police.cross_access" not in a.perm_codes)):
                part &= ~Q(**{f"{prefix}branch_id": g["police"]})
            if "cid.access" not in a.perm_codes:
                for path in g["restricted"]:
                    part &= ~Q(**{f"{prefix}path__startswith": path})
        q |= part
    return q if granted else None


def scoped_units(user, code):
    """Queryset of units the user may access under `code`. Empty when nothing is granted."""
    q = unit_scope_q(user, code)
    if q is None:
        return OrganizationalUnit.objects.none()
    return OrganizationalUnit.objects.filter(q)
