"""Ammunition control endpoints: training events, warning flags, incident trace. Read access needs weapons.view in scope; creating
and closing events needs weapons.manage in scope. Reads are audited."""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.logistics.models import StockTransaction
from apps.organization.models import OrganizationalUnit

from . import control
from .models import AmmoEvent, SoldierRounds
from .views import _scoped, _uid


def _rows(user):
    """Soldier-round rows the caller may see: soldiers in the units covered by their weapons.view scope."""
    q = scope.unit_scope_q(user, "weapons.view", "personnel__org_unit__")
    return SoldierRounds.objects.none() if q is None else SoldierRounds.objects.filter(q)


def _events(user):
    q = scope.unit_scope_q(user, "weapons.view", "org_unit__")
    return AmmoEvent.objects.none() if q is None else AmmoEvent.objects.filter(q).select_related("org_unit")


class AmmoControlViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    pagination_class = None
    queryset = AmmoEvent.objects.none()
    permission_map = {
        "events": ("weapons.view", "any"), "event": ("weapons.view", "any"), "flags": ("weapons.view", "any"),
        "trace": ("weapons.view", "any"),
        "create_event": ("weapons.manage", "any"), "close_event": ("weapons.manage", "any"),
    }

    @action(detail=False, methods=["get"])
    def events(self, request):
        qs = _events(request.user)
        status = request.query_params.get("status")
        if status in ("open", "closed"):
            qs = qs.filter(status=status)
        uid = uuid_param(request, "org_unit")
        if uid:
            qs = qs.filter(org_unit_id=uid)
        return Response({"results": [control.event_out(e) for e in qs[:100]]})

    @action(detail=False, methods=["post"], url_path="create-event")
    def create_event(self, request):
        d = json_body(request)
        name = str(d.get("name") or "").strip()[:150]
        if not name:
            raise field_error("name", "required")
        try:
            day = parse_date(str(d.get("event_date") or ""))
        except ValueError:
            day = None
        if day is None:
            raise field_error("event_date", "invalid_date", "Use a date like 2026-03-01.")
        uid = _uid(d.get("org_unit")) if d.get("org_unit") else None
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if unit is None or not scope.can(request.user, "weapons.manage", unit=unit):
            raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
        event = AmmoEvent.objects.create(name=name, org_unit=unit, event_date=day, created_by_username=request.user.username)
        record("weapon.ammo_event_create", request=request, entity_type="ammo_event", entity_id=event.pk,
               metadata={"org_unit": str(unit.pk), "event_date": day.isoformat()})
        return Response(control.event_out(event), status=201)

    @action(detail=False, methods=["get"])
    def event(self, request):
        eid = uuid_param(request, "id")
        event = _events(request.user).filter(pk=eid).first() if eid else None
        if event is None:
            raise field_error("id", "out_of_scope", "That event was not found.")
        record_read(request, "weapon.read_ammo_event", entity_type="ammo_event", entity_id=event.pk, org_unit=event.org_unit)
        return Response(control.event_summary(event))

    @action(detail=False, methods=["post"], url_path="close-event")
    def close_event(self, request):
        eid = _uid(json_body(request).get("id"))
        event = _events(request.user).filter(pk=eid).first() if eid else None
        if event is None or not scope.can(request.user, "weapons.manage", unit=event.org_unit):
            raise field_error("id", "out_of_scope", "That event was not found.")
        closed = control.close_event(request, event)
        return Response(control.event_out(closed))

    @action(detail=False, methods=["get"])
    def flags(self, request):
        try:
            days = max(1, min(180, int(request.query_params.get("days", 30))))
        except ValueError:
            raise field_error("days", "invalid_number")
        record_read(request, "weapon.read_ammo_flags", entity_type="ammo_flags")
        return Response(control.flags(_rows(request.user), _events(request.user), days))

    @action(detail=False, methods=["get"])
    def trace(self, request):
        serial = (request.query_params.get("serial") or "").strip()[:64]
        lot = (request.query_params.get("lot") or "").strip()[:40]
        if not serial and not lot:
            raise field_error("serial", "serial_or_lot_required", "Give a weapon serial number or a lot number.")
        raw = request.query_params.get("at")
        at = parse_datetime(raw) if raw else timezone.now()
        if at is None:
            raise field_error("at", "invalid_datetime", "Use a date and time like 2026-03-01T14:30.")
        if timezone.is_naive(at):
            at = timezone.make_aware(at)
        record_read(request, "weapon.read_ammo_trace", entity_type="ammo_trace")
        tq = scope.unit_scope_q(request.user, "weapons.view", "stock_line__org_unit__")
        txns = StockTransaction.objects.none() if tq is None else StockTransaction.objects.filter(tq)
        return Response(control.trace(_rows(request.user), _scoped(request.user), serial, lot, at, txns))
