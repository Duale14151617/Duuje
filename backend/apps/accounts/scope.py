"""Server-side scope engine. Every authorization decision goes through here.

A RoleAssignment grants a role's permissions over the subtree rooted at
`org_unit`, optionally limited to units of one service branch. An assignment at
the HQ node with no branch is "global". Nothing is granted by default.
"""
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

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


# Holding any of these means a user can create accounts, hand out roles or override module switches: always needs MFA, even if the
# role carrying it was not flagged "privileged".
ADMIN_PERMS = frozenset({"users.manage", "roles.assign", "system.full_access"})


# Permissions that touch pay, weapons, medical, discipline, restricted records or the personnel register. A role holding any of them is
# "sensitive": two-step sign-in is strongly recommended, and becomes mandatory on the date in MFA_SENSITIVE_REQUIRED_FROM (if set).
SENSITIVE_PREFIXES = ("payroll.", "payment.", "arrears.", "survivor.", "disciplinary.", "restricted.", "medical.")
SENSITIVE_EXACT = frozenset({"weapons.manage", "personnel.manage", "personnel.import", "personnel.export", "personnel.confirm_death",
                             "credentials.issue", "logistics.approve", "logistics.restricted", "logistics.restricted_approve"})


def holds_sensitive(user):
    return any(c.startswith(SENSITIVE_PREFIXES) or c in SENSITIVE_EXACT for a in assignments(user) for c in a.perm_codes)


def mfa_sensitive_deadline():
    """The date from which sensitive roles must use two-step sign-in, or None while it is only recommended."""
    raw = (getattr(settings, "MFA_SENSITIVE_REQUIRED_FROM", "") or "").strip()
    if not raw:
        return None
    try:
        from datetime import date
        return date.fromisoformat(raw)
    except ValueError:
        return None


def requires_mfa(user):
    if any(a.role.is_privileged or (ADMIN_PERMS & a.perm_codes) for a in assignments(user)):
        return True
    deadline = mfa_sensitive_deadline()
    return deadline is not None and timezone.localdate() >= deadline and holds_sensitive(user)


def recommends_mfa(user):
    """Sensitive access without being required (yet) to use two-step sign-in."""
    return not requires_mfa(user) and holds_sensitive(user)


def is_global(a):
    return a.org_unit.level == OrganizationalUnit.Level.HQ and a.branch_id is None


def covers(a, unit):
    if not unit.path.startswith(a.org_unit.path):
        return False
    return a.branch_id is None or unit.branch_id == a.branch_id


# Permission families that touch personnel data. One extra server-side rule applies to them (see _blocked / unit_scope_q):
# restricted units need `restricted.access` in the same assignment.
GATED_PREFIXES = ("personnel.", "reports.", "training.", "logistics.", "analytics.", "restricted.", "disciplinary.", "documents.", "payroll.", "survivor.", "payment.", "arrears.", "vehicles.", "changes.", "food.", "tasks.", "promotion.", "fitness.", "medical.")


def _gates(user):
    g = getattr(user, "_module_gates", None)
    if g is None:
        g = {"restricted": list(OrganizationalUnit.objects.filter(restricted=True).values_list("path", flat=True))}
        user._module_gates = g
    return g


FULL_ACCESS = "system.full_access"  # maintenance override held by super_admin: lifts the restricted-unit gate


def has_full_access(user):
    return FULL_ACCESS in permission_codes(user)


def self_approval_allowed(user, check, request=None, entity_type="", entity_id=""):
    """True only for the super administrator (system.full_access), who alone may approve, verify or count their own work.
    Every use is written to the audit log. Nobody else, including the headquarters administrator, can ever pass a
    "must be a different person" check."""
    if not has_full_access(user):
        return False
    from apps.audit.services import record
    record("self_approval.used", request=request, actor=user, entity_type=entity_type, entity_id=entity_id, metadata={"check": check})
    return True


def _blocked(user, a, code, unit):
    if not code.startswith(GATED_PREFIXES):
        return False
    g = _gates(user)
    if FULL_ACCESS in a.perm_codes:
        return False
    return "restricted.access" not in a.perm_codes and any(unit.path.startswith(p) for p in g["restricted"])


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
        if code.startswith(GATED_PREFIXES):
            g = _gates(user)
        if code.startswith(GATED_PREFIXES) and FULL_ACCESS not in a.perm_codes:
            if "restricted.access" not in a.perm_codes:
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
