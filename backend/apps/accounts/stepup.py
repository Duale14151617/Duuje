"""Step-up authentication: a signed-in session is not enough for the most damaging actions.

Credential resets, role assignment, personnel export and the break-glass override all need an authenticator code entered within the
last STEP_UP_MFA_SECONDS (default 10 minutes). Signing in with a code counts. A stolen session cookie therefore cannot do any of
them, because the thief does not hold the authenticator. Accounts without MFA enabled are not asked (there is nothing to ask).
"""
import time

from django.conf import settings
from rest_framework.exceptions import PermissionDenied

SESSION_KEY = "mfa_at"


class StepUpRequired(PermissionDenied):
    default_detail = "Confirm your authenticator code to continue."
    default_code = "step_up_required"


def mark_fresh(request):
    request.session[SESSION_KEY] = int(time.time())


def is_fresh(request, user=None):
    if not getattr(settings, "STEP_UP_MFA_REQUIRED", False):
        return True
    user = user if user is not None else getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False) or not getattr(user, "mfa_enabled", False):
        return True
    try:
        stamp = int(request.session.get(SESSION_KEY, 0))
    except (TypeError, ValueError):
        stamp = 0
    return 0 <= time.time() - stamp <= int(getattr(settings, "STEP_UP_MFA_SECONDS", 600))


def require_fresh_mfa(request):
    if not is_fresh(request):
        raise StepUpRequired()
