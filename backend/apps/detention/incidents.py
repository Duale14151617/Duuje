"""Custody incidents: deaths, injuries and use of force involving a person in custody.

* The station reports it (detention.manage for the station). The report is never edited or deleted.
* It is visible to everyone whose detention.view scope covers the station, so the district and regional commanders see it straight away,
  and it shows on the oversight dashboard as "awaiting review" until a regional authority (detention.incident_review) reviews it.
* The reviewer adds a note; nobody reviews their own report (the super administrator is the only exception, and it is audited).
* A death closes the person's register row with the outcome "Died in custody" in the same step, so nobody is left listed as held.
* The security-alert recipients are told that a report exists (type and station only, no names or details)."""
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts import alerts, scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.concurrency import VersionConflict, require_version
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.organization.models import OrganizationalUnit
from apps.vehicles.views import _uid, _unit_brief

from .models import CustodyIncident as I, DetentionRecord as R
from .views import _log, _not_future, _text, _when, close_record


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


def _out(i):
    return {"id": str(i.pk), "record": {"id": str(i.record_id), "register_no": i.record.register_no}, "org_unit": _unit_brief(i.org_unit),
            "kind": i.kind, "occurred_at": i.occurred_at, "place": i.place, "description": i.description, "people_involved": i.people_involved,
            "medical_attended": i.medical_attended, "medical_note": i.medical_note, "reported_by": i.reported_by_username,
            "reviewed": i.reviewed_at is not None, "reviewed_at": i.reviewed_at, "reviewed_by": i.reviewed_by_username, "review_note": i.review_note,
            "version": i.version}


class CustodyIncidentViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9a-f\-]{36}"
    permission_map = {"list": ("detention.view", "any"), "retrieve": ("detention.view", "any"), "create": ("detention.manage", "any"),
                      "review": ("detention.incident_review", "any")}

    def _scoped(self):
        q = scope.unit_scope_q(self.request.user, "detention.view", "org_unit__")
        return I.objects.none() if q is None else I.objects.filter(q).select_related("record", "org_unit")

    def _row(self, pk):
        row = self._scoped().filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None:
            raise Http404
        return row

    def list(self, request):
        p = request.query_params
        qs = self._scoped()
        if p.get("kind") in {c for c, _ in I.Kind.choices}:
            qs = qs.filter(kind=p["kind"])
        if p.get("reviewed") in ("0", "1"):
            qs = qs.filter(reviewed_at__isnull=p["reviewed"] == "0")
        if _uid(p.get("unit")):
            prefix = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).values_list("path", flat=True).first()
            qs = qs.filter(org_unit__path__startswith=prefix) if prefix else qs.none()
        page = self.paginate_queryset(qs.order_by("-occurred_at"))
        record_read(request, "detention.read_incidents", entity_type="custody_incident", count=len(page))
        return self.get_paginated_response([_out(i) for i in page])

    def retrieve(self, request, pk=None):
        i = self._row(pk)
        record_read(request, "detention.read_incident", entity_type="custody_incident", entity_id=i.pk, org_unit=i.org_unit)
        return Response(_out(i))

    @transaction.atomic
    def create(self, request):
        d = json_body(request)
        rec = R.objects.select_for_update().select_related("org_unit").filter(pk=_uid(d.get("record"))).first() if _uid(d.get("record")) else None
        if rec is None or rec.status == R.Status.VOID or not scope.can(request.user, "detention.manage", unit=rec.org_unit):
            raise field_error("record", "unknown", "Choose the person from your station's register.")
        kind = d.get("kind")
        if kind not in {c for c, _ in I.Kind.choices}:
            raise field_error("kind", "invalid_choice", "Choose death, injury or use of force.")
        when = _not_future(_when(d.get("occurred_at"), "occurred_at", timezone.now()), "occurred_at")
        if when < rec.booked_at:
            raise field_error("occurred_at", "before_booking", "This cannot be earlier than the booking time.")
        i = I.objects.create(record=rec, org_unit=rec.org_unit, kind=kind, occurred_at=when, place=_text(d, "place", 200),
                             description=_text(d, "description", 1000, required=True), people_involved=_text(d, "people_involved", 300),
                             medical_attended=d.get("medical_attended") in (True, "true", "1", 1, "on"), medical_note=_text(d, "medical_note", 300),
                             reported_by_username=request.user.username)
        _log(rec, "incident", request, f"{I.Kind(kind).label} reported (see the incident report)", when)  # no details in the custody log
        if kind == I.Kind.DEATH and rec.status == R.Status.IN_CUSTODY:
            rec.refresh_from_db()
            close_record(request, rec, {"outcome": "died_in_custody", "outcome_note": "See the custody incident report.", "ended_at": when.isoformat()}, rec.version)
        record("detention.incident_report", request=request, entity_type="custody_incident", entity_id=i.pk,
               metadata={"kind": kind, "register_no": rec.register_no, "org_unit": str(rec.org_unit_id)})
        alerts.notify("custody incident reported", f"A custody incident ({I.Kind(kind).label.lower()}) was reported at {rec.org_unit.name_en}. "
                      "Open the system to read and review the report.", request=request, actor=request.user)
        return Response(_out(i), status=201)

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """The regional authority reviews a report and records what was decided or referred. Not by the person who reported it."""
        d = json_body(request)
        row = self._row(pk)
        if not scope.can(request.user, "detention.incident_review", unit=row.org_unit):
            raise Http404
        with transaction.atomic():
            i = I.objects.select_for_update().select_related("record", "org_unit").get(pk=row.pk)
            if i.version != require_version(d):
                raise VersionConflict()
            if i.reviewed_at:
                raise field_error("state", "already_reviewed", "This report has already been reviewed.")
            if i.reported_by_username == request.user.username and not scope.self_approval_allowed(request.user, "custody_incident_review", request, "custody_incident", i.pk):
                raise field_error("state", "own_report", "A different authorised person must review a report you made.")
            i.review_note = _text(d, "note", 500, required=True)
            i.reviewed_at, i.reviewed_by_username, i.version = timezone.now(), request.user.username, i.version + 1
            i.save()
            record("detention.incident_review", request=request, entity_type="custody_incident", entity_id=i.pk, metadata={"kind": i.kind})
        return Response(_out(i))
