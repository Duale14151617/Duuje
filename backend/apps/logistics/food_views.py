"""Food stores API: suppliers, receipts (with expiry), allocations with delivery acknowledgement, warnings."""
from datetime import date

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import uuid_param
from apps.organization.models import OrganizationalUnit

from . import food, food_bulk
from .models import FoodAllocation, FoodBatch, InventoryCategory, StockLine, Supplier

VIEW, MANAGE = "food.view", "food.manage"
LIMIT = 200


def _supplier(s):
    return {"id": str(s.pk), "name": s.name, "phone": s.phone, "address": s.address, "notes": s.notes, "active": s.active, "version": s.version}


def _batch(b):
    return {"id": str(b.pk), "stock_line": str(b.stock_line_id), "org_unit": str(b.stock_line.org_unit_id),
            "org_unit_name": b.stock_line.org_unit.name_en, "category": b.stock_line.category.name_en, "uom": b.stock_line.uom,
            "supplier": b.supplier.name if b.supplier_id else "", "supplier_id": str(b.supplier_id) if b.supplier_id else None,
            "batch_ref": b.batch_ref, "quantity": b.quantity, "remaining": b.remaining, "received_on": b.received_on.isoformat(),
            "expires_on": b.expires_on.isoformat() if b.expires_on else None, "source": b.source,
            "delivery_note_ref": b.delivery_note_ref, "order_ref": b.authority_ref, "entered_by": b.created_by_username,
            "created_at": b.created_at.isoformat()}


def _alloc(a):
    return {"id": str(a.pk), "status": a.status, "quantity": a.quantity, "uom": a.from_line.uom, "category": a.from_line.category.name_en,
            "from_unit": str(a.from_line.org_unit_id), "from_unit_name": a.from_line.org_unit.name_en, "stock_line": str(a.from_line_id),
            "to_unit": str(a.to_unit_id), "to_unit_name": a.to_unit.name_en, "order_ref": a.order_ref,
            "issuing_officer": a.issuing_officer, "order_date": a.order_date.isoformat(), "issue_note_ref": a.issue_note_ref,
            "issued_by": a.issued_by_username, "issued_at": a.issued_at.isoformat(),
            "delivered_at": a.delivered_at.isoformat() if a.delivered_at else None, "received_by_name": a.received_by_name,
            "receipt_note_ref": a.receipt_note_ref, "acknowledged_by": a.acknowledged_by_username,
            "cancel_reason": a.cancel_reason, "version": a.version}


def _visible(request, prefix):
    q = scope.unit_scope_q(request.user, VIEW, prefix)
    return q


class SupplierViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    queryset = Supplier.objects.all()
    permission_map = {"list": (VIEW, "global"), "retrieve": (VIEW, "global"), "create": (MANAGE, "global"),
                      "partial_update": (MANAGE, "global")}

    def list(self, request):
        qs = self.get_queryset()
        if request.query_params.get("active") in ("true", "false"):
            qs = qs.filter(active=request.query_params["active"] == "true")
        return Response({"results": [_supplier(s) for s in qs[:LIMIT]]})

    def retrieve(self, request, pk=None):
        return Response(_supplier(self.get_object()))

    def create(self, request):
        return Response(_supplier(food.supplier_create(request, request.data)), status=201)

    def partial_update(self, request, pk=None):
        return Response(_supplier(food.supplier_update(request, self.get_object(), request.data, require_version(request.data))))


class FoodReceiptViewSet(viewsets.GenericViewSet):
    """Deliveries from suppliers (one batch each). Entered directly by HQ administrators with the delivery note and Army order."""

    permission_classes = [ScopedPermission]
    throttle_scope = None  # set per action for imports
    http_method_names = ["get", "post", "head", "options"]
    permission_map = {"list": (VIEW, "global"), "create": (MANAGE, "global"), "opening_import": (MANAGE, "global")}

    @action(detail=False, methods=["post"], url_path="opening-import", parser_classes=[MultiPartParser], throttle_scope="bulk")
    def opening_import(self, request):
        """Opening food stock from a CSV or XLSX file. Without `confirm=true` this only checks the file and reports every problem
        by row (nothing is saved); with it, the file is checked again and, if clean, saved in one transaction."""
        upload = request.FILES.get("file")
        if upload is None:
            raise field_error("file", "file_required", "Choose a file.")
        authority = food._text(request.data.get("authority_ref"), "authority_ref", "authority_required", 150)
        rows = food_bulk.parse_upload(upload)
        results = food_bulk.validate_opening(request.user, rows)
        problems = [{"row": r["row"], "errors": r["errors"]} for r in results if r["errors"]]
        if str(request.data.get("confirm", "")).lower() != "true":
            record("food.opening_preview", request=request, entity_type="food_batch", metadata={"rows": len(rows), "problems": len(problems)})
            return Response({"total": len(rows), "valid": len(rows) - len(problems), "can_commit": not problems, "rows": problems,
                             "stores": food_bulk.summarise(results) if not problems else []})
        if problems:  # re-checked on confirm: data and scope may have changed since the preview
            return Response({"code": "import_has_errors", "detail": "Fix the file and check it again.", "rows": problems}, status=409)
        return Response(food_bulk.commit_opening(request, results, authority), status=201)

    def list(self, request):
        q = _visible(request, "stock_line__org_unit__")
        qs = FoodBatch.objects.filter(q, source="receipt") if q is not None else FoodBatch.objects.none()
        qs = qs.select_related("stock_line__org_unit", "stock_line__category", "supplier")
        unit_id = uuid_param(request, "org_unit")
        if unit_id:
            unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
            qs = qs.filter(stock_line__org_unit__path__startswith=unit.path) if unit else qs.none()
        if uuid_param(request, "supplier"):
            qs = qs.filter(supplier=uuid_param(request, "supplier"))
        rows = list(qs.order_by("-received_on", "-created_at")[:LIMIT])
        record("food.receipts_list", request=request, entity_type="food_batch", metadata={"count": len(rows)})
        return Response({"results": [_batch(b) for b in rows]})

    def create(self, request):
        return Response(_batch(food.receive(request, request.data)), status=201)


class FoodAllocationViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    throttle_scope = None  # set per action for the bulk transfer
    http_method_names = ["get", "post", "head", "options"]
    queryset = FoodAllocation.objects.select_related("from_line__org_unit", "from_line__category", "to_unit")
    permission_map = {"list": (VIEW, "global"), "retrieve": (VIEW, "global"), "create": (MANAGE, "global"),
                      "acknowledge": (MANAGE, "global"), "cancel": (MANAGE, "global"), "bulk": (MANAGE, "global")}

    def get_queryset(self):
        q = _visible(self.request, "from_line__org_unit__")
        qs = super().get_queryset()
        qs = qs.filter(q) if q is not None else qs.none()
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def list(self, request):
        rows = list(self.get_queryset()[:LIMIT])
        record("food.allocations_list", request=request, entity_type="food_allocation", metadata={"count": len(rows)})
        return Response({"results": [_alloc(a) for a in rows]})

    def retrieve(self, request, pk=None):
        return Response(_alloc(self.get_object()))

    def create(self, request):
        return Response(_alloc(food.issue(request, request.data)), status=201)

    @action(detail=False, methods=["post"], throttle_scope="bulk")
    def bulk(self, request):
        """One order, one source store, many destination units. All lines are issued or none is."""
        try:
            allocations = food_bulk.bulk_issue(request, request.data)
        except food_bulk.BulkProblems as exc:
            return Response({"code": "bulk_has_errors", "detail": "Some lines have problems. Nothing was issued.", "rows": exc.rows},
                            status=409)
        return Response({"count": len(allocations), "quantity": sum(a.quantity for a in allocations),
                         "allocations": [_alloc(a) for a in allocations]}, status=201)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        return Response(_alloc(food.acknowledge(request, self.get_object(), request.data, require_version(request.data))))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(_alloc(food.cancel(request, self.get_object(), request.data, require_version(request.data))))


class FoodWarningsViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": (VIEW, "global")}

    def list(self, request):
        try:
            days = max(0, min(365, int(request.query_params.get("days", 30))))
        except ValueError:
            raise field_error("days", "invalid_number", "Enter a number of days.")
        data = food.warnings(request.user, days)
        record("food.warnings_view", request=request, entity_type="food_batch",
               metadata={"low": len(data["low_stock"]), "expiring": len(data["expiring"]), "unbatched": len(data["unbatched"])})
        return Response({**data, "days": days, "as_of": date.today().isoformat()})


class FoodOptionsViewSet(viewsets.GenericViewSet):
    """What the food screens need to fill their pick-lists (food categories and the stores holding food), so HQ administrators
    do not need access to the general logistics lists."""

    permission_classes = [ScopedPermission]
    permission_map = {"list": (VIEW, "global")}

    def list(self, request):
        cats = InventoryCategory.objects.filter(code__startswith="food", kind="stock", approval_status="approved", active=True)
        q = _visible(request, "org_unit__")
        lines = StockLine.objects.filter(q, category__in=cats).select_related("category", "org_unit") if q is not None else StockLine.objects.none()
        return Response({
            "categories": [{"id": str(c.pk), "code": c.code, "name_en": c.name_en, "name_so": c.name_so} for c in cats],
            "stores": [{"id": str(ln.pk), "org_unit": str(ln.org_unit_id), "org_unit_name": ln.org_unit.name_en, "category": str(ln.category_id),
                        "category_name": ln.category.name_en, "quantity": ln.quantity, "uom": ln.uom, "reorder_level": ln.reorder_level}
                       for ln in lines[:LIMIT]]})
