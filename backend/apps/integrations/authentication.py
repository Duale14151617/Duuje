"""Bearer-key authentication for the /ext/ endpoints. Sessions and cookies are never used here."""
import hmac

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, NotFound, Throttled
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from apps.audit.services import client_ip, record

from . import services
from .models import IntegrationClient

_DUMMY = "0" * 64


def _fail_key(ip):
    return f"integ-fail:{ip or 'unknown'}"


def _blocked(ip):
    return cache.get(_fail_key(ip), 0) >= settings.INTEGRATION_FAIL_LIMIT


def _register_failure(ip):
    key = _fail_key(ip)
    cache.add(key, 0, settings.INTEGRATION_FAIL_WINDOW)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, settings.INTEGRATION_FAIL_WINDOW)


class IntegrationKeyAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer realm="armyhq-integration"'

    def _fail(self, request, code, message, prefix="", client=None):
        http = request._request  # the DRF Request would recurse into authentication
        _register_failure(client_ip(http))
        record("integration.auth_failed", request=http, outcome="denied", entity_type="integration_client",
               entity_id=client.pk if client else "", metadata={"reason": code, "key_prefix": prefix[:12]})
        raise AuthenticationFailed(message, code=code)

    def authenticate(self, request):
        if not settings.INTEGRATIONS_ENABLED:
            raise NotFound()  # the whole surface is invisible while the feature is off
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        http = request._request
        ip = client_ip(http)
        if _blocked(ip):
            raise Throttled(wait=settings.INTEGRATION_FAIL_WINDOW)
        if len(parts) != 2:
            self._fail(request, "invalid_key", "Invalid credentials.")
        try:
            raw = parts[1].decode("ascii")
        except UnicodeDecodeError:
            self._fail(request, "invalid_key", "Invalid credentials.")
        parsed = services.parse_key(raw)
        client = (IntegrationClient.objects.select_related("org_unit").filter(key_prefix=parsed[0]).first()
                  if parsed else None)
        supplied = services.hash_key(raw)
        if not (hmac.compare_digest(supplied, client.key_hash if client else _DUMMY) and client is not None):
            self._fail(request, "invalid_key", "Invalid credentials.", prefix=parsed[0] if parsed else "")
        reason = client.unusable_reason(timezone.now())  # only reachable with a correct secret
        if reason:
            self._fail(request, reason, "This key is no longer valid.", prefix=client.key_prefix, client=client)
        return (AnonymousUser(), client)


class IsIntegrationClient(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, IntegrationClient)


class IntegrationRateThrottle(SimpleRateThrottle):
    """Per client, not per address: one noisy integration cannot starve the others."""

    scope = "integration"

    def get_cache_key(self, request, view):
        client = request.auth
        if not isinstance(client, IntegrationClient):
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(client.pk)}
