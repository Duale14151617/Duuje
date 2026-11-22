"""Custody facilities API: jail centers (army lock-ups, one or more per station) and prisons (outside the Army).

Read: detention.view. A jail center is shown to callers whose scope covers its station; prisons belong to no station and are shown to
everyone who can read the register. Write: detention.manage. A jail center needs that permission for its station; a prison, which sits
outside the unit tree, needs it at headquarters level (a global grant). Facilities are never deleted, only switched off."""
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import VersionConflict, require_version
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.organization.models import OrganizationalUnit
from apps.vehicles.views import _uid, _unit_brief

from . import capacity as cap
from .models import CustodyCell as C, CustodyFacility as F
from .views import _text

KINDS = {k for k, _ in F.Kind.choices}


def _out(f, st=None):
    held = getattr(f, "held_now", None)
    jail = f.kind == "jail_center"
    sm = cap.summarise(f, st or cap.stats_for([f.pk])[f.pk]) if jail else {}
    return {"id": str(f.pk), "code": f.code, "kind": f.kind, "name_en": f.name_en, "name_so": f.name_so, "org_unit": _unit_brief(f.org_unit),
            "location": f.location, "capacity": f.capacity, "operated_by": f.operated_by, "active": f.active, "version": f.version,
            "status": f.status, "status_note": f.status_note, "status_at": f.status_at, "status_by": f.status_by_username, "usable": f.usable,
            "needs_verification": f.status == F.Status.UNVERIFIED,
            "held_now": held if jail else None, "received_total": getattr(f, "received_total", None) if f.kind == "prison" else None,
            "capacity_effective": sm.get("capacity"), "cells": sm.get("cells"), "available": sm.get("available"), "over_capacity": sm.get("over_capacity")}


def _cell_out(c, held=0):
    return {"id": str(c.pk), "facility": str(c.facility_id), "code": c.code, "name": c.name, "capacity": c.capacity, "note": c.note,
            "active": c.active, "reserved_for": c.reserved_for, "occupied": held, "available": max(c.capacity - held, 0), "version": c.version}


def _reserved(d):
    v = d.get("reserved_for") or "any"
    if v not in {k for k, _ in C.ReservedFor.choices}:
        raise field_error("reserved_for", "invalid_choice", "Choose anyone, women only, juveniles only or adult men only.")
    return v


def _cell_capacity(d):
    try:
        n = int(str(d.get("capacity")).strip())
    except (TypeError, ValueError):
        raise field_error("capacity", "invalid_number", "Enter a whole number.")
    if not 1 <= n <= 1000:
        raise field_error("capacity", "invalid_number", "Enter a number between 1 and 1000.")
    return n


def _capacity(d):
    if d.get("capacity") in (None, ""):
        return None
    try:
        n = int(str(d["capacity"]).strip())
    except (TypeError, ValueError):
        raise field_error("capacity", "invalid_number", "Enter a whole number.")
    if not 0 <= n <= 100000:
        raise field_error("capacity", "invalid_number", "Enter a number between 0 and 100000.")
    return n


class CustodyFacilityViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9a-f\-]{36}"
    permission_map = {"list": ("detention.view", "any"), "create": ("detention.manage", "any"), "edit": ("detention.manage", "any"),
                      "cells": ("detention.view", "any"), "add_cell": ("detention.manage", "any"), "edit_cell": ("detention.manage", "any"),
                      "set_status": ("detention.verify", "any")}

    def _scoped(self):
        q = scope.unit_scope_q(self.request.user, "detention.view", "org_unit__")
        if q is None:
            return F.objects.none()
        return F.objects.filter(q | Q(kind="prison")).select_related("org_unit")

    def _may_write(self, kind, unit):
        return scope.can(self.request.user, "detention.manage") if kind == "prison" else (unit is not None and scope.can(self.request.user, "detention.manage", unit=unit))

    def list(self, request):
        p = request.query_params
        qs = self._scoped().annotate(held_now=Count("records", filter=Q(records__status="in_custody"), distinct=True),
                                     received_total=Count("received", distinct=True))
        if p.get("kind") in KINDS:
            qs = qs.filter(kind=p["kind"])
        if p.get("active") in ("0", "1"):
            qs = qs.filter(active=p["active"] == "1")
        if _uid(p.get("unit")):
            qs = qs.filter(org_unit_id=_uid(p["unit"]))
        if p.get("status") in {c for c, _ in F.Status.choices}:
            qs = qs.filter(status=p["status"])
        rows = list(qs.order_by("kind", "name_en"))
        stats = cap.stats_for([f.pk for f in rows])
        return Response({"results": [_out(f, stats[f.pk]) for f in rows]})

    def create(self, request):
        d = json_body(request)
        kind = d.get("kind")
        if kind not in KINDS:
            raise field_error("kind", "invalid_choice", "Choose jail center or prison.")
        unit = None
        if kind == "jail_center":
            unit = OrganizationalUnit.objects.filter(pk=_uid(d.get("org_unit"))).first() if _uid(d.get("org_unit")) else None
            if unit is None:
                raise field_error("org_unit", "required", "Choose the station this jail center belongs to.")
        if not self._may_write(kind, unit):
            raise Http404
        code = _text(d, "code", 64, required=True).upper().replace(" ", "-")
        if F.objects.filter(code=code).exists():
            raise field_error("code", "duplicate", "This code is already used.")
        try:
            with transaction.atomic():
                f = F.objects.create(code=code, kind=kind, org_unit=unit, name_en=_text(d, "name_en", 150, required=True), name_so=_text(d, "name_so", 150),
                                     location=_text(d, "location", 200), capacity=_capacity(d),
                                     operated_by=_text(d, "operated_by", 150) or ("Army" if kind == "jail_center" else ""),
                                     last_edited_by_username=request.user.username)
        except IntegrityError:
            raise field_error("code", "duplicate", "This code is already used.")
        record("detention.facility_create", request=request, entity_type="custody_facility", entity_id=f.pk, metadata={"code": f.code, "kind": f.kind})
        return Response(_out(f), status=201)

    @action(detail=True, methods=["post"])
    def edit(self, request, pk=None):
        d = json_body(request)
        row = self._scoped().filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None or not self._may_write(row.kind, row.org_unit):
            raise Http404
        with transaction.atomic():
            f = F.objects.select_for_update().get(pk=row.pk)
            if f.version != require_version(d):
                raise VersionConflict()
            changed = []
            for name, limit in (("name_en", 150), ("name_so", 150), ("location", 200), ("operated_by", 150)):
                if name in d:
                    new = _text(d, name, limit, required=name == "name_en")
                    if new != getattr(f, name):
                        setattr(f, name, new)
                        changed.append(name)
            if "capacity" in d and _capacity(d) != f.capacity:
                f.capacity = _capacity(d)
                changed.append("capacity")
            if "active" in d and bool(d["active"]) != f.active:
                if not d["active"] and f.records.filter(status="in_custody").exists():
                    raise field_error("active", "in_use", "People are still held here. Move or release them first.")
                f.active = bool(d["active"])
                changed.append("active")
            if changed:
                f.version += 1
                f.last_edited_by_username = request.user.username
                f.save()
                record("detention.facility_edit", request=request, entity_type="custody_facility", entity_id=f.pk, metadata={"code": f.code, "fields": changed})
        return Response(_out(F.objects.select_related("org_unit").annotate(held_now=Count("records", filter=Q(records__status="in_custody"), distinct=True),
                                                                         received_total=Count("received", distinct=True)).get(pk=f.pk)))

    def _facility(self, pk):
        row = self._scoped().filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None:
            raise Http404
        return row

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        """Verify a facility as operational, or record that it is out of use or closed. Needs detention.verify for the station (a prison:
        a global grant). A note saying what was checked is required, and the change is audited."""
        d = json_body(request)
        row = self._facility(pk)
        allowed = scope.can(request.user, "detention.verify") if row.kind == "prison" else scope.can(request.user, "detention.verify", unit=row.org_unit)
        if not allowed:
            raise Http404
        new = d.get("status")
        if new not in {c for c, _ in F.Status.choices} or new == F.Status.UNVERIFIED:
            raise field_error("status", "invalid_choice", "Choose operational, temporarily out of use or closed.")
        note = _text(d, "note", 300, required=True)
        with transaction.atomic():
            f = F.objects.select_for_update().get(pk=row.pk)
            if f.version != require_version(d):
                raise VersionConflict()
            if new == F.Status.OPERATIONAL and not f.active:
                raise field_error("status", "inactive", "Switch the facility on before marking it operational.")
            if new != F.Status.OPERATIONAL and f.records.filter(status="in_custody").exists():
                raise field_error("status", "in_use", "People are still held here. Move or release them first.")
            if f.last_edited_by_username == request.user.username and not scope.self_approval_allowed(request.user, "facility_verification", request, "custody_facility", f.pk):
                raise field_error("status", "own_entry", "A different authorised person must verify a facility you created or last changed.")
            old = f.status
            f.status, f.status_note, f.status_at, f.status_by_username = new, note, timezone.now(), request.user.username
            f.version += 1
            f.save()
            record("detention.facility_status", request=request, entity_type="custody_facility", entity_id=f.pk, metadata={"code": f.code, "from": old, "to": new})
        return Response(_out(F.objects.select_related("org_unit").annotate(held_now=Count("records", filter=Q(records__status="in_custody"), distinct=True),
                                                                         received_total=Count("received", distinct=True)).get(pk=f.pk)))

    @action(detail=True, methods=["get"])
    def cells(self, request, pk=None):
        f = self._facility(pk)
        rows = list(f.cells.order_by("code"))
        held = cap.cell_occupancy([c.pk for c in rows])
        return Response({"results": [_cell_out(c, held.get(c.pk, 0)) for c in rows]})

    @action(detail=True, methods=["post"])
    def add_cell(self, request, pk=None):
        d = json_body(request)
        f = self._facility(pk)
        if f.kind != "jail_center" or not self._may_write(f.kind, f.org_unit):
            raise Http404
        code = _text(d, "code", 30, required=True).upper().replace(" ", "-")
        if f.cells.filter(code=code).exists():
            raise field_error("code", "duplicate", "This cell code is already used in this jail center.")
        try:
            with transaction.atomic():
                c = C.objects.create(facility=f, code=code, name=_text(d, "name", 100), note=_text(d, "note", 200), capacity=_cell_capacity(d), reserved_for=_reserved(d))
        except IntegrityError:
            raise field_error("code", "duplicate", "This cell code is already used in this jail center.")
        record("detention.cell_create", request=request, entity_type="custody_cell", entity_id=c.pk, metadata={"facility": f.code, "code": c.code, "capacity": c.capacity})
        return Response(_cell_out(c), status=201)

    @action(detail=True, methods=["post"])
    def edit_cell(self, request, pk=None):
        """Change a cell of this facility (body: cell, version, then name / note / capacity / active)."""
        d = json_body(request)
        f = self._facility(pk)
        if f.kind != "jail_center" or not self._may_write(f.kind, f.org_unit):
            raise Http404
        with transaction.atomic():
            c = C.objects.select_for_update().filter(pk=_uid(d.get("cell")), facility=f).first() if _uid(d.get("cell")) else None
            if c is None:
                raise field_error("cell", "unknown", "Choose a cell of this jail center.")
            if c.version != require_version(d):
                raise VersionConflict()
            held = c.records.filter(status="in_custody").count()
            changed = []
            for name, limit in (("name", 100), ("note", 200)):
                if name in d and _text(d, name, limit) != getattr(c, name):
                    setattr(c, name, _text(d, name, limit))
                    changed.append(name)
            if "reserved_for" in d and _reserved(d) != c.reserved_for:
                c.reserved_for = _reserved(d)
                changed.append("reserved_for")
            if "capacity" in d and _cell_capacity(d) != c.capacity:
                if _cell_capacity(d) < held:
                    raise field_error("capacity", "below_occupancy", f"{held} people are in this cell now.")
                c.capacity = _cell_capacity(d)
                changed.append("capacity")
            if "active" in d and bool(d["active"]) != c.active:
                if not d["active"] and held:
                    raise field_error("active", "in_use", "People are in this cell. Move them first.")
                c.active = bool(d["active"])
                changed.append("active")
            if changed:
                c.version += 1
                c.save()
                record("detention.cell_edit", request=request, entity_type="custody_cell", entity_id=c.pk, metadata={"facility": f.code, "code": c.code, "fields": changed})
        return Response(_cell_out(c, held))
