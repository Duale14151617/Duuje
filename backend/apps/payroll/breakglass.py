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
_mfa_fresh = ContextVar("override_mfa_fresh", default=True)


class BreakGlassMiddleware:
    """Make this request's override reason (if any) visible to the service layer, and clear it afterwards."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.accounts.stepup import is_fresh
        token = _reason.set(" ".join(str(request.META.get("HTTP_X_OVERRIDE_REASON", "")).split())[:300])
        fresh = _mfa_fresh.set(is_fresh(request))
        try:
            return self.get_response(request)
        finally:
            _reason.reset(token)
            _mfa_fresh.reset(fresh)


def bypass(user, check, entity_type, entity_id):
    """True when this user may skip the named different-person check right now. Audits every use."""
    from apps.accounts.scope import FULL_ACCESS, permission_codes
    reason = _reason.get()
    if not (getattr(settings, "BREAK_GLASS_ENABLED", False) and len(reason) >= MIN_REASON):
        return False
    if FULL_ACCESS not in permission_codes(user):
        return False
    if not _mfa_fresh.get():  # a session without a recent authenticator code cannot override anything
        record("breakglass.override", actor=user, outcome="denied", entity_type=entity_type, entity_id=entity_id,
               metadata={"check": check, "reason": "step_up_required"})
        return False
    record("breakglass.override", actor=user, entity_type=entity_type, entity_id=entity_id,
           metadata={"check": check, "reason": reason})
    from apps.accounts import alerts
    alerts.notify("break-glass override used", f"{user.username} overrode the '{check}' check on {entity_type} {entity_id}. "
                  f"Reason given: {reason}", actor=user)
    return True
