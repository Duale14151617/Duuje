import uuid

from django.db.models import Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core import crypto
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from . import services as svc
from .models import MaintenanceRecord, Vehicle, VehicleCategory, VehicleDocument, VehicleEvent, VehicleStatusType


def _uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _unit_brief(u):
    return None if u is None else {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}


def _person_brief(p):
    return None if p is None else {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                                   "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}}


def _cat(c):
    return {"id": str(c.pk), "code": c.code, "name_en": c.name_en, "name_so": c.name_so, "active": c.active, "sort_order": c.sort_order}


def _status_type(x):
    return {"id": str(x.pk), "code": x.code, "name_en": x.name_en, "name_so": x.name_so, "available": x.available, "is_system": x.is_system, "active": x.active}


def _out(v, today=None):
    due = getattr(v, "next_due", None)
    today = today or timezone.localdate()
    return {"id": str(v.pk), "vehicle_id": v.vehicle_id, "plate": v.plate, "plate_status": v.plate_status, "category": _cat(v.category),
            "vehicle_type": v.vehicle_type, "make": v.make, "model": v.model, "year": v.year, "org_unit": _unit_brief(v.org_unit),
            "driver": _person_brief(v.driver), "custodian": _person_brief(v.custodian), "location": v.location, "status": v.status,
            "condition": v.condition, "next_due_date": due, "maintenance_overdue": bool(due and due < today and v.status != "decommissioned"),
            "disposal_pending": bool(v.disposal_requested_at), "version": v.version}


def _event_out(e):
    return {"id": str(e.pk), "kind": e.kind, "before": e.before, "after": e.after, "reason": e.reason, "authority_ref": e.authority_ref,
            "effective_date": e.effective_date, "actor": e.actor_username, "at": e.created_at}


def _maint_out(m, show_cost):
    d = {"id": str(m.pk), "kind": m.kind, "state": m.state, "performed_on": m.performed_on, "reported_issue": m.reported_issue,
         "work_performed": m.work_performed, "workshop": m.workshop, "next_due_date": m.next_due_date, "reference": m.reference,
         "recorded_by": m.created_by_username, "version": m.version}
    if show_cost:
        d["cost"] = None if m.cost is None else str(m.cost)
        d["currency"] = m.currency
    return d


def _doc_out(d):
    return {"id": str(d.pk), "category": d.category, "title": d.title, "content_type": d.content_type, "size_bytes": d.size_bytes,
            "uploaded_at": d.uploaded_at, "uploaded_by": d.uploaded_by_username, "maintenance": str(d.maintenance_id) if d.maintenance_id else None}


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


class VehicleViewSet(viewsets.GenericViewSet):
    """Military vehicle registry. Every route is permission-checked server-side and narrowed to the caller's organizational scope,
    so guessing a Vehicle ID or editing a URL reveals nothing outside it (an out-of-scope record answers 404)."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser, MultiPartParser]
    lookup_value_regex = r"[0-9A-Za-z\-]+"
    permission_map = {
        "list": ("vehicles.view", "any"), "retrieve": ("vehicles.view", "unit"), "summary": ("vehicles.view", "any"),
        "categories": (("vehicles.view", "vehicles.configure"), "any"), "category_update": ("vehicles.configure", "global"), "statuses": (("vehicles.view", "vehicles.configure"), "any"), "status_update": ("vehicles.configure", "global"), "people": (("vehicles.create", "vehicles.edit"), "any"),
        "create": ("vehicles.create", "any"), "edit": ("vehicles.edit", "unit"), "transfer": ("vehicles.transfer", "unit"),
        "driver": ("vehicles.edit", "unit"), "custodian": ("vehicles.edit", "unit"), "location": ("vehicles.edit", "unit"),
        "status": ("vehicles.edit", "unit"), "history": ("vehicles.view", "unit"), "maintenance": ("vehicles.view", "unit"),
        "maintenance_add": ("vehicles.edit", "unit"), "maintenance_complete": ("vehicles.edit", "unit"),
        "documents": ("vehicles.view", "unit"), "document_upload": ("vehicles.edit", "unit"), "document_download": ("vehicles.view", "unit"),
        "document_withdraw": ("vehicles.edit", "unit"), "propose_disposal": ("vehicles.dispose", "unit"),
        "approve_disposal": ("vehicles.approve", "unit"), "reject_disposal": ("vehicles.approve", "unit"),
    }

    def scope_unit(self, obj):
        return svc.effective_unit(obj)

    # --- querysets --------------------------------------------------------------------------------------------------------
    def get_queryset(self):
        q = scope.unit_scope_q(self.request.user, "vehicles.view", "org_unit__")
        if q is None:
            return Vehicle.objects.none()
        return svc.with_due(Vehicle.objects.filter(q)).select_related("category", "org_unit", "driver__rank", "custodian__rank")

    def get_object(self):
        key = self.kwargs["pk"]
        qs = self.get_queryset()
        obj = qs.filter(vehicle_id=key.upper()).first() if key.upper().startswith("VEH-") else (qs.filter(pk=_uid(key)).first() if _uid(key) else None)
        if obj is None:
            raise Http404
        self.check_object_permissions(self.request, obj)
        return obj

    def _can(self, code, unit):
        return scope.can(self.request.user, code, unit=unit)

    def _reach(self, code):
        return lambda unit: scope.can(self.request.user, code, unit=unit)

    def _fresh(self, v):
        return _out(self.get_queryset().get(pk=v.pk))

    def _unit_in_scope(self, value, code, field="org_unit"):
        unit = OrganizationalUnit.objects.filter(pk=_uid(value)).first() if _uid(value) else None
        if unit is None or not scope.can(self.request.user, code, unit=unit):
            raise field_error(field, "out_of_scope", "That unit is outside your scope.")  # an unreachable unit reads like an unknown one
        return unit

    # --- read -------------------------------------------------------------------------------------------------------------
    def list(self, request):
        qs, p = self.get_queryset(), request.query_params
        if p.get("q"):
            q = p["q"].strip()[:60]
            key = svc.plate_key(q) or q
            qs = qs.filter(Q(vehicle_id__icontains=q) | Q(plate_key__icontains=key) | Q(make__icontains=q) | Q(model__icontains=q)
                           | Q(driver__service_number__iexact=q) | Q(driver__full_name__icontains=q))
        if p.get("vehicle_id"):
            qs = qs.filter(vehicle_id__iexact=p["vehicle_id"].strip()[:20])
        if p.get("plate"):
            qs = qs.filter(plate_key=svc.plate_key(p["plate"][:32]) or "\0")
        if p.get("category"):
            qs = qs.filter(Q(category__code=p["category"]) | Q(category_id=_uid(p["category"])))
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("service_number"):
            qs = qs.filter(Q(driver__service_number=p["service_number"]) | Q(custodian__service_number=p["service_number"]))
        unit = uuid_param(request, "org_unit")
        base = None
        if unit:
            base = OrganizationalUnit.objects.filter(pk=unit).first()
            if base is None:
                qs = qs.none()
            elif p.get("direct") == "1":
                qs = qs.filter(org_unit=base)
            else:
                qs = qs.filter(org_unit__path__startswith=base.path)
        if p.get("include_decommissioned") != "1" and p.get("status") != "decommissioned":
            qs = qs.exclude(status="decommissioned")
        if p.get("overdue") == "1":
            qs = qs.filter(svc.overdue_q())
        if p.get("no_driver") == "1":
            qs = qs.filter(driver__isnull=True)
        if p.get("no_custodian") == "1":
            qs = qs.filter(custodian__isnull=True)
        page = self.paginate_queryset(qs.order_by("vehicle_id"))
        record_read(request, "vehicle.read_list", entity_type="vehicle_register", org_unit=base, count=len(page))
        return self.get_paginated_response([_out(v) for v in page])

    def retrieve(self, request, pk=None):
        v = self.get_object()
        record_read(request, "vehicle.read_detail", entity_type="vehicle", entity_id=v.pk, org_unit=v.org_unit)
        d = _out(v)
        d.update({"acquired_on": v.acquired_on, "acquisition_ref": v.acquisition_ref, "notes": v.notes,
                  "disposal": {"requested_at": v.disposal_requested_at, "requested_by": v.disposal_requested_by,
                               "reason": v.disposal_reason, "authority_ref": v.disposal_authority_ref} if v.disposal_requested_at else None,
                  "decommissioned_at": v.decommissioned_at, "created_at": v.created_at, "updated_at": v.updated_at,
                  "capabilities": {c: self._can(f"vehicles.{c}", v.org_unit) for c in ("edit", "transfer", "dispose", "approve", "cost")},
                  "assignment_history": [_event_out(e) for e in v.events.filter(kind__in=["registered", "unit_transfer", "driver_change", "custodian_change"])[:100]]})
        return Response(d)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        v = self.get_object()
        record_read(request, "vehicle.read_history", entity_type="vehicle", entity_id=v.pk, org_unit=v.org_unit)
        kind = request.query_params.get("kind")
        evs = v.events.filter(kind=kind) if kind else v.events.all()
        return Response({"results": [_event_out(e) for e in evs[:500]]})

    @action(detail=True, methods=["get"])
    def maintenance(self, request, pk=None):
        v = self.get_object()
        record_read(request, "vehicle.read_maintenance", entity_type="vehicle", entity_id=v.pk, org_unit=v.org_unit)
        show = self._can("vehicles.cost", v.org_unit)
        return Response({"results": [_maint_out(m, show) for m in v.maintenance.all()[:300]], "cost_visible": show})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Fleet totals for a unit and, separately, its subordinate units. Derived from vehicle rows on every request."""
        unit = uuid_param(request, "org_unit")
        base = OrganizationalUnit.objects.filter(pk=unit).first() if unit else None
        if base is None:
            raise field_error("org_unit", "required", "Choose a unit.")
        allowed = scope.scoped_units(request.user, "vehicles.view")
        # The unit must lie inside, or be an ancestor of, a unit the caller may see; the figures themselves are computed only from
        # vehicles inside the caller's scope.
        if not any(base.path.startswith(u.path) or u.path.startswith(base.path) for u in allowed.only("path")):
            raise Http404
        record_read(request, "vehicle.read_summary", entity_type="vehicle_summary", org_unit=base)
        return Response(svc.fleet_summary(self.get_queryset(), base))

    @action(detail=False, methods=["get", "post"])
    def categories(self, request):
        if request.method == "POST":
            if not scope.can(request.user, "vehicles.configure"):
                record("access.denied", request=request, outcome="denied", entity_type="VehicleViewSet", metadata={"permission": "vehicles.configure"})
                raise Http404
            d = json_body(request)
            code = str(d.get("code") or "").strip().lower()
            name = str(d.get("name_en") or "").strip()
            if not code or len(code) > 40 or not code.replace("_", "").isalnum():
                raise field_error("code", "invalid_code", "Use letters, digits and underscores.")
            if not name:
                raise field_error("name_en", "required", "Give the category a name.")
            if VehicleCategory.objects.filter(code=code).exists():
                raise field_error("code", "code_in_use", "That code is already used.")
            c = VehicleCategory.objects.create(code=code, name_en=name[:120], name_so=str(d.get("name_so") or "")[:120])
            record("vehicle.category_create", request=request, entity_type="vehicle_category", entity_id=c.pk, metadata={"code": code})
            return Response(_cat(c), status=201)
        if not scope.has_anywhere(request.user, "vehicles.view"):
            raise Http404
        return Response({"results": [_cat(c) for c in VehicleCategory.objects.filter(active=True)]})

    @action(detail=False, methods=["patch"], url_path=r"categories/(?P<cid>[0-9a-f\-]{36})")
    def category_update(self, request, cid=None):
        c = VehicleCategory.objects.filter(pk=cid).first()
        if c is None:
            raise Http404
        d = json_body(request)
        for f, n in (("name_en", 120), ("name_so", 120)):
            if f in d:
                setattr(c, f, str(d[f] or "").strip()[:n])
        if "active" in d:
            if d["active"] is False and c.vehicles.exclude(status="decommissioned").exists():
                raise field_error("active", "category_in_use", "Vehicles still use this category.")
            c.active = bool(d["active"])
        if "sort_order" in d and isinstance(d["sort_order"], int):
            c.sort_order = max(0, min(10000, d["sort_order"]))
        c.save()
        record("vehicle.category_update", request=request, entity_type="vehicle_category", entity_id=c.pk, metadata={"code": c.code})
        return Response(_cat(c))

    @action(detail=False, methods=["get", "post"])
    def statuses(self, request):
        """Operational statuses. HQ may add statuses and say whether a vehicle in them is available; the six system ones are fixed."""
        if request.method == "POST":
            if not scope.can(request.user, "vehicles.configure"):
                record("access.denied", request=request, outcome="denied", entity_type="VehicleViewSet", metadata={"permission": "vehicles.configure"})
                raise Http404
            d = json_body(request)
            code = str(d.get("code") or "").strip().lower()
            name = str(d.get("name_en") or "").strip()
            if not code or len(code) > 30 or not code.replace("_", "").isalnum():
                raise field_error("code", "invalid_code", "Use letters, digits and underscores.")
            if not name:
                raise field_error("name_en", "required", "Give the status a name.")
            if VehicleStatusType.objects.filter(code=code).exists():
                raise field_error("code", "code_in_use", "That code is already used.")
            st = VehicleStatusType.objects.create(code=code, name_en=name[:120], name_so=str(d.get("name_so") or "")[:120],
                                                  available=bool(d.get("available", False)))
            record("vehicle.status_type_create", request=request, entity_type="vehicle_status_type", entity_id=st.pk, metadata={"code": code})
            return Response(_status_type(st), status=201)
        if not scope.has_anywhere(request.user, "vehicles.view"):
            raise Http404
        return Response({"results": [_status_type(x) for x in VehicleStatusType.objects.filter(active=True)]})

    @action(detail=False, methods=["patch"], url_path=r"statuses/(?P<sid>[0-9a-f\-]{36})")
    def status_update(self, request, sid=None):
        st = VehicleStatusType.objects.filter(pk=sid).first()
        if st is None:
            raise Http404
        d = json_body(request)
        for f in ("name_en", "name_so"):
            if f in d:
                setattr(st, f, str(d[f] or "").strip()[:120])
        if st.is_system:
            if "active" in d or "available" in d:
                raise field_error("status", "system_status", "The built-in statuses cannot be switched off or changed in meaning.")
        else:
            if "available" in d:
                st.available = bool(d["available"])
            if "active" in d:
                if d["active"] is False and Vehicle.objects.filter(status=st.code).exists():
                    raise field_error("active", "status_in_use", "Vehicles are still in this status.")
                st.active = bool(d["active"])
        st.save()
        record("vehicle.status_type_update", request=request, entity_type="vehicle_status_type", entity_id=st.pk, metadata={"code": st.code})
        return Response(_status_type(st))

    @action(detail=False, methods=["get"])
    def people(self, request):
        """Minimal lookup of serving personnel to name as driver or custodian. Opens no personnel record."""
        qs = None
        for code in ("vehicles.create", "vehicles.edit"):
            q = scope.unit_scope_q(request.user, code, "org_unit__")
            if q is not None:
                qs = q if qs is None else (qs | q)
        s = (request.query_params.get("q") or "").strip()[:60]
        if qs is None or len(s) < 2:
            return Response({"results": []})
        rows = (Personnel.objects.filter(qs).exclude(status__in=NOT_SERVING).filter(Q(full_name__icontains=s) | Q(service_number__icontains=s))
                .select_related("rank", "org_unit").order_by("full_name")[:20])
        return Response({"results": [{**_person_brief(p), "org_unit": _unit_brief(p.org_unit)} for p in rows]})

    # --- write ------------------------------------------------------------------------------------------------------------
    def create(self, request):
        d = json_body(request)
        unit = self._unit_in_scope(d.get("org_unit"), "vehicles.create")
        v = svc.register(request, d, unit, self._reach("vehicles.create"))
        return Response(self._fresh(v), status=201)

    @action(detail=True, methods=["post"])
    def edit(self, request, pk=None):
        d = json_body(request)
        v = svc.edit_details(request, self.get_object(), d, require_version(d))
        return Response(self._fresh(v))

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        d = json_body(request)
        obj = self.get_object()
        to = self._unit_in_scope(d.get("org_unit"), "vehicles.transfer")
        v = svc.transfer(request, obj, to, d, require_version(d))
        return Response(self._fresh(v) if self.get_queryset().filter(pk=v.pk).exists() else {"id": str(v.pk), "transferred": True})

    @action(detail=True, methods=["post"])
    def driver(self, request, pk=None):
        d = json_body(request)
        obj = self.get_object()
        v = svc.assign_driver(request, obj, d, require_version(d), self._reach("vehicles.edit"))
        return Response(self._fresh(v))

    @action(detail=True, methods=["post"])
    def custodian(self, request, pk=None):
        d = json_body(request)
        obj = self.get_object()
        v = svc.assign_custodian(request, obj, d, require_version(d), self._reach("vehicles.edit"))
        return Response(self._fresh(v))

    @action(detail=True, methods=["post"])
    def location(self, request, pk=None):
        d = json_body(request)
        v = svc.set_location(request, self.get_object(), d, require_version(d))
        return Response(self._fresh(v))

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        d = json_body(request)
        v = svc.change_status(request, self.get_object(), d, require_version(d))
        return Response(self._fresh(v))

    @action(detail=True, methods=["post"], url_path="maintenance/add")
    def maintenance_add(self, request, pk=None):
        d = json_body(request)
        obj = self.get_object()
        v, m = svc.add_maintenance(request, obj, d, require_version(d), self._can("vehicles.cost", obj.org_unit))
        return Response({"vehicle": self._fresh(v), "record": _maint_out(m, self._can("vehicles.cost", obj.org_unit))}, status=201)

    @action(detail=True, methods=["post"], url_path=r"maintenance/(?P<mid>[0-9a-f\-]{36})/complete")
    def maintenance_complete(self, request, pk=None, mid=None):
        d = json_body(request)
        obj = self.get_object()
        m = MaintenanceRecord.objects.filter(pk=mid, vehicle=obj).first()
        if m is None:
            raise Http404
        v, m = svc.complete_maintenance(request, m, d, require_version(d), self._can("vehicles.cost", obj.org_unit))
        return Response({"vehicle": self._fresh(v), "record": _maint_out(m, self._can("vehicles.cost", obj.org_unit))})

    @action(detail=True, methods=["post"], url_path="disposal/propose")
    def propose_disposal(self, request, pk=None):
        d = json_body(request)
        v = svc.propose_disposal(request, self.get_object(), d, require_version(d))
        return Response(self._fresh(v))

    @action(detail=True, methods=["post"], url_path="disposal/approve")
    def approve_disposal(self, request, pk=None):
        d = json_body(request)
        obj = self.get_object()
        v = svc.decide_disposal(request, obj, d, require_version(d), True)
        return Response(self._fresh(v))

    @action(detail=True, methods=["post"], url_path="disposal/reject")
    def reject_disposal(self, request, pk=None):
        d = json_body(request)
        v = svc.decide_disposal(request, self.get_object(), d, require_version(d), False)
        return Response(self._fresh(v))

    # --- documents --------------------------------------------------------------------------------------------------------
    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        v = self.get_object()
        record_read(request, "vehicle.read_documents", entity_type="vehicle", entity_id=v.pk, org_unit=v.org_unit)
        return Response({"results": [_doc_out(d) for d in v.documents.filter(withdrawn_at__isnull=True)]})

    @action(detail=True, methods=["post"], url_path="documents/upload")
    def document_upload(self, request, pk=None):
        v = self.get_object()
        mid = request.data.get("maintenance") or None
        m = MaintenanceRecord.objects.filter(pk=_uid(mid), vehicle=v).first() if mid else None
        if mid and m is None:
            raise field_error("maintenance", "unknown", "Unknown maintenance record.")
        doc = svc.add_document(request, v, request.data.get("category") or "", request.data.get("title") or "", request.FILES.get("file"), m)
        return Response(_doc_out(doc), status=201)

    @action(detail=True, methods=["get"], url_path=r"documents/(?P<did>[0-9a-f\-]{36})/download")
    def document_download(self, request, pk=None, did=None):
        v = self.get_object()
        doc = VehicleDocument.objects.filter(pk=did, vehicle=v, withdrawn_at__isnull=True).first()
        if doc is None:
            raise Http404
        record_read(request, "vehicle.document_download", entity_type="vehicle_document", entity_id=doc.pk, org_unit=v.org_unit)
        resp = HttpResponse(crypto.decrypt_bytes(bytes(doc.content_enc)), content_type=doc.content_type)
        resp["Content-Disposition"] = 'attachment; filename="vehicle-document"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store"
        return resp

    @action(detail=True, methods=["post"], url_path=r"documents/(?P<did>[0-9a-f\-]{36})/withdraw")
    def document_withdraw(self, request, pk=None, did=None):
        v = self.get_object()
        doc = VehicleDocument.objects.filter(pk=did, vehicle=v).first()
        if doc is None:
            raise Http404
        svc.withdraw_document(request, doc, json_body(request).get("reason"))
        return Response({"ok": True})
