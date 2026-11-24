"""Shift handover: one note at the end of a shift saying who is in custody, what is pending and what to watch.

* The server copies the list of people in custody from the register when the note is written, so the note shows what was true then.
  The officer adds their own words (pending, watch, optional custody note); both of those are required, "nothing" is a valid answer.
* The next officer must acknowledge it. The author cannot acknowledge their own note, and an acknowledgement is final.
* Until the station's latest note has been acknowledged, nobody except its author can write the next one. That is what makes the
  acknowledgement mean something: the incoming officer reads it before handing over their own shift.
* Notes and acknowledgements are append-only (database triggers). Access reuses detention.view (read) and detention.manage (write and
  acknowledge), narrowed to the caller's units. Audit data holds counts and ids, never names or the text of the note.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.organization.models import OrganizationalUnit
from apps.vehicles.views import _uid, _unit_brief

from .models import DetentionRecord as R, ShiftHandover as H, ShiftHandoverAck as Ack
from .views import _actor, _not_future, _text, _when, court_flags, held_hours, is_overdue

MAX_PEOPLE = 200  # a station that holds more than this has a bigger problem than a long note


def ack_hours():
    """A note still unacknowledged after this many hours is shown as overdue (an alert, not a rule)."""
    return int(getattr(settings, "DETENTION_HANDOVER_ACK_HOURS", 12))


def snapshot(unit, now=None):
    now = now or timezone.now()
    rows = R.objects.filter(org_unit=unit, status=R.Status.IN_CUSTODY).prefetch_related("hearings").order_by("booked_at")[:MAX_PEOPLE]
    out = []
    for r in rows:
        f = court_flags(r, now)
        out.append({"register_no": r.register_no, "name": r.detainee_name, "cell": r.cell, "held_hours": held_hours(r, now),
                    "review_due": is_overdue(r, now), "court_soon": f["court_soon"], "remand_expired": f["remand_expired"]})
    return out


def _out(h, now=None):
    now = now or timezone.now()
    ack = getattr(h, "ack", None)
    return {"id": str(h.pk), "org_unit": _unit_brief(h.org_unit), "shift_ended_at": h.shift_ended_at, "custody": h.custody_snapshot,
            "custody_note": h.custody_note, "pending": h.pending, "watch": h.watch, "written_by": h.written_by_username, "written_at": h.created_at,
            "acknowledged": None if ack is None else {"by": ack.acknowledged_by_username, "at": ack.acknowledged_at, "comment": ack.comment},
            "ack_overdue": ack is None and now - h.created_at >= timedelta(hours=ack_hours())}


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


class ShiftHandoverViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9a-f\-]{36}"
    permission_map = {"list": ("detention.view", "any"), "retrieve": ("detention.view", "any"), "waiting": ("detention.view", "any"),
                      "preview": ("detention.manage", "any"), "create": ("detention.manage", "any"), "acknowledge": ("detention.manage", "any")}

    def _scoped(self):
        q = scope.unit_scope_q(self.request.user, "detention.view", "org_unit__")
        return H.objects.none() if q is None else H.objects.filter(q).select_related("org_unit", "ack")

    def _unit(self, value, code="detention.manage"):
        u = OrganizationalUnit.objects.filter(pk=_uid(value)).first() if _uid(value) else None
        if u is None or not scope.can(self.request.user, code, unit=u):
            raise field_error("org_unit", "unknown", "Choose the station this handover is for.")
        return u

    def list(self, request):
        p, qs = request.query_params, self._scoped()
        if _uid(p.get("unit")):
            prefix = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).values_list("path", flat=True).first()
            qs = qs.filter(org_unit__path__startswith=prefix) if prefix else qs.none()
        if p.get("waiting") == "1":
            qs = qs.filter(ack__isnull=True)
        page = self.paginate_queryset(qs.order_by("-created_at"))
        record_read(request, "handover.read_list", entity_type="shift_handover", count=len(page))
        now = timezone.now()
        return self.get_paginated_response([_out(h, now) for h in page])

    def retrieve(self, request, pk=None):
        h = self._scoped().filter(pk=_uid(pk)).first() if _uid(pk) else None
        if h is None:
            raise Http404
        record_read(request, "handover.read", entity_type="shift_handover", entity_id=h.pk, org_unit=h.org_unit)
        return Response(_out(h))

    @action(detail=False, methods=["get"])
    def waiting(self, request):
        """Notes waiting for acknowledgement in the caller's stations, and how many of them this person may acknowledge (not their own)."""
        qs = self._scoped().filter(ack__isnull=True)
        me = request.user.username
        can_ack = [h for h in qs if h.written_by_username != me and scope.can(request.user, "detention.manage", unit=h.org_unit)]
        now = timezone.now()
        record_read(request, "handover.read_waiting", entity_type="shift_handover", count=qs.count())
        return Response({"waiting": qs.count(), "for_me": len(can_ack), "overdue": sum(1 for h in can_ack if _out(h, now)["ack_overdue"]),
                         "results": [_out(h, now) for h in can_ack[:20]]})

    @action(detail=False, methods=["get"])
    def preview(self, request):
        """What the note will list as in custody right now (?unit=), and whether the previous note blocks a new one."""
        unit = self._unit(request.query_params.get("unit"))
        last = H.objects.filter(org_unit=unit).select_related("ack").order_by("-created_at").first()
        blocked = last is not None and not hasattr(last, "ack") and last.written_by_username != request.user.username
        return Response({"org_unit": _unit_brief(unit), "custody": snapshot(unit), "blocked_by": _out(last) if blocked else None})

    def create(self, request):
        d = json_body(request)
        unit = self._unit(d.get("org_unit"))
        pending, watch = _text(d, "pending", 2000, required=True), _text(d, "watch", 2000, required=True)
        note = _text(d, "custody_note", 1000)
        ended = _not_future(_when(d.get("shift_ended_at"), "shift_ended_at", timezone.now()), "shift_ended_at")
        me = _actor(request)
        with transaction.atomic():
            OrganizationalUnit.objects.select_for_update().get(pk=unit.pk)  # two officers writing at once cannot both pass the check below
            last = H.objects.filter(org_unit=unit).select_related("ack").order_by("-created_at").first()
            if last is not None and not hasattr(last, "ack") and last.written_by_username != me:
                raise field_error("handover", "previous_unacknowledged", "Acknowledge the previous handover note before writing yours.")
            people = snapshot(unit)
            h = H.objects.create(org_unit=unit, shift_ended_at=ended, custody_snapshot=people, custody_note=note, pending=pending, watch=watch,
                                 written_by_username=me)
            record("handover.create", request=request, entity_type="shift_handover", entity_id=h.pk, metadata={"org_unit": str(unit.pk), "in_custody": len(people)})
        return Response(_out(self._scoped().get(pk=h.pk)), status=201)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        d = json_body(request)
        h = self._scoped().filter(pk=_uid(pk)).first() if _uid(pk) else None
        if h is None or not scope.can(request.user, "detention.manage", unit=h.org_unit):
            raise Http404
        me = _actor(request)
        if h.written_by_username == me:
            raise field_error("handover", "own_handover", "The next officer must acknowledge this note, not the one who wrote it.")
        if hasattr(h, "ack"):
            raise field_error("handover", "already_acknowledged", "This handover note has already been acknowledged.")
        comment = _text(d, "comment", 300)
        try:
            with transaction.atomic():
                Ack.objects.create(handover=h, acknowledged_by_username=me, comment=comment)
        except IntegrityError:  # someone acknowledged it a moment ago
            raise field_error("handover", "already_acknowledged", "This handover note has already been acknowledged.")
        record("handover.acknowledge", request=request, entity_type="shift_handover", entity_id=h.pk, metadata={"org_unit": str(h.org_unit_id)})
        return Response(_out(self._scoped().get(pk=h.pk)))
