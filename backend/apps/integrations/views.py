from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ScopedPermission
from apps.analytics import services as analytics
from apps.audit.services import client_ip, record
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from django.conf import settings

from . import services
from .authentication import IntegrationKeyAuthentication, IntegrationRateThrottle, IsIntegrationClient
from .models import IntegrationCall, IntegrationClient
from .serializers import IntegrationCallSerializer, IntegrationClientSerializer


def _meta(obj):
    return {"scopes": obj.scopes, "org_unit": obj.org_unit.code, "expires_at": obj.expires_at.isoformat(),
            "key_prefix": obj.key_prefix}


# ------------------------------------------------------------------------- administration (signed-in HQ users)
class IntegrationClientViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                               mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = IntegrationClientSerializer
    queryset = IntegrationClient.objects.select_related("org_unit")
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": ("integrations.view", "global"), "retrieve": ("integrations.view", "global"),
        "calls": ("integrations.view", "global"),
        "create": ("integrations.manage", "global"), "partial_update": ("integrations.manage", "global"),
        "rotate": ("integrations.manage", "global"), "revoke": ("integrations.manage", "global"),
    }

    def create(self, request, *args, **kwargs):
        services.require_enabled()
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            client, full_key = services.issue(ser.validated_data, request.user)
            record("integration.create", request=request, entity_type="integration_client", entity_id=client.pk,
                   metadata={"name": client.name, **_meta(client)})
        data = self.get_serializer(client).data
        return Response({**data, "key": full_key, "key_notice": "shown_once"}, status=201)

    def partial_update(self, request, *args, **kwargs):
        services.require_enabled()
        return super().partial_update(request, *args, **kwargs)

    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.save()
        record("integration.update", request=self.request, entity_type="integration_client", entity_id=obj.pk,
               metadata={"fields": sorted(serializer.validated_data.keys()), **_meta(obj)})

    @action(detail=True, methods=["post"])
    def rotate(self, request, pk=None):
        services.require_enabled()
        client = self.get_object()
        if client.unusable_reason() == "key_revoked":
            raise PermissionDenied("A revoked client cannot be rotated.", code="client_revoked")
        expected = require_version(request.data)
        with transaction.atomic():
            client, full_key = services.rotate_key(client, expected)
            record("integration.rotate", request=request, entity_type="integration_client", entity_id=client.pk,
                   metadata=_meta(client))
        return Response({**self.get_serializer(client).data, "key": full_key, "key_notice": "shown_once"})

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        """Always available, even while the feature flag is off: switching a credential off must never be blocked."""
        client = self.get_object()
        with transaction.atomic():
            changed = IntegrationClient.objects.filter(pk=client.pk, revoked_at__isnull=True).update(
                active=False, revoked_at=timezone.now(), updated_at=timezone.now())
            if changed:
                record("integration.revoke", request=request, entity_type="integration_client", entity_id=client.pk,
                       metadata=_meta(client))
        client.refresh_from_db()
        return Response(self.get_serializer(client).data)

    @action(detail=True, methods=["get"])
    def calls(self, request, pk=None):
        client = self.get_object()
        page = self.paginate_queryset(client.calls.all())
        return self.get_paginated_response(IntegrationCallSerializer(page, many=True).data)


# ------------------------------------------------------------------------------- external API (machine clients)
class ExtBase(APIView):
    authentication_classes = [IntegrationKeyAuthentication]
    permission_classes = [IsIntegrationClient]
    throttle_classes = [IntegrationRateThrottle]
    endpoint = ""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        client = getattr(request, "auth", None)
        if isinstance(client, IntegrationClient):
            code = response.status_code
            outcome = ("success" if code < 400 else "throttled" if code == 429
                       else "denied" if code in (401, 403, 404) else "error")
            http = request._request
            IntegrationCall.objects.create(
                client=client, endpoint=self.endpoint[:64], status_code=code, outcome=outcome,
                correlation_id=getattr(http, "correlation_id", ""), ip_address=client_ip(http))
            if outcome == "success":
                IntegrationClient.objects.filter(pk=client.pk).update(last_used_at=timezone.now())
        return response


class ExtMeView(ExtBase):
    endpoint = "me"

    def get(self, request):
        c = request.auth
        return Response({"name": c.name, "scopes": c.scopes, "org_unit": c.org_unit.code,
                         "expires_at": c.expires_at, "min_cell": settings.INTEGRATION_MIN_CELL})


class ExtAnalyticsView(ExtBase):
    def initial(self, request, *args, **kwargs):
        self.endpoint = f"analytics/{kwargs.get('section', '')}"[:64]
        super().initial(request, *args, **kwargs)

    def get(self, request, section):
        if section not in analytics.SECTIONS:
            raise NotFound()
        s = analytics.ClientScope(request.auth, settings.INTEGRATION_MIN_CELL)
        if section not in s.sections():
            raise PermissionDenied("This key is not allowed to read that section.", code="scope_denied")
        if request.query_params.get("unit") and not settings.INTEGRATION_ALLOW_UNIT_FILTER:
            raise field_error("unit", "unit_filter_not_allowed", "Unit filtering is not enabled for integration keys.")
        filters = analytics.parse_filters(request.query_params, s)
        data = analytics.compute(s, section, filters)
        if data is None:
            raise PermissionDenied("This key is not allowed to read that section.", code="scope_denied")
        return Response({"section": section, "min_cell": s.min_cell, "data": data})
