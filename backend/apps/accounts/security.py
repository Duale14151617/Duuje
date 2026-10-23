import hmac
import time

import pyotp

from apps.core import crypto

from . import scope
from .models import User

TOTP_INTERVAL = 30


def restrictions(user):
    """Conditions that confine a session to the self-service screens only."""
    found = []
    if user.must_change_password:
        found.append("password_change")
    if scope.requires_mfa(user) and not user.mfa_enabled:
        found.append("mfa_enrollment")
    return found


def _now():
    return time.time()


def consume_totp(user, code):
    """Verify a TOTP code and burn its time-step. A code (or any older one) can never be used twice.

    The conditional UPDATE makes the check atomic, so two simultaneous logins cannot both spend one code.
    """
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == 6) or not user.mfa_secret_enc:
        return False
    totp = pyotp.TOTP(crypto.decrypt(user.mfa_secret_enc), interval=TOTP_INTERVAL)
    now = _now()
    for offset in (0, -1, 1):  # one step of clock drift either way
        moment = now + offset * TOTP_INTERVAL
        if hmac.compare_digest(totp.at(moment), code):
            step = int(moment // TOTP_INTERVAL)
            return User.objects.filter(pk=user.pk, mfa_last_step__lt=step).update(mfa_last_step=step) == 1
    return False
