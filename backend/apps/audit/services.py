from django.conf import settings

from apps.core.middleware import get_correlation_id

from .models import AuditEvent


def client_ip(request):
    if request is None:
        return None
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


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
