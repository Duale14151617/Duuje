import hmac
import math
import time
from datetime import timedelta

import pyotp
from django.conf import settings
from django.utils import timezone

from apps.core import crypto

from . import backup_codes, scope
from .models import MfaBackupCode, PasskeyChallenge, PasskeyCredential, User

TOTP_INTERVAL = 30


def password_age(user, now=None):
    """None when passwords do not expire or the age is unknown; otherwise when this one runs out and how many whole days are left."""
    limit = settings.PASSWORD_MAX_AGE_DAYS
    if not limit or user.password_changed_at is None:
        return None
    now = now or timezone.now()
    expires = user.password_changed_at + timedelta(days=limit)
    left = math.ceil((expires - now).total_seconds() / 86400)
    return {"expires_at": expires, "days_left": max(left, 0), "expired": now >= expires,
            "warn": left <= settings.PASSWORD_WARN_DAYS}


def restrictions(user):
    """Conditions that confine a session to the self-service screens only."""
    found = []
    if user.must_change_password:
        found.append("password_change")
    elif (age := password_age(user)) and age["expired"]:
        found.append("password_change")  # too old: the same forced-change screen as a temporary password
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


def consume_second_factor(user, code):
    """Check what the person typed in the "code" box: a 6-digit authenticator code, or a one-time backup code.
    Returns "totp", "backup_code", or None."""
    code = (code or "").strip()
    if code.isdigit() and len(code) == 6:
        return "totp" if consume_totp(user, code) else None
    return "backup_code" if backup_codes.consume(user, code) else None


def clear_second_factors(user):
    """The authenticator was reset or removed: its backup codes and passkeys go with it (they only mean something beside it)."""
    MfaBackupCode.objects.filter(user=user).delete()
    PasskeyCredential.objects.filter(user=user).delete()
    PasskeyChallenge.objects.filter(user=user).delete()
