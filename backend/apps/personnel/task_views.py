"""Administrative task tracking API (/operations/tasks/)."""
from datetime import date

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import uuid_param
from apps.organization.models import OrganizationalUnit

from . import tasks as svc
from .models import Personnel, UnitTask
from .services import NOT_SERVING

VIEW, MANAGE = "tasks.view", "tasks.manage"
LIMIT = 200


def _out(t, events=False):
    today = date.today()
    r = t.responsible
    d = {"id": str(t.pk), "org_unit": str(t.org_unit_id), "org_unit_name": t.org_unit.name_en, "title": t.title,
         "description": t.description, "authority_ref": t.authority_ref, "assigned_on": t.assigned_on.isoformat(),
         "due_on": t.due_on.isoformat() if t.due_on else None, "status": t.status,
         "overdue": bool(t.due_on and t.due_on < today and t.status in svc.OPEN),
         "responsible": ({"id": str(r.pk), "full_name": r.full_name, "service_number": r.service_number, "rank": r.rank.name_en} if r else None),
         "completion_report": t.completion_report, "document_ref": t.document_ref, "cancel_reason": t.cancel_reason,
         "completed_at": t.completed_at.isoformat() if t.completed_at else None, "created_by": t.created_by_username, "version": t.version}
    if events:
        d["events"] = [{"kind": e.kind, "from_status": e.from_status, "to_status": e.to_status, "note": e.note,
                        "actor": e.actor_username, "at": e.created_at.isoformat()} for e in t.events.all()]
    return d


class UnitTaskViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    queryset = UnitTask.objects.select_related("org_unit", "responsible__rank")
    permission_map = {
        "list": (VIEW, "global"), "retrieve": (VIEW, "global"), "members": (MANAGE, "global"),
        "create": (MANAGE, "global"), "partial_update": (MANAGE, "global"), "start": (MANAGE, "global"),
        "complete": (MANAGE, "global"), "cancel": (MANAGE, "global"),
    }

    def get_queryset(self):
        q = scope.unit_scope_q(self.request.user, VIEW, "org_unit__")
        qs = super().get_queryset()
        qs = qs.filter(q) if q is not None else qs.none()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("overdue") == "1":
            qs = qs.filter(due_on__lt=date.today(), status__in=svc.OPEN)
        unit_id = uuid_param(self.request, "org_unit")
        if unit_id:
            unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
            qs = qs.filter(org_unit__path__startswith=unit.path) if unit else qs.none()
        return qs

    def list(self, request):
        rows = list(self.get_queryset()[:LIMIT])
        record("task.list", request=request, entity_type="unit_task", metadata={"count": len(rows)})
        return Response({"results": [_out(t) for t in rows]})

    def retrieve(self, request, pk=None):
        t = self.get_object()
        record("task.view", request=request, entity_type="unit_task", entity_id=t.pk)
        return Response(_out(t, events=True))

    def create(self, request):
        return Response(_out(svc.create(request, request.data), events=True), status=201)

    def partial_update(self, request, pk=None):
        return Response(_out(svc.update(request, self.get_object(), request.data, require_version(request.data)), events=True))

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return Response(_out(svc.start(request, self.get_object(), require_version(request.data)), events=True))

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return Response(_out(svc.complete(request, self.get_object(), request.data, require_version(request.data)), events=True))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(_out(svc.cancel(request, self.get_object(), request.data, require_version(request.data)), events=True))

    @action(detail=False, methods=["get"])
    def members(self, request):
        """Serving people in a unit and below, for choosing who is responsible (name, rank, service number only)."""
        unit = svc._unit(request.user, request.query_params.get("org_unit"))
        people = Personnel.objects.filter(org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING).select_related("rank", "org_unit")
        text = (request.query_params.get("q") or "").strip()
        if text:
            people = people.filter(Q(full_name__icontains=text) | Q(service_number__iexact=text))
        rows = list(people.order_by("full_name")[:LIMIT])
        record("task.members_lookup", request=request, entity_type="personnel", metadata={"unit": str(unit.pk), "count": len(rows)})
        return Response({"results": [{"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                                      "rank": p.rank.name_en, "unit": p.org_unit.name_en} for p in rows]})
