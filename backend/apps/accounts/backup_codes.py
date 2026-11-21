"""Single-use backup codes: the way in when the authenticator app and every passkey are out of reach (lost phone).

Ten codes are shown once, when MFA is switched on or when the user asks for a new set (a new set cancels the old one). Only hashes
are stored. A code looks like K7M2Q-9XPTW (letters and digits without the easily confused 0/O/1/I) and works exactly once.
"""
import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from .models import MfaBackupCode

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 10
COUNT = 10


def normalize(code):
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def looks_like_backup_code(code):
    n = normalize(code)
    return len(n) == LENGTH and all(ch in ALPHABET for ch in n)


def _hash(user, normalized):
    return hashlib.sha256(f"{user.pk}:{normalized}".encode()).hexdigest()


def pretty(normalized):
    return f"{normalized[:LENGTH // 2]}-{normalized[LENGTH // 2:]}"


@transaction.atomic
def generate(user):
    """Replace the user's codes with a fresh set and return the plain codes (the only time they exist in readable form)."""
    MfaBackupCode.objects.filter(user=user).delete()
    plain = []
    while len(plain) < COUNT:
        code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
        if code not in plain:
            plain.append(code)
    MfaBackupCode.objects.bulk_create([MfaBackupCode(user=user, code_hash=_hash(user, c)) for c in plain])
    return [pretty(c) for c in plain]


def consume(user, code):
    """True once per code. The conditional UPDATE makes it atomic, so two simultaneous sign-ins cannot both spend one code."""
    if not looks_like_backup_code(code):
        return False
    return MfaBackupCode.objects.filter(user=user, code_hash=_hash(user, normalize(code)), used_at__isnull=True).update(
        used_at=timezone.now()) == 1


def remaining(user):
    return MfaBackupCode.objects.filter(user=user, used_at__isnull=True).count()
