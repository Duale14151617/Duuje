from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, viewsets

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.params import uuid_param

from rest_framework.decorators import action
from rest_framework.response import Response

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.core.concurrency import require_version, versioned_update
from apps.core.errors import field_error

from . import change_requests, structure, structure_changes
from .models import ChangeRequest, DesignationRule, ServiceBranch, SpecialistDesignation, StructureChange, UnitType
from .serializers import (BranchSerializer, DesignationSerializer, RuleSerializer, StructureChangeSerializer,
                          UnitSerializer, UnitTypeSerializer)


class UnitViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = UnitSerializer
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": ("org.view", "unit"), "retrieve": ("org.view", "unit"),
        "create": ("org.manage", "any"), "partial_update": ("org.manage", "unit"),
        "tree": ("org.view", "any"), "overview": ("org.view", "unit"),
    }

    def scope_unit(self, obj):
        return obj

    def get_queryset(self):
        # Scope is applied to the queryset itself, so lists, searches and direct
        # lookups of out-of-scope units behave as if they did not exist (404).
        qs = scope.scoped_units(self.request.user, "org.view")
        p = self.request.query_params
        if p.get("level"):
            qs = qs.filter(level=p["level"])
        for field in ("parent", "branch"):
            value = uuid_param(self.request, field)
            if value:
                qs = qs.filter(**{field: value})
        if p.get("active") in ("true", "false"):
            qs = qs.filter(active=p["active"] == "true")
        if p.get("q"):
            qs = qs.filter(Q(code__icontains=p["q"]) | Q(name_en__icontains=p["q"]) | Q(name_so__icontains=p["q"]))
        for param, field in (("unit_type", "unit_type"), ("designation", "designations")):
            value = uuid_param(self.request, param)
            if value:
                qs = qs.filter(**{field: value})
        if p.get("placeable") == "1":  # units people can be assigned to
            qs = qs.filter(level__in=["branch_command", "unit", "station"])
        return qs.select_related("parent", "branch").prefetch_related("designations")

    TREE_LIMIT = 2000

    @action(detail=True, methods=["get"])
    def overview(self, request, pk=None):
        """Read-only picture of one unit (Guuto, Urur, section...): strength counted once, sub-unit totals, commanders.

        Every person has exactly one unit, so `total` = `direct` + the sum of the sub-units' totals: nobody is counted twice.
        Only people the caller may count are included (personnel.view or changes.propose, with the Police/CID gates applied).
        Aggregates only; names appear only for callers who may see personnel (or HQ administrators preparing a request)."""
        from collections import Counter

        from apps.personnel.models import CommandAppointment, Personnel
        from apps.personnel.services import NOT_SERVING

        unit = self.get_object()
        q = None
        for code in ("personnel.view", "changes.propose"):
            part = scope.unit_scope_q(request.user, code, "org_unit__")
            if part is not None:
                q = part if q is None else (q | part)
        base = Personnel.objects.filter(q).exclude(status__in=NOT_SERVING) if q is not None else Personnel.objects.none()
        below = base.filter(org_unit__path__startswith=unit.path)
        by_unit = Counter(below.values_list("org_unit__path", flat=True))
        by_status = dict(Counter(below.values_list("status", flat=True)))
        kids = list(scope.scoped_units(request.user, "org.view").filter(parent=unit, active=True)
                    .select_related("unit_type").order_by("code"))
        children = [{"id": str(k.pk), "code": k.code, "name_en": k.name_en, "name_so": k.name_so, "level": k.level,
                     "unit_type": k.unit_type.code if k.unit_type_id else None,
                     "direct": by_unit.get(k.path, 0),
                     "total": sum(n for p, n in by_unit.items() if p.startswith(k.path))} for k in kids]
        names_ok = scope.can(request.user, "personnel.view", unit=unit) or scope.can(request.user, "changes.propose", unit=unit)
        appts = CommandAppointment.objects.filter(ended_at__isnull=True, org_unit__in=[unit] + kids).select_related(
            "appointment_type", "org_unit", "personnel__rank")
        commanders = [{"appointment": str(a.pk), "type": a.appointment_type.code, "type_en": a.appointment_type.name_en,
                       "type_so": a.appointment_type.name_so, "unit_id": str(a.org_unit_id), "unit_code": a.org_unit.code,
                       "holder": ({"id": str(a.personnel_id), "full_name": a.personnel.full_name,
                                   "rank": a.personnel.rank.name_en, "service_number": a.personnel.service_number}
                                  if names_ok else None)} for a in appts]
        members = []
        if names_ok:  # the section's own personnel: name, rank, service number (the unit's strength is counted from the same rows)
            members = [{"id": str(m.pk), "full_name": m.full_name, "rank": m.rank.name_en, "service_number": m.service_number,
                        "status": m.status} for m in base.filter(org_unit=unit).select_related("rank").order_by("full_name")[:300]]
        chain = [{"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}
                 for u in scope.scoped_units(request.user, "org.view").filter(path__in=self._ancestors(unit)).order_by("path")]
        direct = by_unit.get(unit.path, 0)
        total = sum(by_unit.values())
        record_read(request, "org_unit.overview_view", entity_type="organizational_unit", entity_id=unit.pk, org_unit=unit, count=total)
        return Response({
            "unit": {"id": str(unit.pk), "code": unit.code, "name_en": unit.name_en, "name_so": unit.name_so, "level": unit.level,
                     "unit_type": unit.unit_type.code if unit.unit_type_id else None},
            "breadcrumb": chain, "strength": {"direct": direct, "total": total, "by_status": by_status},
            "children": children, "commanders": commanders, "members": members, "counts_complete": q is not None})

    @staticmethod
    def _ancestors(unit):
        parts = [p for p in unit.path.split("/") if p]
        return ["/" + "/".join(parts[:i]) + "/" for i in range(1, len(parts))] if unit.path.startswith("/") else \
            ["/".join(parts[:i]) + "/" for i in range(1, len(parts))]

    @action(detail=False, methods=["get"])
    def tree(self, request):
        """Nested view of the units in the caller's scope (2.0). A unit whose parent is outside the scope becomes a root."""
        qs = scope.scoped_units(request.user, "org.view")
        if request.query_params.get("include_inactive") != "1":
            qs = qs.filter(active=True)
        rows = list(qs.select_related("unit_type").order_by("path")[: self.TREE_LIMIT + 1])
        truncated = len(rows) > self.TREE_LIMIT
        rows = rows[: self.TREE_LIMIT]
        nodes = {u.pk: {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so, "level": u.level,
                        "unit_type": u.unit_type.code if u.unit_type_id else None, "active": u.active, "children": []}
                 for u in rows}
        roots = []
        for u in rows:  # path order guarantees parents come before children
            parent = nodes.get(u.parent_id)
            (parent["children"] if parent else roots).append(nodes[u.pk])
        return Response({"count": len(rows), "truncated": truncated, "roots": roots})

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        record("org_unit.create", request=self.request, entity_type="organizational_unit",
               entity_id=obj.pk, metadata={"code": obj.code, "level": obj.level, "type": str(obj.unit_type_id or ""),
                                           "designations": sorted(obj.designations.values_list("code", flat=True))})

    @transaction.atomic
    def perform_update(self, serializer):
        before = serializer.instance
        old = {"type": str(before.unit_type_id or ""), "designations": sorted(before.designations.values_list("code", flat=True)),
               "exception": [before.strength_exception_min, before.strength_exception_max]}
        obj = serializer.save()
        record("org_unit.update", request=self.request, entity_type="organizational_unit",
               entity_id=obj.pk, metadata={"fields": sorted(serializer.validated_data.keys())})
        # Template changes get their own, searchable audit events (who changed what, from what).
        new_designations = sorted(obj.designations.values_list("code", flat=True))
        if old["designations"] != new_designations:
            record("org_unit.designations_change", request=self.request, entity_type="organizational_unit",
                   entity_id=obj.pk, metadata={"from": old["designations"], "to": new_designations})
        if old["type"] != str(obj.unit_type_id or ""):
            record("org_unit.type_change", request=self.request, entity_type="organizational_unit",
                   entity_id=obj.pk, metadata={"from": old["type"], "to": str(obj.unit_type_id or "")})
        if old["exception"] != [obj.strength_exception_min, obj.strength_exception_max]:
            record("org_unit.strength_exception", request=self.request, entity_type="organizational_unit",
                   entity_id=obj.pk, metadata={"from": old["exception"],
                                               "to": [obj.strength_exception_min, obj.strength_exception_max]})


class ServiceBranchViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                           mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Branch catalogue: readable by anyone with org.view; changes need HQ org.manage."""

    serializer_class = BranchSerializer
    queryset = ServiceBranch.objects.all()
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": ("org.view", "any"), "retrieve": ("org.view", "any"),
        "create": ("org.manage", "global"), "partial_update": ("org.manage", "global"),
    }

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        record("branch.create", request=self.request, entity_type="service_branch",
               entity_id=obj.pk, metadata={"code": obj.code})

    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.save()
        record("branch.update", request=self.request, entity_type="service_branch", entity_id=obj.pk)


class _Catalogue(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                 mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Template catalogues: readable by anyone with org.view; changes need headquarters org.manage. All audited."""

    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None
    permission_map = {
        "list": ("org.view", "any"), "retrieve": ("org.view", "any"),
        "create": ("org.manage", "global"), "partial_update": ("org.manage", "global"),
    }
    entity = ""

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        record(f"{self.entity}.create", request=self.request, entity_type=self.entity, entity_id=obj.pk,
               metadata={"code": getattr(obj, "code", "")})

    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.save()
        record(f"{self.entity}.update", request=self.request, entity_type=self.entity, entity_id=obj.pk,
               metadata={"fields": sorted(serializer.validated_data.keys())})


class UnitTypeViewSet(_Catalogue):
    """Reading is unchanged. While STRUCTURE_CHANGES_REQUIRE_APPROVAL is on (default), levels are changed only through
    an approved StructureChange; direct writes are refused (permission is still checked first)."""

    serializer_class = UnitTypeSerializer
    queryset = UnitType.objects.select_related("parent_type")
    entity = "unit_type"

    def create(self, request, *args, **kwargs):
        if settings.STRUCTURE_CHANGES_REQUIRE_APPROVAL:
            raise structure_changes.StructureApprovalRequired()
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if settings.STRUCTURE_CHANGES_REQUIRE_APPROVAL:
            raise structure_changes.StructureApprovalRequired()
        return super().partial_update(request, *args, **kwargs)


class DesignationViewSet(_Catalogue):
    serializer_class = DesignationSerializer
    queryset = SpecialistDesignation.objects.all()
    entity = "specialist_designation"


class RuleViewSet(_Catalogue):
    serializer_class = RuleSerializer
    queryset = DesignationRule.objects.select_related("parent_type", "child_type", "designation")
    entity = "designation_rule"


class StructureViewSet(viewsets.GenericViewSet):
    """Reference vs actual strength per unit, and deviations from the standard template, within the caller's scope."""

    permission_classes = [ScopedPermission]
    permission_map = {"list": ("org.view", "unit"), "findings": ("org.view", "unit")}
    serializer_class = UnitSerializer

    def get_queryset(self):
        qs = scope.scoped_units(self.request.user, "org.view").filter(unit_type__isnull=False)
        p = self.request.query_params
        if p.get("type"):
            qs = qs.filter(unit_type__code=p["type"].upper())
        if uuid_param(self.request, "parent"):
            qs = qs.filter(parent=uuid_param(self.request, "parent"))
        if p.get("active") in ("true", "false"):
            qs = qs.filter(active=p["active"] == "true")
        return qs.select_related("unit_type", "parent").prefetch_related("designations").order_by("unit_type__tier", "path")

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        totals = structure.subtree_strength(request.user, page)
        rows = []
        for u in page:
            actual = totals.get(u.path, 0) if scope.can(request.user, "personnel.view", u) else None
            status, has_exc, lo, hi = structure.strength_status(u, u.unit_type, actual)
            rows.append({
                "id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so, "level": u.level,
                "active": u.active, "parent": str(u.parent_id) if u.parent_id else None,
                "unit_type": str(u.unit_type_id), "designations": [str(d.pk) for d in u.designations.all()],
                "reference_min": lo, "reference_max": hi, "has_exception": has_exc,
                "strength_exception_note": u.strength_exception_note if has_exc else "",
                "actual_strength": actual, "strength_status": status})
        return self.get_paginated_response(rows)

    @action(detail=False, methods=["get"])
    def findings(self, request):
        data = structure.findings(request.user)
        return Response({"count": len(data), "truncated": len(data) > 500, "results": data[:500]})


class StructureChangeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                             mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Propose -> submit -> a different person approves (which applies) or rejects. Nothing is live before approval."""

    serializer_class = StructureChangeSerializer
    queryset = StructureChange.objects.all()
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    _both = ("org.structure_propose", "org.structure_approve")
    permission_map = {
        "list": (_both, "global"), "retrieve": (_both, "global"),
        "create": ("org.structure_propose", "global"), "partial_update": ("org.structure_propose", "global"),
        "submit": ("org.structure_propose", "global"),
        "approve": ("org.structure_approve", "global"), "reject": ("org.structure_approve", "global"),
    }

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def _meta(self, obj):
        return {"title": obj.title, "operations": len(obj.operations)}

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        record("structure_change.create", request=self.request, entity_type="structure_change", entity_id=obj.pk, metadata=self._meta(obj))

    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.save()
        record("structure_change.update", request=self.request, entity_type="structure_change", entity_id=obj.pk,
               metadata={"fields": sorted(serializer.validated_data.keys())})

    def _require_status(self, obj, status):
        if obj.status != status:
            raise field_error("status", "invalid_transition", "That is not allowed in the current state.")

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        obj = self.get_object()
        expected = require_version(request.data)
        self._require_status(obj, StructureChange.Status.DRAFT)
        if obj.proposed_by_id != request.user.pk:
            raise PermissionDenied("Only the proposer can submit.", code="not_proposer")
        impact = structure_changes.evaluate(obj.operations)
        if impact["errors"]:
            raise field_error("operations", "proposal_invalid", "The proposal has problems.")
        with transaction.atomic():
            obj = versioned_update(obj, {"status": "submitted", "submitted_at": timezone.now(), "impact": impact}, expected)
            record("structure_change.submit", request=request, entity_type="structure_change", entity_id=obj.pk, metadata=self._meta(obj))
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        expected = require_version(request.data)
        self._require_status(obj, StructureChange.Status.SUBMITTED)
        if obj.proposed_by_id == request.user.pk:  # separation of duties is not configurable
            record("access.denied", request=request, outcome="denied", entity_type="structure_change", entity_id=obj.pk,
                   metadata={"reason": "self_approval"})
            raise PermissionDenied("You cannot approve your own proposal.", code="self_approval_forbidden")
        note = str(request.data.get("note", ""))[:500]
        with transaction.atomic():
            report = structure_changes.apply(obj, request.user, request)
            obj = versioned_update(obj, {"status": "approved", "decided_by": request.user, "decided_by_username": request.user.username,
                                         "decided_at": timezone.now(), "decision_note": note, "impact": report}, expected)
            record("structure_change.approve", request=request, entity_type="structure_change", entity_id=obj.pk, metadata=self._meta(obj))
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        obj = self.get_object()
        expected = require_version(request.data)
        self._require_status(obj, StructureChange.Status.SUBMITTED)
        note = str(request.data.get("note", "")).strip()[:500]
        if len(note) < 3:
            raise field_error("note", "note_required", "Give a reason.")
        with transaction.atomic():
            obj = versioned_update(obj, {"status": "rejected", "decided_by": request.user, "decided_by_username": request.user.username,
                                         "decided_at": timezone.now(), "decision_note": note}, expected)
            record("structure_change.reject", request=request, entity_type="structure_change", entity_id=obj.pk, metadata=self._meta(obj))
        return Response(self.get_serializer(obj).data)


def _change_request_out(obj):
    return {"id": str(obj.pk), "kind": obj.kind, "status": obj.status, "summary": obj.summary, "payload": obj.payload,
            "unit": str(obj.unit_id), "order_ref": obj.order_ref, "issuing_officer": obj.issuing_officer,
            "order_date": obj.order_date.isoformat(), "batch": str(obj.batch_id) if obj.batch_id else None, "proposed_by": obj.proposed_by_username,
            "created_at": obj.created_at.isoformat(), "review_started_at": obj.review_started_at and obj.review_started_at.isoformat(),
            "decided_by": obj.decided_by_username, "decided_at": obj.decided_at and obj.decided_at.isoformat(),
            "decision_note": obj.decision_note, "self_approved": obj.self_approved, "version": obj.version}


class ChangeRequestViewSet(viewsets.GenericViewSet):
    """Hierarchy-affecting actions: HQ administrators propose (with the Army order), the super administrator decides.
    Nothing is live before approval. Permissions are enforced here on the server; the user interface only mirrors them."""

    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "head", "options"]
    queryset = ChangeRequest.objects.all()
    _both = ("changes.propose", "changes.approve")
    permission_map = {
        "list": (_both, "global"), "retrieve": (_both, "global"),
        "create": ("changes.propose", "global"), "withdraw": ("changes.propose", "global"),
        "start_review": ("changes.approve", "global"), "approve": ("changes.approve", "global"),
        "bulk_transfer": ("changes.propose", "global"), "batch": (_both, "global"),
        "reject": ("changes.approve", "global"), "people": ("changes.propose", "global"), "appointment_types": ("changes.propose", "global"),
    }

    def get_queryset(self):
        qs = super().get_queryset()
        for key in ("status", "kind"):
            if self.request.query_params.get(key):
                qs = qs.filter(**{key: self.request.query_params[key]})
        if uuid_param(self.request, "batch"):
            qs = qs.filter(batch_id=uuid_param(self.request, "batch"))
        return qs

    def list(self, request):
        rows = list(self.get_queryset()[:200])
        record("change_request.list", request=request, entity_type="change_request", metadata={"count": len(rows)})
        return Response({"results": [_change_request_out(r) for r in rows]})

    def retrieve(self, request, pk=None):
        obj = self.get_object()
        record("change_request.view", request=request, entity_type="change_request", entity_id=obj.pk)
        return Response(_change_request_out(obj))

    def create(self, request):
        d = request.data
        obj = change_requests.propose(
            request.user, request, kind=d.get("kind"), payload=d.get("payload"), order_ref=d.get("order_ref"),
            issuing_officer=d.get("issuing_officer"), order_date=d.get("order_date"))
        return Response(_change_request_out(obj), status=201)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        obj = change_requests.withdraw(self.get_object(), request.user, request, require_version(request.data))
        return Response(_change_request_out(obj))

    @action(detail=True, methods=["post"], url_path="start-review")
    def start_review(self, request, pk=None):
        obj = change_requests.start_review(self.get_object(), request.user, request, require_version(request.data))
        return Response(_change_request_out(obj))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = change_requests.approve(self.get_object(), request.user, request, require_version(request.data),
                                      str(request.data.get("note", "")))
        return Response(_change_request_out(obj))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        obj = change_requests.reject(self.get_object(), request.user, request, require_version(request.data),
                                     str(request.data.get("note", "")))
        return Response(_change_request_out(obj))

    @action(detail=False, methods=["get"])
    def people(self, request):
        """Narrow lookup so an HQ administrator can name the person in a request: name, service number, rank, unit and current
        appointments only (no phone, profile, documents or history). Needs >= 3 characters, returns at most 20, and is audited."""
        from apps.personnel.models import CommandAppointment, Personnel

        text = (request.query_params.get("q") or "").strip()
        if len(text) < 3:
            raise field_error("q", "query_too_short", "Type at least 3 characters.")
        q = scope.unit_scope_q(request.user, "changes.propose", "org_unit__")
        rows = []
        if q is not None:
            people = list(Personnel.objects.filter(q).filter(Q(full_name__icontains=text) | Q(service_number__iexact=text))
                          .select_related("rank", "org_unit")[:20])
            open_by = {}
            for a in CommandAppointment.objects.filter(personnel__in=people, ended_at__isnull=True).select_related("appointment_type", "org_unit"):
                open_by.setdefault(a.personnel_id, []).append({"id": str(a.pk), "type": a.appointment_type.name_en, "unit": a.org_unit.name_en})
            rows = [{"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number, "rank": p.rank.name_en,
                     "unit": p.org_unit.name_en, "unit_id": str(p.org_unit_id), "status": p.status,
                     "open_appointments": open_by.get(p.pk, [])} for p in people]
        record("change_request.people_lookup", request=request, entity_type="personnel", metadata={"count": len(rows)})
        return Response({"results": rows})

    @action(detail=False, methods=["get"], url_path="appointment-types")
    def appointment_types(self, request):
        """The command post catalogue, so an HQ administrator can choose the post in a request (it holds no personal data)."""
        from apps.personnel.models import AppointmentType

        return Response({"results": [{"id": str(t.pk), "code": t.code, "name_en": t.name_en, "name_so": t.name_so,
                                      "unit_type": str(t.unit_type_id) if t.unit_type_id else None, "exclusive": t.exclusive}
                                     for t in AppointmentType.objects.filter(active=True).order_by("code")]})

    @action(detail=False, methods=["post"], url_path="bulk-transfer")
    def bulk_transfer(self, request):
        """One Army order moving many people. All rows are checked first; if any is wrong nothing is created and every
        problem row is reported. `items` is a list of {service_number | personnel, org_unit?}; `org_unit` is the default
        destination. The requests are decided together (see `batch`)."""
        d = request.data
        try:
            rows = change_requests.propose_bulk_transfer(
                request.user, request, items=d.get("items"), order_ref=d.get("order_ref"), issuing_officer=d.get("issuing_officer"),
                order_date=d.get("order_date"), org_unit=d.get("org_unit"), effective_date=d.get("effective_date"), reason=str(d.get("reason") or ""))
        except change_requests.BulkInvalid as exc:
            return Response({"code": "bulk_invalid", "detail": "Some rows cannot be used. Nothing was created.", "rows": exc.rows}, status=400)
        return Response({"batch": str(rows[0].batch_id), "count": len(rows), "results": [_change_request_out(r) for r in rows]}, status=201)

    @action(detail=False, methods=["post"])
    def batch(self, request):
        """Decide or withdraw a whole batch atomically: {batch, action: approve|reject|start_review|withdraw, count, note}."""
        d = request.data
        rows = change_requests.decide_batch(request.user, request, batch=d.get("batch"), action=d.get("action"),
                                            expected_count=d.get("count"), note=str(d.get("note") or ""))
        return Response({"batch": str(rows[0].batch_id), "count": len(rows), "results": [_change_request_out(r) for r in rows]})
