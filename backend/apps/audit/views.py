from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, viewsets

from apps.accounts.permissions import ScopedPermission
from apps.core.errors import field_error

from .models import AuditEvent
from .services import record
from .serializers import AuditEventSerializer


class AuditEventViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only. Requires audit.view at headquarters (unscoped) level."""

    serializer_class = AuditEventSerializer
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("audit.view", "global"), "retrieve": ("audit.view", "global")}

    def get_queryset(self):
        qs = AuditEvent.objects.all()
        p = self.request.query_params
        for param, field in (("action", "action"), ("entity_type", "entity_type"),
                             ("outcome", "outcome"), ("actor", "actor_username"),
                             ("correlation_id", "correlation_id")):
            if p.get(param):
                qs = qs.filter(**{field: p[param]})
        try:
            if p.get("from"):
                qs = qs.filter(occurred_at__gte=p["from"])
            if p.get("to"):
                qs = qs.filter(occurred_at__lte=p["to"])
        except (DjangoValidationError, ValueError):
            raise field_error("from", "invalid_date", "Invalid date.")
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        record("audit.read", request=request, entity_type="audit_event",
               metadata={"filters": {k: v for k, v in request.query_params.items() if k != "page"}, "page": request.query_params.get("page", "1")})
        return response

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        record("audit.read", request=request, entity_type="audit_event", entity_id=kwargs.get("pk"))
        return response
