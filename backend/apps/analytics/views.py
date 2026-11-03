from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record

from . import services


class AnalyticsViewSet(viewsets.GenericViewSet):
    """Aggregate analytics for signed-in users. The gate is `analytics.view`; each section additionally needs the
    permission that already governs its data (personnel.view, reports.summary, logistics.report, training.report)
    and is limited to the units that permission covers. Read-only; no exports."""

    permission_classes = [ScopedPermission]
    pagination_class = None
    permission_map = {
        "list": ("analytics.view", "any"), "personnel": ("analytics.view", "any"), "reports": ("analytics.view", "any"),
        "logistics": ("analytics.view", "any"), "training": ("analytics.view", "any"),
    }

    def list(self, request):
        return Response({"sections": services.UserScope(request.user).sections()})

    def _section(self, request, name):
        s = services.UserScope(request.user)
        filters = services.parse_filters(request.query_params, s)
        data = services.compute(s, name, filters)
        if data is None:
            record("access.denied", request=request, outcome="denied", entity_type="analytics",
                   metadata={"section": name, "permission": services.SECTION_PERMISSION[name]})
            raise PermissionDenied()
        return Response(data)

    @action(detail=False, methods=["get"])
    def personnel(self, request):
        return self._section(request, "personnel")

    @action(detail=False, methods=["get"])
    def reports(self, request):
        return self._section(request, "reports")

    @action(detail=False, methods=["get"])
    def logistics(self, request):
        return self._section(request, "logistics")

    @action(detail=False, methods=["get"])
    def training(self, request):
        return self._section(request, "training")
