import uuid

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.models import User
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import require_version, versioned_update
from apps.core.errors import field_error
from apps.core.params import uuid_param
from apps.organization.models import OrganizationalUnit

from . import services as svc
from .models import Asset, InventoryCategory, Reconciliation, StockLine
from .serializers import (AssetChangeSerializer, AssetCreateSerializer, AssetEventSerializer, AssetSerializer,
                          CategorySerializer, ReconciliationDetailSerializer, ReconciliationSerializer,
                          StockLineCreateSerializer, StockLinePatchSerializer, StockLineSerializer,
                          StockTransactionSerializer, TransactionInputSerializer, TransferInputSerializer)

VIEW_CODES = ("logistics.view", "logistics.restricted")


def _subtree(qs, request, param="org_unit"):
    unit_id = uuid_param(request, param)
    if unit_id:
        unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
        qs = qs.filter(org_unit__path__startswith=unit.path) if unit else qs.none()
    return qs


class CategoryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = CategorySerializer
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None
    ANY = (*VIEW_CODES, "logistics.configure", "logistics.approve", "logistics.restricted_approve")
    permission_map = {
        "list": (ANY, "any"), "retrieve": (ANY, "any"),
        "create": ("logistics.configure", "global"), "partial_update": ("logistics.configure", "global"),
        "approve": (("logistics.approve", "logistics.restricted_approve"), "global"),
    }

    def get_queryset(self):
        u = self.request.user
        qs = InventoryCategory.objects.all()
        if not (scope.has_anywhere(u, "logistics.restricted") or scope.can(u, "logistics.restricted_approve")
                or scope.can(u, "logistics.configure")):
            qs = qs.filter(restricted=False)  # restricted categories are invisible to everyone else
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        record("category.create", request=self.request, entity_type="inventory_category", entity_id=obj.pk,
               metadata={"code": obj.code, "restricted": obj.restricted})

    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.save()
        record("category.update", request=self.request, entity_type="inventory_category", entity_id=obj.pk)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        cat = self.get_object()
        needed = "logistics.restricted_approve" if cat.restricted else "logistics.approve"
        if not scope.can(request.user, needed):
            record("category.approve", request=request, outcome="denied", entity_type="inventory_category",
                   entity_id=cat.pk, metadata={"needed": needed})
            raise PermissionDenied("Institutional review permission is required.", code="permission_denied")
        if cat.created_by_id == request.user.pk:
            record("category.approve", request=request, outcome="denied", entity_type="inventory_category",
                   entity_id=cat.pk, metadata={"reason": "self_approval"})
            raise PermissionDenied("You cannot approve a category you created.", code="self_approval_not_allowed")
        if not cat.name_so.strip():
            return Response({"code": "somali_name_required", "detail": "A Somali name is required."}, status=409)
        expected = require_version(request.data)
        with transaction.atomic():
            cat = versioned_update(cat, {"approval_status": "approved", "approved_by": request.user,
                                         "approved_at": timezone.now()}, expected)
            record("category.approve", request=request, entity_type="inventory_category", entity_id=cat.pk,
                   metadata={"restricted": cat.restricted})
        return Response(CategorySerializer(cat).data)


class StockViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = StockLineSerializer
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": (VIEW_CODES, "unit"), "retrieve": (VIEW_CODES, "unit"),
        "create": ("logistics.manage", "any"), "partial_update": ("logistics.manage", "unit"),
        "post_transaction": ("logistics.manage", "unit"), "transfer": ("logistics.manage", "unit"),
    }

    def scope_unit(self, obj):
        return obj.org_unit

    def get_queryset(self):
        qs = StockLine.objects.filter(svc.visible_q(self.request.user, "org_unit__", "category__")).select_related("category", "org_unit")
        if uuid_param(self.request, "category"):
            qs = qs.filter(category=uuid_param(self.request, "category"))
        qs = _subtree(qs, self.request)
        if self.request.query_params.get("below_reorder") == "1":
            qs = qs.filter(reorder_level__gt=0, quantity__lte=F("reorder_level"))
        return qs

    def _out(self, line):
        return Response(StockLineSerializer(StockLine.objects.select_related("category", "org_unit").get(pk=line.pk)).data)

    def create(self, request, *args, **kwargs):
        ser = StockLineCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        line = svc.create_stock_line(request, d["category"], d["org_unit"], d.get("uom", ""), d["reorder_level"])
        resp = self._out(line)
        resp.status_code = 201
        return resp

    def partial_update(self, request, *args, **kwargs):
        line = self.get_object()
        svc.authorize(request, line.org_unit, line.category)
        ser = StockLinePatchSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            line = versioned_update(line, dict(ser.validated_data), require_version(request.data))
            record("stock.line_update", request=request, entity_type="stock_line", entity_id=line.pk,
                   metadata={"fields": sorted(ser.validated_data)})
        return self._out(line)

    @action(detail=True, methods=["get", "post"], url_path="transactions")
    def post_transaction(self, request, pk=None):
        line = self.get_object()
        if request.method == "GET":
            page = self.paginate_queryset(line.transactions.select_related("counterpart_unit"))
            return self.get_paginated_response(StockTransactionSerializer(page, many=True).data)
        ser = TransactionInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        svc.post_stock(request, line, d["kind"], d["delta"], d.get("reason", ""), d.get("expected_balance"))
        return self._out(line)

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        line = self.get_object()
        ser = TransferInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        svc.transfer_stock(request, line, d["to_unit"], d["quantity"], d.get("reason", ""))
        return self._out(line)


class AssetViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = AssetSerializer
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": (VIEW_CODES, "unit"), "retrieve": (VIEW_CODES, "unit"), "events": (VIEW_CODES, "unit"),
        "create": ("logistics.manage", "any"), "change": ("logistics.manage", "unit"),
        "custodian": ("logistics.manage", "unit"),
    }

    def scope_unit(self, obj):
        return obj.org_unit

    def get_queryset(self):
        qs = (Asset.objects.filter(svc.visible_q(self.request.user, "org_unit__", "category__"))
              .select_related("category", "org_unit", "issued_to_unit", "custodian"))
        p = self.request.query_params
        if uuid_param(self.request, "category"):
            qs = qs.filter(category=uuid_param(self.request, "category"))
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("q"):
            qs = qs.filter(identifier__icontains=p["q"])
        return _subtree(qs, self.request)

    def _out(self, asset, status=200):
        a = Asset.objects.select_related("category", "org_unit", "issued_to_unit", "custodian").get(pk=asset.pk)
        return Response(AssetSerializer(a).data, status=status)

    def create(self, request, *args, **kwargs):
        ser = AssetCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        return self._out(svc.register_asset(request, d["category"], d["org_unit"], d["identifier"], d["description"]), 201)

    @action(detail=True, methods=["post"])
    def change(self, request, pk=None):
        asset = self.get_object()
        ser = AssetChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        updated = svc.change_asset(request, asset, d["action"], require_version(request.data), d["note"], d.get("to_unit"))
        return self._out(updated)

    @action(detail=True, methods=["post"])
    def custodian(self, request, pk=None):
        asset = self.get_object()
        username = request.data.get("username")
        candidate = None
        if username:
            candidate = User.objects.filter(username=str(username).lower()).first()
            if candidate is None:
                raise field_error("username", "custodian_not_authorised")
        return self._out(svc.set_custodian(request, asset, candidate, require_version(request.data)))

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        asset = self.get_object()
        return Response(AssetEventSerializer(asset.events.select_related("from_unit", "to_unit"), many=True).data)


class ReconciliationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("logistics.reconcile", "unit"), "retrieve": ("logistics.reconcile", "unit"),
        "create": ("logistics.reconcile", "any"), "count": ("logistics.reconcile", "unit"),
        "complete": ("logistics.reconcile", "unit"), "cancel": ("logistics.reconcile", "unit"),
    }

    def scope_unit(self, obj):
        return obj.org_unit

    def get_serializer_class(self):
        return ReconciliationSerializer if self.action == "list" else ReconciliationDetailSerializer

    def get_queryset(self):
        user = self.request.user
        q = scope.unit_scope_q(user, "logistics.reconcile", "org_unit__")
        if q is None:
            return Reconciliation.objects.none()
        restricted = scope.unit_scope_q(user, "logistics.restricted", "org_unit__")
        q &= Q(includes_restricted=False) | (restricted if restricted is not None else Q(pk__in=[]))
        return Reconciliation.objects.filter(q).select_related("org_unit", "started_by").prefetch_related("lines")

    def _out(self, rec, status=200):
        r = self.get_queryset().get(pk=rec.pk)
        return Response(ReconciliationDetailSerializer(r).data, status=status)

    def create(self, request, *args, **kwargs):
        raw = request.data.get("org_unit")
        try:
            unit = OrganizationalUnit.objects.filter(pk=uuid.UUID(str(raw))).first() if raw else None
        except ValueError:
            unit = None
        if unit is None:
            raise field_error("org_unit", "required")
        return self._out(svc.start_reconciliation(request, unit, str(request.data.get("notes") or "")), 201)

    @action(detail=True, methods=["post"])
    def count(self, request, pk=None):
        rec = self.get_object()
        items = request.data.get("lines")
        if not isinstance(items, list) or not items or len(items) > 5000:
            raise field_error("lines", "invalid_count")
        svc.count_lines(request, rec, items)
        return self._out(rec)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._out(svc.complete_reconciliation(request, self.get_object(), require_version(request.data)))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._out(svc.cancel_reconciliation(request, self.get_object(), require_version(request.data)))


class LogisticsSummaryViewSet(viewsets.GenericViewSet):
    queryset = StockLine.objects.none()
    pagination_class = None
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("logistics.report", "any")}

    def list(self, request):
        return Response(svc.summary(request.user))
