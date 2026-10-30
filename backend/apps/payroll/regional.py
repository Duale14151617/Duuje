"""Regional scope for paying salaries.

Headquarters (an unscoped grant) prepares and approves payroll runs. A regional finance account holds the payment roles at a regional
command, so it sees and handles only the SALARY payments, and the approved run lines, of personnel inside that command. Headquarters
accounts behave exactly as before: when a user holds the permission at headquarters nothing is narrowed.
"""
from django.db.models import Q

from apps.accounts import scope


def is_hq(user, codes):
    """True when the user holds any of these permissions at headquarters (unscoped)."""
    return any(scope.can(user, c) for c in codes)


def narrow(user, codes, qs, prefix):
    """Headquarters: unchanged. Regional: rows whose unit lies inside an assignment that holds one of the permissions."""
    if is_hq(user, codes):
        return qs
    q, granted = Q(), False
    for c in codes:
        part = scope.unit_scope_q(user, c, prefix)
        if part is not None:
            q |= part
            granted = True
    return qs.filter(q) if granted else qs.none()


def in_scope(user, codes, unit):
    return any(scope.can(user, c) or scope.can(user, c, unit=unit) for c in codes)
