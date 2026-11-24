"""Passkey ceremonies on top of apps.accounts.webauthn: issue a server-side challenge, check what the browser returns, burn the
challenge. A passkey is an ADDITIONAL second factor next to the authenticator app: it can be used instead of the 6-digit code at
sign-in and for step-up, and it can only be added by someone who already has the authenticator set up."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import webauthn
from .models import PasskeyChallenge, PasskeyCredential

CHALLENGE_SECONDS = 300
MAX_PER_USER = 10


def rp_id(request):
    configured = getattr(settings, "WEBAUTHN_RP_ID", "")
    return configured or request.get_host().split(":")[0]


def origins(request):
    configured = list(getattr(settings, "WEBAUTHN_ORIGINS", []) or [])
    if configured:
        return configured
    found = [f"{'https' if request.is_secure() else 'http'}://{request.get_host()}"]
    if settings.DEBUG:
        found += ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"]
    return found


def _issue(user, purpose):
    PasskeyChallenge.objects.filter(expires_at__lt=timezone.now() - timedelta(hours=1)).delete()
    return PasskeyChallenge.objects.create(user=user, purpose=purpose, challenge=webauthn.b64e(secrets.token_bytes(32)),
                                           expires_at=timezone.now() + timedelta(seconds=CHALLENGE_SECONDS))


def _burn(user, challenge_id, purpose):
    """The challenge text, or None when it is unknown, someone else's, for another purpose, expired or already used."""
    try:
        row = PasskeyChallenge.objects.filter(pk=challenge_id, user=user, purpose=purpose, used_at__isnull=True,
                                              expires_at__gt=timezone.now()).first()
    except Exception:  # a malformed id
        row = None
    if row is None:
        return None
    won = PasskeyChallenge.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=timezone.now())
    return row.challenge if won == 1 else None


def has_passkeys(user):
    return PasskeyCredential.objects.filter(user=user).exists()


def registration_options(request, user):
    ch = _issue(user, "register")
    return {"challenge_id": str(ch.pk), "options": {
        "challenge": ch.challenge,
        "rp": {"id": rp_id(request), "name": getattr(settings, "WEBAUTHN_RP_NAME", "Police HQ")},
        "user": {"id": webauthn.b64e(user.pk.bytes), "name": user.username, "displayName": user.full_name or user.username},
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}, {"type": "public-key", "alg": -257}],
        "excludeCredentials": [{"type": "public-key", "id": c.credential_id} for c in PasskeyCredential.objects.filter(user=user)],
        "authenticatorSelection": {"residentKey": "preferred", "userVerification": "preferred"},
        "attestation": "none",
        "timeout": 120000,
    }}


def register(request, user, challenge_id, credential, name):
    """Verify and store a new passkey. Raises WebAuthnError (not a valid ceremony) or ValueError (limit reached)."""
    if PasskeyCredential.objects.filter(user=user).count() >= MAX_PER_USER:
        raise ValueError("limit")
    challenge = _burn(user, challenge_id, "register")
    if challenge is None:
        raise webauthn.WebAuthnError("challenge expired")
    cred_id, public_key, count, transports = webauthn.verify_registration(
        credential, challenge=challenge, rp_id=rp_id(request), origins=origins(request))
    if PasskeyCredential.objects.filter(credential_id=cred_id).exists():
        raise webauthn.WebAuthnError("already registered")
    return PasskeyCredential.objects.create(user=user, credential_id=cred_id, public_key=public_key, sign_count=count,
                                            name=(name or "Passkey").strip()[:60] or "Passkey", transports=transports)


def request_options(request, user, purpose):
    """Options for navigator.credentials.get(). `purpose` is "login" or "stepup"."""
    ch = _issue(user, purpose)
    return {"challenge_id": str(ch.pk), "options": {
        "challenge": ch.challenge,
        "rpId": rp_id(request),
        "allowCredentials": [{"type": "public-key", "id": c.credential_id, "transports": c.transports}
                             for c in PasskeyCredential.objects.filter(user=user)],
        "userVerification": "preferred",
        "timeout": 120000,
    }}


def verify(request, user, payload, purpose):
    """True when `payload` ({challenge_id, credential}) is a valid passkey assertion by `user` for a challenge we issued."""
    if not isinstance(payload, dict) or not isinstance(payload.get("credential"), dict):
        return False
    credential = payload["credential"]
    stored = PasskeyCredential.objects.filter(user=user, credential_id=str(credential.get("id", ""))[:512]).first()
    if stored is None:
        return False
    challenge = _burn(user, payload.get("challenge_id"), purpose)
    if challenge is None:
        return False
    try:
        count = webauthn.verify_assertion(credential, stored_public_key=stored.public_key, stored_sign_count=stored.sign_count,
                                          challenge=challenge, rp_id=rp_id(request), origins=origins(request))
    except webauthn.WebAuthnError:
        return False
    with transaction.atomic():
        PasskeyCredential.objects.filter(pk=stored.pk).update(sign_count=count, last_used_at=timezone.now())
    return True
