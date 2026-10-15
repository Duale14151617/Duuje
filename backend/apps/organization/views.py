from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, viewsets

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.params import uuid_param

from rest_framework.decorators import action
from rest_framework.response import Response

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.core.concurrency import require_version, versioned_update
from apps.core.errors import field_error

from . import structure, structure_changes
from .models import DesignationRule, ServiceBranch, SpecialistDesignation, StructureChange, UnitType
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
        "tree": ("org.view", "any"),
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
            qs = qs.filter(level__in=["branch_command", "unit"])
        return qs.select_related("parent", "branch").prefetch_related("designations")

    TREE_LIMIT = 2000

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
