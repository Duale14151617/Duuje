import uuid
from datetime import timedelta

from django.db.models import Count, DecimalField, Exists, F, OuterRef, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.logistics import services as logi
from apps.logistics.models import StockLine, StockTransaction
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel

from . import services as svc
from .models import PpeInspection, PpeMovement

INSPECTION_WINDOW_DAYS = 30


def _unit(u):
    return {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}


def _person(p):
    # Only what accountability needs: name, service number, rank, unit. Nothing else from the personnel record.
    return {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
            "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}, "unit": _unit(p.org_unit)}


def _get_person(raw, field="personnel"):
    try:
        pk = uuid.UUID(str(raw))
    except (ValueError, TypeError):
        raise field_error(field, "required")
    p = Personnel.objects.select_related("rank", "org_unit").filter(pk=pk).first()
    if p is None:
        raise field_error(field, "required")
    return p


def _ppe_lines(user, request=None):
    qs = StockLine.objects.filter(logi.visible_q(user, "org_unit__", "category__"), category__code__startswith=svc.PREFIX)
    if request is not None:
        unit_id = uuid_param(request, "org_unit")
        if unit_id:
            unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
            qs = qs.filter(org_unit__path__startswith=unit.path) if unit else qs.none()
    return qs


class PpeViewSet(viewsets.GenericViewSet):
    queryset = StockLine.objects.none()
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("logistics.view", "any"), "ledger": ("logistics.view", "any"), "holder": ("logistics.view", "any"),
        "summary": ("logistics.view", "any"), "people": ("logistics.manage", "any"),
        "movement": ("logistics.manage", "unit"), "replace": ("logistics.manage", "unit"), "inspect": ("logistics.manage", "unit"),
    }

    def scope_unit(self, obj):
        return obj.org_unit

    def get_queryset(self):
        return _ppe_lines(self.request.user, self.request).select_related("category", "org_unit")

    def list(self, request):
        """PPE stock lines with what is in store and what is held by personnel. One grouped query; server-side filter and paging."""
        qs = self.get_queryset()
        p = request.query_params
        if uuid_param(request, "category"):
            qs = qs.filter(category=uuid_param(request, "category"))
        if p.get("q"):
            qs = qs.filter(Q(category__name_en__icontains=p["q"]) | Q(category__name_so__icontains=p["q"]) | Q(org_unit__name_en__icontains=p["q"]))
        if p.get("below_reorder") == "1":
            qs = qs.filter(reorder_level__gt=0, quantity__lte=F("reorder_level"))
        qs = qs.annotate(held=Coalesce(Sum("ppe_movements__delta"), 0)).order_by("category__code", "org_unit__path")
        page = self.paginate_queryset(qs)
        rows = [{"id": str(l.pk), "category": {"id": str(l.category_id), "code": l.category.code, "name_en": l.category.name_en,
                                              "name_so": l.category.name_so},
                 "org_unit": _unit(l.org_unit), "uom": l.uom, "in_store": l.quantity, "held": l.held,
                 "reorder_level": l.reorder_level, "below_reorder": l.reorder_level > 0 and l.quantity <= l.reorder_level,
                 "version": l.version} for l in page]
        return self.get_paginated_response(rows)

    def _line_action(self):
        line = self.get_queryset().filter(pk=self.kwargs["pk"]).first()
        if line is None:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        self.check_object_permissions(self.request, line)
        return line

    def _out(self, row):
        p = row.personnel
        return {"id": str(row.pk), "kind": row.kind, "quantity": abs(row.delta), "personnel": _person(p)}

    @action(detail=True, methods=["post"])
    def movement(self, request, pk=None):
        line = self._line_action()
        d = json_body(request)
        q = d.get("quantity")
        row = svc.post(request, _get_person(d.get("personnel")), line, str(d.get("kind") or ""), q if isinstance(q, int) else 0, d)
        return Response(self._out(row), status=201)

    @action(detail=True, methods=["post"])
    def replace(self, request, pk=None):
        line = self._line_action()
        d = json_body(request)
        q = d.get("quantity")
        _, new = svc.replace(request, _get_person(d.get("personnel")), line, q if isinstance(q, int) else 0,
                             str(d.get("out_kind") or "damaged"), d)
        return Response(self._out(new), status=201)

    @action(detail=True, methods=["post"])
    def inspect(self, request, pk=None):
        line = self._line_action()
        d = json_body(request)
        row = svc.inspect(request, _get_person(d.get("personnel")), line, str(d.get("condition") or ""), d.get("inspected_on"),
                          d.get("next_due"), d.get("note"))
        return Response({"id": str(row.pk), "condition": row.condition, "next_due": row.next_due}, status=201)

    @action(detail=False, methods=["get"])
    def ledger(self, request):
        """Paginated movement history (newest first). Filters: kind, category, org_unit, personnel, from, to."""
        user = request.user
        lines = _ppe_lines(user, request)
        qs = PpeMovement.objects.filter(stock_line__in=lines.values("pk")).select_related("personnel__rank", "stock_line__category")
        p = request.query_params
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if uuid_param(request, "category"):
            qs = qs.filter(stock_line__category=uuid_param(request, "category"))
        if uuid_param(request, "personnel"):
            qs = qs.filter(personnel=uuid_param(request, "personnel"))
        if p.get("q"):
            qs = qs.filter(Q(personnel__service_number__icontains=p["q"]) | Q(reference__icontains=p["q"]))
        try:
            if p.get("from"):
                qs = qs.filter(created_at__date__gte=timezone.datetime.fromisoformat(p["from"]).date())
            if p.get("to"):
                qs = qs.filter(created_at__date__lte=timezone.datetime.fromisoformat(p["to"]).date())
        except ValueError:
            raise field_error("from", "invalid_date", "Use a date like 2026-03-01.")
        page = self.paginate_queryset(qs)
        rows = [{"id": str(r.pk), "kind": r.kind, "quantity": abs(r.delta), "size": r.size, "serial": r.serial, "condition": r.condition,
                 "reference": r.reference, "authority_ref": r.authority_ref, "note": r.note, "actor": r.actor_username,
                 "personnel": {"id": str(r.personnel_id), "full_name": r.personnel.full_name, "service_number": r.personnel.service_number},
                 "category": {"code": r.stock_line.category.code, "name_en": r.stock_line.category.name_en, "name_so": r.stock_line.category.name_so},
                 "at": r.created_at} for r in page]
        record_read(request, "ppe.read_ledger", entity_type="ppe_ledger", count=len(rows))
        return self.get_paginated_response(rows)

    @action(detail=False, methods=["get"])
    def holder(self, request):
        """One person's PPE holdings, inspections and history. Needs logistics.view over the person's unit."""
        person = _get_person(request.query_params.get("personnel"))
        if not scope.can(request.user, "logistics.view", unit=person.org_unit):
            raise field_error("personnel", "out_of_scope", "That person is outside your scope.")
        holdings, history = svc.person_ppe(person)
        record_read(request, "ppe.read_holder", entity_type="personnel", entity_id=person.pk, org_unit=person.org_unit, count=len(history))
        return Response({"personnel": _person(person), "holdings": holdings, "history": history})

    @action(detail=False, methods=["get"])
    def people(self, request):
        """Minimal lookup of serving personnel (name, service number, rank) in a unit, to issue PPE to. Opens no personnel record."""
        from apps.personnel.services import NOT_SERVING
        q = scope.unit_scope_q(request.user, "logistics.manage", "org_unit__")
        uid = uuid_param(request, "org_unit")
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if q is None or unit is None:
            return Response({"results": []})
        qs = Personnel.objects.filter(q, org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING).select_related("rank", "org_unit")
        term = (request.query_params.get("q") or "").strip()[:60]
        if term:
            qs = qs.filter(Q(full_name__icontains=term) | Q(service_number__icontains=term))
        return Response({"results": [_person(x) for x in qs.order_by("full_name")[:20]]})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(ppe_summary(request.user, _ppe_lines(request.user, request)))


def ppe_summary(user, lines, today=None):
    """PPE aggregates for the dashboard: a fixed number of grouped queries however many people hold equipment.
    `lines` is the already-scoped queryset of PPE stock lines."""
    today = today or timezone.localdate()
    horizon = today + timedelta(days=INSPECTION_WINDOW_DAYS)
    ids = lines.values("pk")
    moves = PpeMovement.objects.filter(stock_line__in=ids)
    store = {r["category__code"]: r for r in lines.values("category__code", "category__name_en", "category__name_so")
             .annotate(in_store=Sum("quantity"), n=Count("pk"))}
    by_kind = {}
    for code, kind, s in moves.values_list("stock_line__category__code", "kind").annotate(s=Sum("delta")):
        by_kind.setdefault(code, {})[kind] = s
    cats = []
    for code, r in sorted(store.items()):
        k = by_kind.get(code, {})
        cats.append({"code": code, "name_en": r["category__name_en"], "name_so": r["category__name_so"], "in_store": r["in_store"] or 0,
                     "held": sum(k.values()), "damaged": -k.get("damaged", 0), "lost": -k.get("lost", 0), "retired": -k.get("retired", 0)})
    held_pairs = (moves.values("personnel", "stock_line").annotate(h=Sum("delta")).filter(h__gt=0))
    holders = held_pairs.values("personnel").distinct().count()
    holding_pairs = held_pairs.count()
    holds = Exists(moves.filter(personnel=OuterRef("personnel"), stock_line=OuterRef("stock_line")).values("personnel", "stock_line")
                   .annotate(h=Sum("delta")).filter(h__gt=0))
    newer = PpeInspection.objects.filter(personnel=OuterRef("personnel"), stock_line=OuterRef("stock_line")).filter(
        Q(inspected_on__gt=OuterRef("inspected_on")) | Q(inspected_on=OuterRef("inspected_on"), created_at__gt=OuterRef("created_at")))
    latest = PpeInspection.objects.filter(stock_line__in=ids).filter(holds, ~Exists(newer))
    cond = {c: n for c, n in latest.values_list("condition").annotate(n=Count("pk"))}
    inspected = sum(cond.values())
    due = latest.filter(next_due__isnull=False, next_due__lte=horizon).count()
    overdue = latest.filter(next_due__isnull=False, next_due__lt=today).count()
    out = {
        "lines": lines.count(),
        "in_store": sum(c["in_store"] for c in cats), "with_personnel": sum(c["held"] for c in cats),
        "holders": holders, "holding_pairs": holding_pairs,
        "damaged": sum(c["damaged"] for c in cats), "lost": sum(c["lost"] for c in cats), "retired": sum(c["retired"] for c in cats),
        "below_reorder": lines.filter(reorder_level__gt=0, quantity__lte=F("reorder_level")).count(),
        "by_category": cats,
        "inspection": {"window_days": INSPECTION_WINDOW_DAYS, "inspected": inspected, "never_inspected": max(holding_pairs - inspected, 0),
                       "due": due, "overdue": overdue, "by_condition": cond},
        "procurement": {"visible": False, "by_currency": []},
    }
    if scope.has_anywhere(user, "logistics.report"):
        spend = (StockTransaction.objects.filter(stock_line__in=ids, kind="receive", unit_cost__isnull=False)
                 .values("currency").annotate(total=Coalesce(Sum(F("delta") * F("unit_cost"), output_field=DecimalField(max_digits=18, decimal_places=2)), 0),
                                              qty=Sum("delta")).order_by("currency"))
        out["procurement"] = {"visible": True, "by_currency": [{"currency": r["currency"], "total": str(r["total"]), "quantity": r["qty"]} for r in spend]}
    return out
