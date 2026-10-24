"""Break-glass override for the "must be a different person" rules in payroll and payments.

Only a user holding `system.full_access` (super_admin) can use it, only when ARMYHQ_BREAK_GLASS is on, and only with a written reason
(sent in the X-Override-Reason header, at least 15 characters). It skips ONE separation-of-duties check for ONE action; every other
rule (state, amounts, validity, permissions) still applies, and every use is written to the audit log with the reason.
"""
from contextvars import ContextVar

from django.conf import settings

from apps.audit.services import record

MIN_REASON = 15
_reason = ContextVar("override_reason", default="")


class BreakGlassMiddleware:
    """Make this request's override reason (if any) visible to the service layer, and clear it afterwards."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _reason.set(" ".join(str(request.META.get("HTTP_X_OVERRIDE_REASON", "")).split())[:300])
        try:
            return self.get_response(request)
        finally:
            _reason.reset(token)


def bypass(user, check, entity_type, entity_id):
    """True when this user may skip the named different-person check right now. Audits every use."""
    from apps.accounts.scope import FULL_ACCESS, permission_codes
    reason = _reason.get()
    if not (getattr(settings, "BREAK_GLASS_ENABLED", False) and len(reason) >= MIN_REASON):
        return False
    if FULL_ACCESS not in permission_codes(user):
        return False
    record("breakglass.override", actor=user, entity_type=entity_type, entity_id=entity_id,
           metadata={"check": check, "reason": reason})
    return True
