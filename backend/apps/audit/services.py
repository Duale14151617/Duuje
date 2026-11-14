import ipaddress
import logging

from django.conf import settings

from apps.core.middleware import get_correlation_id

from .models import AuditEvent

logger = logging.getLogger(__name__)


def _valid_ip(value):
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def client_ip(request):
    """Address of the caller. Behind `NUM_PROXIES` trusted proxies the real client is the Nth entry FROM THE RIGHT of
    X-Forwarded-For: everything to its left was supplied by the client and can be forged. Anything that is not a valid IP is
    discarded (a forged value would otherwise break the audit insert or let an attacker dodge per-address lockouts)."""
    if request is None:
        return None
    if getattr(settings, "DEBUG_CLIENT_IP", False) and not getattr(request, "_client_ip_logged", False):
        # Temporary diagnostic (env DEBUG_CLIENT_IP=1): shows which header holds the real client address behind the host's proxies.
        # Logged once per request. Turn it off again once NUM_PROXIES is settled; it writes client addresses to the logs.
        try:
            request._client_ip_logged = True
        except AttributeError:
            pass
        meta = request.META
        logger.warning("client-ip debug: remote_addr=%s xff=%s cf=%s true_client=%s real_ip=%s num_proxies=%s",
                       meta.get("REMOTE_ADDR"), meta.get("HTTP_X_FORWARDED_FOR"), meta.get("HTTP_CF_CONNECTING_IP"),
                       meta.get("HTTP_TRUE_CLIENT_IP"), meta.get("HTTP_X_REAL_IP"), getattr(settings, "NUM_PROXIES", None))
    if settings.TRUST_PROXY_HEADERS:
        forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
        hops = max(int(getattr(settings, "NUM_PROXIES", 1) or 1), 1)
        if forwarded:
            candidate = forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
            ip = _valid_ip(candidate)
            if ip:
                return ip
    return _valid_ip(request.META.get("REMOTE_ADDR"))


def record(action, *, request=None, actor=None, entity_type="", entity_id="", outcome="success", metadata=None):
    """Write one audit event. Never pass secrets or full request bodies in metadata."""
    if actor is None and request is not None:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            actor = user
    return AuditEvent.objects.create(
        actor_id=getattr(actor, "pk", None),
        actor_username=getattr(actor, "username", "") or "",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else "",
        outcome=outcome,
        correlation_id=get_correlation_id(),
        ip_address=client_ip(request),
        metadata=metadata or {},
    )


def record_read(request, action, *, entity_type, entity_id="", org_unit=None, count=None):
    """Audit a sensitive READ (weapon register, attendance records). Called server-side from the view action itself, so a
    direct API request cannot skip it. Records who, what resource, when (occurred_at) and the organizational scope; never
    the returned rows, serial numbers or personal data."""
    meta = {}
    if org_unit is not None:
        meta["org_unit"] = str(getattr(org_unit, "pk", org_unit))
        path = getattr(org_unit, "path", None)
        if path:
            meta["org_path"] = path
    if count is not None:
        meta["count"] = int(count)
    return record(action, request=request, entity_type=entity_type, entity_id=entity_id, metadata=meta)
