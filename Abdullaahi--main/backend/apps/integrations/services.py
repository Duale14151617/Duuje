import hashlib
import hmac
import re
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException

from .models import IntegrationClient

KEY_RE = re.compile(r"^ahq_([0-9a-f]{8})_([A-Za-z0-9_-]{20,128})$")


class FeatureDisabled(APIException):
    status_code = 403
    default_detail = "Integrations are not enabled on this server."
    default_code = "feature_disabled"


def require_enabled():
    if not settings.INTEGRATIONS_ENABLED:
        raise FeatureDisabled()


def hash_key(full_key):
    return hashlib.sha256(full_key.encode()).hexdigest()


def parse_key(raw):
    """Returns (prefix, full_key) or None. The secret part is never logged or stored."""
    m = KEY_RE.match(raw or "")
    return (m.group(1), raw) if m else None


def _new_key():
    prefix = secrets.token_hex(4)
    return prefix, f"ahq_{prefix}_{secrets.token_urlsafe(32)}"


@transaction.atomic
def issue(data, user):
    """Create a client and return (client, full_key). The full key is shown once and cannot be recovered."""
    for _ in range(5):
        prefix, full = _new_key()
        try:
            with transaction.atomic():
                client = IntegrationClient.objects.create(
                    key_prefix=prefix, key_hash=hash_key(full), created_by=user,
                    created_by_username=getattr(user, "username", ""), **data)
            return client, full
        except IntegrityError:  # prefix collision (1 in 4 billion): try again
            continue
    raise RuntimeError("could not allocate a key prefix")


def rotate_key(client, expected_version):
    """Replace the credential; the old one stops working immediately."""
    from apps.core.concurrency import versioned_update
    prefix, full = _new_key()
    client = versioned_update(client, {"key_prefix": prefix, "key_hash": hash_key(full)}, expected_version)
    return client, full
