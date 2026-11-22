"""Occurrence Book API. Access reuses the detention permissions: detention.view to read, detention.manage to write (the custody / duty
officer keeps both registers), both narrowed to the caller's unit scope. Out-of-scope entries answer 404. Reads are audited."""
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.detention.models import DetentionRecord
from apps.detention.views import _day
from apps.organization.models import OrganizationalUnit
from apps.vehicles.views import _uid, _unit_brief

from . import services
from .models import OccurrenceEntry as E


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


def _out(e):
    det = e.detention_record
    return {"id": str(e.pk), "ob_number": e.ob_number, "org_unit": _unit_brief(e.org_unit), "category": e.category, "occurred_at": e.occurred_at,
            "location": e.location, "reported_by": e.reported_by, "summary": e.summary, "details": e.details,
            "detention": None if det is None else {"id": str(det.pk), "register_no": det.register_no},
            "status": e.status, "recorded_by": e.recorded_by_username, "voided_reason": e.voided_reason if e.status == E.Status.VOID else "",
            "version": e.version}


def _follow_out(f):
    return {"id": str(f.pk), "kind": f.kind, "occurred_at": f.occurred_at, "text": f.text, "by": f.by_username}


class OccurrenceViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9a-f\-]{36}"
    permission_map = {"list": ("detention.view", "any"), "retrieve": ("detention.view", "any"), "summary": ("detention.view", "any"),
                      "create": ("detention.manage", "any"), "follow_up": ("detention.manage", "any"), "void": ("detention.manage", "any")}

    def _scoped(self):
        q = scope.unit_scope_q(self.request.user, "detention.view", "org_unit__")
        return E.objects.none() if q is None else E.objects.filter(q).select_related("org_unit", "detention_record")

    def _row(self, pk, write=False):
        row = self._scoped().filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None or (write and not scope.can(self.request.user, "detention.manage", unit=row.org_unit)):
            raise Http404
        return row

    def _fresh(self, pk):
        return _out(E.objects.select_related("org_unit", "detention_record").get(pk=pk))

    def list(self, request):
        p = request.query_params
        qs = self._scoped()
        if p.get("status") in {"recorded", "void"}:
            qs = qs.filter(status=p["status"])
        elif p.get("include_void") != "1":
            qs = qs.exclude(status="void")
        if p.get("category") in services.CATEGORIES:
            qs = qs.filter(category=p["category"])
        if _uid(p.get("unit")):
            prefix = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).values_list("path", flat=True).first()
            qs = qs.filter(org_unit__path__startswith=prefix) if prefix else qs.none()
        if p.get("from"):
            qs = qs.filter(occurred_at__date__gte=_day(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(occurred_at__date__lte=_day(p["to"], "to"))
        if p.get("q"):
            s = p["q"].strip()[:60]
            qs = qs.filter(Q(ob_number__icontains=s) | Q(summary__icontains=s) | Q(details__icontains=s) | Q(reported_by__icontains=s) | Q(location__icontains=s))
        page = self.paginate_queryset(qs.order_by("-occurred_at", "-ob_seq"))
        record_read(request, "occurrence.read_list", entity_type="occurrence_book", count=len(page))
        return self.get_paginated_response([_out(e) for e in page])

    def retrieve(self, request, pk=None):
        e = self._row(pk)
        record_read(request, "occurrence.read_entry", entity_type="occurrence_entry", entity_id=e.pk, org_unit=e.org_unit)
        return Response({**_out(e), "follow_ups": [_follow_out(f) for f in e.follow_ups.all()]})

    def create(self, request):
        d = json_body(request)
        unit = OrganizationalUnit.objects.filter(pk=_uid(d.get("org_unit"))).first() if _uid(d.get("org_unit")) else None
        if unit is None or not scope.can(request.user, "detention.manage", unit=unit):
            raise field_error("org_unit", "unknown", "Choose the station whose Occurrence Book this goes in.")
        det = None
        if d.get("detention_record") not in (None, ""):
            det = DetentionRecord.objects.filter(pk=_uid(d["detention_record"]), org_unit=unit).first() if _uid(d["detention_record"]) else None
            if det is None:
                raise field_error("detention_record", "unknown", "Unknown detention record for this station.")
        e = services.create_entry(request, unit, d, detention=det)
        return Response(self._fresh(e.pk), status=201)

    @action(detail=True, methods=["post"], url_path="follow-up")
    def follow_up(self, request, pk=None):
        d = json_body(request)
        e = services.add_follow_up(request, self._row(pk, write=True), d, require_version(d))
        return Response(self._fresh(e.pk), status=201)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        d = json_body(request)
        e = services.void_entry(request, self._row(pk, write=True), d, require_version(d))
        return Response(self._fresh(e.pk))

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self._scoped().exclude(status="void")
        today = timezone.localdate()
        out = {"today": qs.filter(occurred_at__date=today).count(), "this_year": qs.filter(ob_year=today.year).count(),
               "arrests_today": qs.filter(occurred_at__date=today, category="arrest").count()}
        record_read(request, "occurrence.read_summary", entity_type="occurrence_summary")
        return Response(out)
