"""Leave requests and the duty roster. Neither changes personnel status or attendance records."""
import uuid
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record as audit
from apps.audit.services import record_read
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from . import notify
from .models import LeaveRequest, LeaveType, RosterShift

MAX_DAYS = 366
MAX_ROSTER_ROWS = 500
MAX_ROSTER_SPAN = 62
SHIFTS = {s.value for s in RosterShift.Shift}
NOT_FOUND = {"code": "not_found", "detail": "Not found."}


def _uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _day(value, name):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise field_error(name, "invalid_date", "Use a date like 2026-03-01.")


def _unit(request, value, code):
    """Unknown and out-of-scope units read alike, so ids cannot be probed."""
    unit = OrganizationalUnit.objects.filter(pk=_uid(value)).first() if _uid(value) else None
    if unit is None or not scope.can(request.user, code, unit=unit):
        raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
    return unit


def _own_personnel(user):
    return Personnel.objects.select_related("org_unit", "rank").filter(account_id=user.pk).first()


def _out(r):
    p = r.personnel
    return {"id": str(r.pk), "personnel": {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number},
            "org_unit": {"id": str(r.org_unit_id), "code": r.org_unit.code, "name_en": r.org_unit.name_en, "name_so": r.org_unit.name_so},
            "leave_type": {"code": r.leave_type.code, "name_en": r.leave_type.name_en, "name_so": r.leave_type.name_so},
            "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(),
            "days": (r.end_date - r.start_date).days + 1, "reason": r.reason, "status": r.status,
            "requested_by": r.requested_by_username, "decided_by": r.decided_by_username, "decided_at": r.decided_at,
            "decision_note": r.decision_note, "created_at": r.created_at}


class LeaveViewSet(viewsets.ViewSet):
    """Leave requests. A member asks for their own leave; a commander can ask on behalf of people in scope; an approver
    decides. Nobody decides their own request (only the super administrator can, and that is audited)."""

    permission_classes = [ScopedPermission]
    permission_map = {
        "list": (("leave.view", "leave.own"), "any"), "types": (("leave.view", "leave.own"), "any"),
        "create": (("leave.request", "leave.own"), "any"),
        "approve": ("leave.approve", "any"), "reject": ("leave.approve", "any"),
        "cancel": (("leave.request", "leave.own", "leave.approve"), "any"),
    }
    queryset = LeaveRequest.objects.none()

    def _visible(self, request):
        """Requests the caller may see: units in scope under leave.view, plus their own."""
        q = Q()
        view_q = scope.unit_scope_q(request.user, "leave.view", "org_unit__")
        if view_q is not None:
            q |= view_q
        me = _own_personnel(request.user)
        if me is not None:
            q |= Q(personnel_id=me.pk)
        if not q:
            return LeaveRequest.objects.none()
        return LeaveRequest.objects.filter(q).select_related("personnel", "org_unit", "leave_type").distinct()

    def list(self, request):
        qs = self._visible(request)
        status = request.query_params.get("status")
        if status in {s.value for s in LeaveRequest.Status}:
            qs = qs.filter(status=status)
        uid = uuid_param(request, "org_unit")
        if uid:
            unit = OrganizationalUnit.objects.filter(pk=uid).first()
            qs = qs.filter(org_unit__path__startswith=unit.path) if unit else qs.none()
        if request.query_params.get("mine") == "1":
            me = _own_personnel(request.user)
            qs = qs.filter(personnel_id=me.pk) if me else qs.none()
        rows = list(qs[:200])
        record_read(request, "leave.read", entity_type="leave", count=len(rows))
        return Response({"results": [_out(r) for r in rows]})

    @action(detail=False, methods=["get"])
    def types(self, request):
        return Response({"results": [{"code": t.code, "name_en": t.name_en, "name_so": t.name_so, "max_days": t.max_days}
                                     for t in LeaveType.objects.filter(active=True)]})

    def create(self, request):
        """{leave_type, start_date, end_date, reason?, personnel?}. Without `personnel` the request is for the caller."""
        d = json_body(request)
        me = _own_personnel(request.user)
        pid = _uid(d.get("personnel")) if d.get("personnel") else None
        if d.get("personnel") and pid is None:
            raise field_error("personnel", "person_unknown", "Unknown person.")
        if pid is None or (me is not None and pid == str(me.pk)):
            if me is None or not scope.has_anywhere(request.user, "leave.own"):
                raise field_error("personnel", "person_unknown", "Choose the person the leave is for.")
            person = me
        else:
            person = Personnel.objects.select_related("org_unit").filter(pk=pid).first()
            if person is None or not scope.can(request.user, "leave.request", unit=person.org_unit):
                raise field_error("personnel", "person_unknown", "Unknown person.")  # unknown and out of scope read alike
        if person.status in NOT_SERVING:
            raise field_error("personnel", "person_not_serving", "This person is no longer serving.")
        ltype = LeaveType.objects.filter(code=d.get("leave_type"), active=True).first()
        if ltype is None:
            raise field_error("leave_type", "invalid_type", "Choose a leave type.")
        start, end = _day(d.get("start_date"), "start_date"), _day(d.get("end_date"), "end_date")
        if end < start:
            raise field_error("end_date", "end_before_start", "The end date cannot be before the start date.")
        days = (end - start).days + 1
        if days > MAX_DAYS or (ltype.max_days and days > ltype.max_days):
            raise field_error("end_date", "too_long", "That is longer than this leave type allows.")
        if start < timezone.localdate() - timedelta(days=30):
            raise field_error("start_date", "too_far_back", "Leave cannot start more than 30 days in the past.")
        with transaction.atomic():
            Personnel.objects.select_for_update().filter(pk=person.pk).first()  # serialize overlapping requests for one person
            clash = LeaveRequest.objects.filter(personnel=person, status__in=["pending", "approved"],
                                                start_date__lte=end, end_date__gte=start).exists()
            if clash:
                raise field_error("start_date", "overlap", "This person already has leave that overlaps these dates.")
            r = LeaveRequest.objects.create(
                personnel=person, org_unit=person.org_unit, leave_type=ltype, start_date=start, end_date=end,
                reason=str(d.get("reason") or "").strip()[:300], requested_by_id=request.user.pk,
                requested_by_username=request.user.username)
            audit("leave.requested", request=request, entity_type="leave", entity_id=r.pk,
                  metadata={"unit": person.org_unit.code, "type": ltype.code, "days": days})
        r = LeaveRequest.objects.select_related("personnel", "org_unit", "leave_type").get(pk=r.pk)
        notify.pending(r)
        return Response(_out(r), status=201)

    def _decidable(self, request, pk):
        r = LeaveRequest.objects.select_related("personnel", "org_unit", "leave_type").filter(pk=_uid(pk)).first() if _uid(pk) else None
        if r is None or not scope.can(request.user, "leave.approve", unit=r.org_unit):
            return None
        return r

    def _decide(self, request, pk, status, event):
        with transaction.atomic():
            r = self._decidable(request, pk)
            if r is None:
                return Response(NOT_FOUND, status=404)
            r = LeaveRequest.objects.select_for_update().select_related("personnel", "org_unit", "leave_type").get(pk=r.pk)
            if r.status != "pending":
                return Response({"code": "invalid_transition", "detail": "Only a pending request can be decided."}, status=409)
            own = r.requested_by_id == request.user.pk or (r.personnel.account_id == request.user.pk)
            if own and not scope.self_approval_allowed(request.user, "leave_decision", request=request, entity_type="leave", entity_id=r.pk):
                audit(f"leave.{event}", request=request, outcome="denied", entity_type="leave", entity_id=r.pk, metadata={"why": "own_request"})
                return Response({"code": "own_request", "detail": "Someone else must decide this request."}, status=403)
            note = str(json_body(request).get("note") or "").strip()[:300]
            if status == "rejected" and not note:
                raise field_error("note", "note_required", "Say why the request is rejected.")
            r.status, r.decided_by_id, r.decided_by_username = status, request.user.pk, request.user.username
            r.decided_at, r.decision_note = timezone.now(), note
            r.save(update_fields=["status", "decided_by_id", "decided_by_username", "decided_at", "decision_note"])
            audit(f"leave.{event}", request=request, entity_type="leave", entity_id=r.pk, metadata={"unit": r.org_unit.code})
        notify.decided(r, f"leave_{status}", request.user)
        return Response(_out(r))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, pk, "approved", "approved")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, pk, "rejected", "rejected")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """The person or the one who asked, or an approver in scope, can cancel a request that has not started yet."""
        with transaction.atomic():
            r = LeaveRequest.objects.select_for_update().select_related("personnel", "org_unit", "leave_type").filter(
                pk=_uid(pk)).first() if _uid(pk) else None
            mine = r is not None and (r.requested_by_id == request.user.pk or r.personnel.account_id == request.user.pk)
            if r is None or not (mine or scope.can(request.user, "leave.approve", unit=r.org_unit)):
                return Response(NOT_FOUND, status=404)
            if r.status not in ("pending", "approved") or r.start_date <= timezone.localdate() and r.status == "approved":
                return Response({"code": "invalid_transition", "detail": "This request can no longer be cancelled."}, status=409)
            r.status = "cancelled"
            r.save(update_fields=["status"])
            audit("leave.cancelled", request=request, entity_type="leave", entity_id=r.pk, metadata={"unit": r.org_unit.code})
        notify.cancelled(r, request.user)
        return Response(_out(r))


class RosterViewSet(viewsets.ViewSet):
    """Duty roster for a unit and below. Setting a duty for someone on approved leave that day is refused."""

    permission_classes = [ScopedPermission]
    permission_map = {"list": ("roster.view", "any"), "assign": ("roster.manage", "any")}
    queryset = RosterShift.objects.none()

    def list(self, request):
        """?org_unit=<id>&from=YYYY-MM-DD&to=YYYY-MM-DD (at most 62 days): the shifts and the approved leave in that window."""
        unit = _unit(request, uuid_param(request, "org_unit"), "roster.view")
        start = _day(request.query_params.get("from") or timezone.localdate().isoformat(), "from")
        end = _day(request.query_params.get("to") or (start + timedelta(days=6)).isoformat(), "to")
        if end < start or (end - start).days >= MAX_ROSTER_SPAN:
            raise field_error("to", "invalid_range", "Choose a range of at most 62 days.")
        q = scope.unit_scope_q(request.user, "roster.view", "org_unit__")
        base = Q(org_unit__path__startswith=unit.path)
        shifts = list(RosterShift.objects.filter(q & base, duty_date__range=(start, end)).select_related("personnel").distinct()[:5000])
        leave = list(LeaveRequest.objects.filter(q & base, status="approved", start_date__lte=end, end_date__gte=start)
                     .select_related("leave_type").distinct()[:2000])
        people = (Personnel.objects.filter(q & Q(org_unit__path__startswith=unit.path)).exclude(status__in=NOT_SERVING)
                  .select_related("rank").order_by("-rank__sort_order", "full_name").distinct()[:1000])
        record_read(request, "roster.read", entity_type="roster", org_unit=unit, count=len(shifts))
        return Response({
            "org_unit": str(unit.pk), "from": start.isoformat(), "to": end.isoformat(),
            "people": [{"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                        "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}} for p in people],
            "shifts": [{"personnel": str(s.personnel_id), "date": s.duty_date.isoformat(), "shift": s.shift, "post": s.post} for s in shifts],
            "leave": [{"personnel": str(r.personnel_id), "from": r.start_date.isoformat(), "to": r.end_date.isoformat(),
                       "type": r.leave_type.code} for r in leave]})

    @action(detail=False, methods=["post"])
    def assign(self, request):
        """{org_unit, entries: [{personnel, date, shift, post?}]}. All entries are checked first; if any is wrong nothing is saved."""
        d = json_body(request)
        unit = _unit(request, d.get("org_unit"), "roster.manage")
        entries = d.get("entries")
        if not isinstance(entries, list) or not entries or len(entries) > MAX_ROSTER_ROWS:
            raise field_error("entries", "entries_invalid", "Send between 1 and 500 entries.")
        clean, errors, seen = [], [], set()
        for i, e in enumerate(entries):
            code, c = self._check(request, unit, e)
            if code is None and (c["person"].pk, c["day"]) in seen:
                code = "duplicate_entry"
            if code:
                errors.append({"index": i, "code": code})
                continue
            seen.add((c["person"].pk, c["day"]))
            clean.append(c)
        if errors:
            return Response({"code": "roster_invalid", "detail": "Fix the listed entries; nothing was saved.", "rows": errors}, status=400)
        with transaction.atomic():
            for c in clean:
                RosterShift.objects.update_or_create(
                    personnel=c["person"], duty_date=c["day"],
                    defaults={"org_unit": c["person"].org_unit, "shift": c["shift"], "post": c["post"],
                              "set_by_username": request.user.username})
            audit("roster.assigned", request=request, entity_type="roster", entity_id=unit.pk,
                  metadata={"unit": unit.code, "count": len(clean)})
        return Response({"saved": len(clean)}, status=201)

    @staticmethod
    def _check(request, unit, e):
        if not isinstance(e, dict) or e.get("shift") not in SHIFTS:
            return "invalid_shift", None
        try:
            day = date.fromisoformat(str(e.get("date")))
        except (TypeError, ValueError):
            return "invalid_date", None
        pid = _uid(e.get("personnel"))
        person = Personnel.objects.select_related("org_unit").filter(pk=pid).first() if pid else None
        if (person is None or not person.org_unit.path.startswith(unit.path)
                or not scope.can(request.user, "roster.manage", unit=person.org_unit)):
            return "person_unknown", None
        if person.status in NOT_SERVING:
            return "person_not_serving", None
        if e["shift"] != "off" and LeaveRequest.objects.filter(personnel=person, status="approved",
                                                              start_date__lte=day, end_date__gte=day).exists():
            return "on_leave", None
        return None, {"person": person, "day": day, "shift": e["shift"], "post": str(e.get("post") or "").strip()[:100]}
