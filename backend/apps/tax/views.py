"""Vehicle and traffic taxes (cash, paper receipt): business rules and API.

Access: tax.view reads (narrowed to the caller's unit scope), tax.record registers vehicles, records receipts, voids them and hands cash
over, tax.confirm counts and confirms a handover (never the person who handed it over), tax.configure sets the tax types (headquarters).
Rows are voided with a reason, never deleted. Every write is audited; reads are audited without personal data."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
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
from apps.core.concurrency import VersionConflict, require_version
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING
from apps.vehicles.services import plate_key
from apps.vehicles.views import _person_brief, _uid, _unit_brief

from .models import TaxCounter, TaxHandover, TaxPayment, TaxType, TaxVehicle

Pay, Veh, Typ, Ho = TaxPayment, TaxVehicle, TaxType, TaxHandover


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


# ---- helpers ---------------------------------------------------------------------------------------------------------------
def _text(d, name, limit, required=False):
    v = d.get(name)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise field_error(name, "required", "This field is required.")
    if len(v) > limit:
        raise field_error(name, "too_long", "Too long.")
    return v


def _date(value, name, required=False):
    if value in (None, ""):
        if required:
            raise field_error(name, "required", "This field is required.")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(name, "invalid_date", "Use YYYY-MM-DD.")


def _money(value, name):
    try:
        x = Decimal(str(value).strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise field_error(name, "invalid_number", "Enter a valid amount.")
    if x <= 0 or x > Decimal("9999999999"):
        raise field_error(name, "invalid_amount", "The amount must be more than zero.")
    return x


def _currency(value, name="currency"):
    c = str(value or "").strip().upper()
    if len(c) != 3 or not c.isalpha():
        raise field_error(name, "invalid_currency", "Use a three-letter currency code such as USD.")
    return c


def add_months(d, months):
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _iso(value):
    """A date as YYYY-MM-DD text (or None), so the API answer is the same whether it is read before or after JSON rendering."""
    return value.isoformat() if value is not None else None


def _money_str(value):
    """Money always with two decimals ('25.00'); SQLite sums come back without the scale, PostgreSQL ones with it."""
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _actor(request):
    return getattr(getattr(request, "user", None), "username", "") or ""


def _next(name, prefix):
    c, _ = TaxCounter.objects.select_for_update().get_or_create(name=name)
    c.last += 1
    c.save(update_fields=["last"])
    return f"{prefix}-{c.last:06d}"


def covered_until(vehicle, tax_type):
    """Last day covered by live (non-void) payments of a recurring type, or None."""
    return Pay.objects.filter(vehicle=vehicle, tax_type=tax_type, voided_at__isnull=True, period_to__isnull=False).order_by("-period_to") \
        .values_list("period_to", flat=True).first()


# ---- business rules --------------------------------------------------------------------------------------------------------
@transaction.atomic
def register_vehicle(request, unit, d):
    plate = _text(d, "plate", 20, required=True)
    key = plate_key(plate)
    if not key:
        raise field_error("plate", "required", "This field is required.")
    if Veh.objects.filter(plate_key=key).exists():
        raise field_error("plate", "duplicate", "This plate is already registered.")
    try:
        with transaction.atomic():
            v = Veh.objects.create(plate=plate.upper(), plate_key=key, owner_name=_text(d, "owner_name", 200, required=True),
                                   owner_phone=_text(d, "owner_phone", 40), id_ref=_text(d, "id_ref", 80), vehicle_kind=_text(d, "vehicle_kind", 60),
                                   make_model=_text(d, "make_model", 120), org_unit=unit, notes=_text(d, "notes", 300), created_by_username=_actor(request))
    except IntegrityError:
        raise field_error("plate", "duplicate", "This plate is already registered.")
    record("tax.vehicle_register", request=request, entity_type="tax_vehicle", entity_id=v.pk, metadata={"plate_key": key, "org_unit": str(unit.pk)})
    return v


@transaction.atomic
def edit_vehicle(request, row, d, version):
    v = Veh.objects.select_for_update().get(pk=row.pk)
    if v.version != version:
        raise VersionConflict()
    changed = []
    for name, limit in (("owner_name", 200), ("owner_phone", 40), ("id_ref", 80), ("vehicle_kind", 60), ("make_model", 120), ("notes", 300)):
        if name in d:
            new = _text(d, name, limit, required=name == "owner_name")
            if new != getattr(v, name):
                setattr(v, name, new)
                changed.append(name)
    if "active" in d and bool(d["active"]) != v.active:
        v.active = bool(d["active"])
        changed.append("active")
    if changed:
        v.version += 1
        v.save()
        record("tax.vehicle_edit", request=request, entity_type="tax_vehicle", entity_id=v.pk, metadata={"fields": changed})
    return v


@transaction.atomic
def record_payment(request, vehicle, unit, d):
    v = Veh.objects.select_for_update().get(pk=vehicle.pk)
    if not v.active:
        raise field_error("vehicle", "inactive", "This vehicle is switched off in the register.")
    t = Typ.objects.filter(pk=_uid(d.get("tax_type"))).first() if _uid(d.get("tax_type")) else None
    if t is None or not t.active:
        raise field_error("tax_type", "unknown", "Choose a tax type.")
    receipt = _text(d, "receipt_no", 40, required=True)
    paid_on = _date(d.get("paid_on"), "paid_on") or timezone.localdate()
    if paid_on > timezone.localdate():
        raise field_error("paid_on", "future", "A payment cannot be dated in the future.")
    raw = d.get("amount")
    if raw in (None, ""):
        if t.default_amount is None:
            raise field_error("amount", "required", "This tax type has no standard amount yet. Enter the amount on the receipt.")
        amount = t.default_amount
    else:
        amount = _money(raw, "amount")
    currency = _currency(d.get("currency") or t.currency)
    p_from = p_to = None
    if t.recurring:
        p_from = _date(d.get("period_from"), "period_from")
        if p_from is None:  # continue from the end of the current cover; if it has lapsed, start on the payment date
            end = covered_until(v, t)
            p_from = end + timedelta(days=1) if end and end >= paid_on else paid_on
        p_to = _date(d.get("period_to"), "period_to") or add_months(p_from, t.period_months) - timedelta(days=1)
        if p_to < p_from:
            raise field_error("period_to", "before_start", "The period cannot end before it starts.")
    if Pay.objects.filter(org_unit=unit, receipt_no=receipt, voided_at__isnull=True).exists():
        raise field_error("receipt_no", "duplicate", "This receipt number was already used in this station.")
    collector = None
    if d.get("collected_by") not in (None, ""):
        collector = Personnel.objects.filter(pk=_uid(d["collected_by"])).exclude(status__in=NOT_SERVING).first() if _uid(d["collected_by"]) else None
        if collector is None:
            raise field_error("collected_by", "unknown", "Unknown or non-serving person.")
    try:
        with transaction.atomic():
            p = Pay.objects.create(receipt_no=receipt, org_unit=unit, vehicle=v, tax_type=t, amount=amount, currency=currency, paid_on=paid_on,
                                   period_from=p_from, period_to=p_to, reference=_text(d, "reference", 150), collected_by=collector,
                                   collected_by_username=_actor(request))
    except IntegrityError:
        raise field_error("receipt_no", "duplicate", "This receipt number was already used in this station.")
    record("tax.payment_record", request=request, entity_type="tax_payment", entity_id=p.pk,
           metadata={"receipt_no": receipt, "tax_type": t.code, "amount": str(amount), "currency": currency, "org_unit": str(unit.pk)})
    return p


@transaction.atomic
def void_payment(request, row, d, version):
    p = Pay.objects.select_for_update().select_related("tax_type").get(pk=row.pk)
    if p.version != version:
        raise VersionConflict()
    if p.voided_at:
        raise field_error("state", "already_void", "This payment is already voided.")
    if p.handover_id:
        raise field_error("state", "handed_over", "This receipt is already in a cash handover and cannot be voided.")
    reason = _text(d, "reason", 300, required=True)
    p.voided_at, p.voided_by_username, p.voided_reason = timezone.now(), _actor(request), reason
    p.version += 1
    p.save()
    record("tax.payment_void", request=request, entity_type="tax_payment", entity_id=p.pk, metadata={"receipt_no": p.receipt_no, "reason": reason})
    return p


@transaction.atomic
def hand_over(request, unit, d):
    currency = _currency(d.get("currency") or getattr(settings, "TAX_CURRENCY", "USD"))
    qs = Pay.objects.select_for_update().filter(org_unit=unit, handover__isnull=True, voided_at__isnull=True, currency=currency)
    until = _date(d.get("until"), "until")
    if until:
        qs = qs.filter(paid_on__lte=until)
    rows = list(qs)
    if not rows:
        raise field_error("org_unit", "nothing_to_hand_over", "There are no uncollected receipts for this station in that currency.")
    total = sum((p.amount for p in rows), Decimal(0))
    h = Ho.objects.create(number=_next("handover", "HO"), org_unit=unit, currency=currency, expected_amount=total, payments_count=len(rows),
                          handed_by_username=_actor(request), note=_text(d, "note", 300))
    Pay.objects.filter(pk__in=[p.pk for p in rows]).update(handover=h)
    record("tax.handover", request=request, entity_type="tax_handover", entity_id=h.pk,
           metadata={"number": h.number, "expected": str(total), "currency": currency, "count": len(rows), "org_unit": str(unit.pk)})
    return h


@transaction.atomic
def confirm_handover(request, row, d, version):
    h = Ho.objects.select_for_update().get(pk=row.pk)
    if h.version != version:
        raise VersionConflict()
    if h.status != Ho.Status.SUBMITTED:
        raise field_error("state", "already_confirmed", "This handover was already counted.")
    if h.handed_by_username == _actor(request) and not scope.self_approval_allowed(request.user, "tax_handover", request, "cash_handover", h.pk):
        raise field_error("state", "own_handover", "Cash must be counted by someone other than the person who handed it over.")
    if d.get("counted_amount") in (None, ""):
        raise field_error("counted_amount", "required", "Enter the cash counted.")
    try:
        counted = Decimal(str(d["counted_amount"]).strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise field_error("counted_amount", "invalid_number", "Enter a valid amount.")
    if counted < 0 or counted > Decimal("99999999999"):
        raise field_error("counted_amount", "invalid_amount", "Enter the cash counted (zero or more).")
    note = _text(d, "note", 300)
    if counted != h.expected_amount and not note:
        raise field_error("note", "difference_needs_note", "The cash counted differs from the receipts. Explain the difference in the note.")
    h.status, h.counted_amount, h.confirmed_by_username, h.confirmed_at = Ho.Status.CONFIRMED, counted, _actor(request), timezone.now()
    if note:
        h.note = (h.note + " | " if h.note else "") + note
    h.version += 1
    h.save()
    record("tax.handover_confirm", request=request, entity_type="tax_handover", entity_id=h.pk,
           metadata={"number": h.number, "expected": str(h.expected_amount), "counted": str(counted), "difference": str(counted - h.expected_amount)})
    return h


def save_type(request, row, d, version=None):
    code = _text(d, "code", 40, required=row is None).lower() if row is None else row.code
    with transaction.atomic():
        t = Typ.objects.select_for_update().get(pk=row.pk) if row else Typ(code=code)
        if row and t.version != version:
            raise VersionConflict()
        if row is None and Typ.objects.filter(code=code).exists():
            raise field_error("code", "duplicate", "This code already exists.")
        t.name_en = _text(d, "name_en", 120, required=True) if "name_en" in d or row is None else t.name_en
        if "name_so" in d:
            t.name_so = _text(d, "name_so", 120)
        if "kind" in d:
            if d["kind"] not in {c.value for c in Typ.Kind}:
                raise field_error("kind", "invalid_choice", "Choose licence, road tax, fine or fee.")
            t.kind = d["kind"]
        if "default_amount" in d:
            t.default_amount = None if d["default_amount"] in (None, "") else _money(d["default_amount"], "default_amount")
        if "currency" in d:
            t.currency = _currency(d["currency"])
        if "recurring" in d:
            t.recurring = bool(d["recurring"])
        if "period_months" in d:
            try:
                n = int(d["period_months"])
            except (TypeError, ValueError):
                raise field_error("period_months", "invalid_number", "Enter a number of months.")
            if not 1 <= n <= 120:
                raise field_error("period_months", "invalid_number", "Use 1 to 120 months.")
            t.period_months = n
        if "active" in d:
            t.active = bool(d["active"])
        if row:
            t.version += 1
        t.save()
    record("tax.type_edit" if row else "tax.type_create", request=request, entity_type="tax_type", entity_id=t.pk, metadata={"code": t.code})
    return t


# ---- serialisers -----------------------------------------------------------------------------------------------------------
def _type_out(t):
    return {"id": str(t.pk), "code": t.code, "name_en": t.name_en, "name_so": t.name_so, "kind": t.kind,
            "default_amount": None if t.default_amount is None else str(t.default_amount), "currency": t.currency, "recurring": t.recurring,
            "period_months": t.period_months, "active": t.active, "version": t.version}


def _vehicle_out(v, cover=None):
    d = {"id": str(v.pk), "plate": v.plate, "owner_name": v.owner_name, "owner_phone": v.owner_phone, "id_ref": v.id_ref, "vehicle_kind": v.vehicle_kind,
         "make_model": v.make_model, "org_unit": _unit_brief(v.org_unit), "active": v.active, "notes": v.notes, "version": v.version}
    if cover is not None:
        today = timezone.localdate()
        d["cover"] = [{"tax_type": code, "paid_until": _iso(end), "overdue": end is None or end < today} for code, end in cover]
    return d


def _payment_out(p):
    return {"id": str(p.pk), "receipt_no": p.receipt_no, "org_unit": _unit_brief(p.org_unit),
            "vehicle": {"id": str(p.vehicle.pk), "plate": p.vehicle.plate, "owner_name": p.vehicle.owner_name},
            "tax_type": {"id": str(p.tax_type.pk), "code": p.tax_type.code, "name_en": p.tax_type.name_en, "name_so": p.tax_type.name_so},
            "amount": _money_str(p.amount), "currency": p.currency, "paid_on": _iso(p.paid_on), "period_from": _iso(p.period_from), "period_to": _iso(p.period_to),
            "reference": p.reference, "collector": _person_brief(p.collected_by) if p.collected_by_id else None, "recorded_by": p.collected_by_username,
            "handover": p.handover.number if p.handover_id else None, "void": p.voided_at is not None, "voided_reason": p.voided_reason, "version": p.version}


def _handover_out(h):
    diff = None if h.counted_amount is None else str(h.counted_amount - h.expected_amount)
    return {"id": str(h.pk), "number": h.number, "org_unit": _unit_brief(h.org_unit), "currency": h.currency, "expected_amount": str(h.expected_amount),
            "payments_count": h.payments_count, "handed_by": h.handed_by_username, "handed_at": h.handed_at, "status": h.status,
            "counted_amount": None if h.counted_amount is None else str(h.counted_amount), "difference": diff, "confirmed_by": h.confirmed_by_username,
            "confirmed_at": h.confirmed_at, "note": h.note, "version": h.version}


# ---- API -------------------------------------------------------------------------------------------------------------------
class TaxViewSet(viewsets.GenericViewSet):
    """Vehicle and traffic taxes. Reads are audited and narrowed to the caller's unit scope (out-of-scope rows answer 404)."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9a-f\-]{36}"
    permission_map = {"types": ("tax.view", "any"), "type_create": ("tax.configure", "global"), "type_update": ("tax.configure", "global"),
                      "vehicles": ("tax.view", "any"), "vehicle_create": ("tax.record", "any"), "vehicle_detail": ("tax.view", "any"),
                      "vehicle_edit": ("tax.record", "any"), "payments": ("tax.view", "any"), "payment_create": ("tax.record", "any"),
                      "payment_void": ("tax.record", "any"), "handovers": ("tax.view", "any"), "handover_create": ("tax.record", "any"),
                      "handover_confirm": ("tax.confirm", "any"), "summary": ("tax.view", "any"), "report": ("tax.view", "any"),
                      "overdue_export": ("tax.view", "any")}

    # scoping
    def _q(self, code, prefix):
        return scope.unit_scope_q(self.request.user, code, prefix)

    def _vehicles(self):
        q = self._q("tax.view", "org_unit__")
        return Veh.objects.none() if q is None else Veh.objects.filter(q)

    def _payments(self):
        q = self._q("tax.view", "org_unit__")
        return Pay.objects.none() if q is None else Pay.objects.filter(q)

    def _handovers(self):
        q = self._q("tax.view", "org_unit__")
        return Ho.objects.none() if q is None else Ho.objects.filter(q)

    def _unit(self, value, code, field="org_unit"):
        u = OrganizationalUnit.objects.filter(pk=_uid(value)).first() if _uid(value) else None
        if u is None or not scope.can(self.request.user, code, unit=u):
            raise field_error(field, "unknown", "Choose a station you work in.")
        return u

    def _vehicle(self, pk, write=False):
        v = self._vehicles().select_related("org_unit").filter(pk=_uid(pk)).first() if _uid(pk) else None
        if v is None or (write and not scope.can(self.request.user, "tax.record", unit=v.org_unit)):
            raise Http404
        return v

    # tax types
    @action(detail=False, methods=["get"])
    def types(self, request):
        qs = Typ.objects.all() if request.query_params.get("all") == "1" else Typ.objects.filter(active=True)
        return Response({"results": [_type_out(t) for t in qs]})

    @action(detail=False, methods=["post"], url_path="types/create")
    def type_create(self, request):
        return Response(_type_out(save_type(request, None, json_body(request))), status=201)

    @action(detail=True, methods=["post"], url_path="types/update")
    def type_update(self, request, pk=None):
        d = json_body(request)
        row = Typ.objects.filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None:
            raise Http404
        return Response(_type_out(save_type(request, row, d, require_version(d))))

    # vehicles
    @action(detail=False, methods=["get"])
    def vehicles(self, request):
        p = request.query_params
        qs = self._vehicles().select_related("org_unit")
        if p.get("include_inactive") != "1":
            qs = qs.filter(active=True)
        if p.get("q"):
            s = p["q"].strip()[:60]
            qs = qs.filter(Q(plate_key__icontains=plate_key(s) or s) | Q(owner_name__icontains=s) | Q(owner_phone__icontains=s) | Q(id_ref__icontains=s))
        if p.get("overdue") == "1":
            today = timezone.localdate()
            types = Typ.objects.filter(active=True, recurring=True)
            if p.get("type"):
                types = types.filter(code=p["type"])
            lacking = Q(pk__in=[])
            for t in types:
                covered = Pay.objects.filter(vehicle=OuterRef("pk"), tax_type=t, voided_at__isnull=True, period_to__gte=today)
                lacking |= Q(pk__in=Veh.objects.exclude(Exists(covered)).values("pk"))
            qs = qs.filter(lacking)
        page = self.paginate_queryset(qs.order_by("plate_key"))
        recurring = list(Typ.objects.filter(active=True, recurring=True))
        ends = {}
        for vid, code, end in Pay.objects.filter(vehicle__in=[v.pk for v in page], tax_type__in=recurring, voided_at__isnull=True) \
                .values_list("vehicle_id", "tax_type__code", "period_to").order_by("period_to"):
            ends[(vid, code)] = end
        out = [_vehicle_out(v, [(t.code, ends.get((v.pk, t.code))) for t in recurring]) for v in page]
        record_read(request, "tax.read_vehicles", entity_type="tax_vehicle_list", count=len(page))
        return self.get_paginated_response(out)

    @action(detail=False, methods=["post"], url_path="vehicles/create")
    def vehicle_create(self, request):
        d = json_body(request)
        v = register_vehicle(request, self._unit(d.get("org_unit"), "tax.record"), d)
        return Response(_vehicle_out(Veh.objects.select_related("org_unit").get(pk=v.pk)), status=201)

    @action(detail=True, methods=["get"], url_path="vehicle")
    def vehicle_detail(self, request, pk=None):
        v = self._vehicle(pk)
        recurring = list(Typ.objects.filter(active=True, recurring=True))
        cover = [(t.code, covered_until(v, t)) for t in recurring]
        pays = Pay.objects.filter(vehicle=v).select_related("org_unit", "tax_type", "vehicle", "handover", "collected_by__rank").order_by("-paid_on", "-created_at")[:100]
        record_read(request, "tax.read_vehicle", entity_type="tax_vehicle", entity_id=v.pk, org_unit=v.org_unit)
        return Response({**_vehicle_out(v, cover), "payments": [_payment_out(p) for p in pays]})

    @action(detail=True, methods=["post"], url_path="vehicle/edit")
    def vehicle_edit(self, request, pk=None):
        d = json_body(request)
        v = edit_vehicle(request, self._vehicle(pk, write=True), d, require_version(d))
        return Response(_vehicle_out(Veh.objects.select_related("org_unit").get(pk=v.pk)))

    # payments
    @action(detail=False, methods=["get"])
    def payments(self, request):
        p = request.query_params
        qs = self._payments().select_related("org_unit", "tax_type", "vehicle", "handover", "collected_by__rank")
        if p.get("include_void") != "1":
            qs = qs.filter(voided_at__isnull=True)
        if p.get("uncollected") == "1":
            qs = qs.filter(handover__isnull=True, voided_at__isnull=True)
        if _uid(p.get("vehicle")):
            qs = qs.filter(vehicle_id=_uid(p["vehicle"]))
        if p.get("type"):
            qs = qs.filter(tax_type__code=p["type"])
        if p.get("from"):
            qs = qs.filter(paid_on__gte=_date(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(paid_on__lte=_date(p["to"], "to"))
        if p.get("q"):
            s = p["q"].strip()[:60]
            qs = qs.filter(Q(receipt_no__icontains=s) | Q(vehicle__plate_key__icontains=plate_key(s) or s) | Q(reference__icontains=s))
        page = self.paginate_queryset(qs.order_by("-paid_on", "-created_at"))
        record_read(request, "tax.read_payments", entity_type="tax_payment_list", count=len(page))
        return self.get_paginated_response([_payment_out(x) for x in page])

    @action(detail=False, methods=["post"], url_path="payments/create")
    def payment_create(self, request):
        d = json_body(request)
        v = self._vehicle(d.get("vehicle"))
        unit = self._unit(d.get("org_unit") or str(v.org_unit_id), "tax.record")
        p = record_payment(request, v, unit, d)
        return Response(_payment_out(Pay.objects.select_related("org_unit", "tax_type", "vehicle", "handover", "collected_by__rank").get(pk=p.pk)), status=201)

    @action(detail=True, methods=["post"], url_path="payments/void")
    def payment_void(self, request, pk=None):
        d = json_body(request)
        row = self._payments().select_related("org_unit").filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None or not scope.can(request.user, "tax.record", unit=row.org_unit):
            raise Http404
        p = void_payment(request, row, d, require_version(d))
        return Response(_payment_out(Pay.objects.select_related("org_unit", "tax_type", "vehicle", "handover", "collected_by__rank").get(pk=p.pk)))

    # cash handovers
    @action(detail=False, methods=["get"])
    def handovers(self, request):
        qs = self._handovers().select_related("org_unit")
        if request.query_params.get("status") in {"submitted", "confirmed"}:
            qs = qs.filter(status=request.query_params["status"])
        page = self.paginate_queryset(qs.order_by("-handed_at"))
        record_read(request, "tax.read_handovers", entity_type="tax_handover_list", count=len(page))
        return self.get_paginated_response([_handover_out(h) for h in page])

    @action(detail=False, methods=["post"], url_path="handovers/create")
    def handover_create(self, request):
        d = json_body(request)
        h = hand_over(request, self._unit(d.get("org_unit"), "tax.record"), d)
        return Response(_handover_out(Ho.objects.select_related("org_unit").get(pk=h.pk)), status=201)

    @action(detail=True, methods=["post"], url_path="handovers/confirm")
    def handover_confirm(self, request, pk=None):
        d = json_body(request)
        row = self._handovers().select_related("org_unit").filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None or not scope.can(request.user, "tax.confirm", unit=row.org_unit):
            raise Http404
        h = confirm_handover(request, row, d, require_version(d))
        return Response(_handover_out(Ho.objects.select_related("org_unit").get(pk=h.pk)))

    @action(detail=False, methods=["get"])
    def summary(self, request):
        live = self._payments().filter(voided_at__isnull=True)
        today = timezone.localdate()
        month = today.replace(day=1)

        def total(qs):
            return [{"currency": r["currency"], "total": _money_str(r["s"]), "count": r["n"]} for r in qs.values("currency").annotate(s=Sum("amount"), n=Count("id")).order_by("currency")]

        out = {"today": total(live.filter(paid_on=today)), "this_month": total(live.filter(paid_on__gte=month)), "uncollected": total(live.filter(handover__isnull=True)),
               "waiting_to_count": self._handovers().filter(status="submitted").count()}
        record_read(request, "tax.read_summary", entity_type="tax_summary")
        return Response(out)

    @action(detail=False, methods=["get"])
    def report(self, request):
        """Collection report: receipts grouped by day, station, tax type and currency (?from=&to=, default today; ?unit= limits to a station
        and the units below it), plus voided receipts and cash still with collectors for the same stations."""
        p = request.query_params
        today = timezone.localdate()
        d0, d1 = _date(p.get("from"), "from") or today, _date(p.get("to"), "to") or today
        if d1 < d0:
            raise field_error("to", "before_start", "The end date cannot be before the start date.")
        if (d1 - d0).days > 366:
            raise field_error("to", "range_too_long", "Choose a period of at most one year.")
        base = self._payments()
        if _uid(p.get("unit")):
            prefix = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).values_list("path", flat=True).first()
            base = base.filter(org_unit__path__startswith=prefix) if prefix else base.none()
        span = base.filter(paid_on__gte=d0, paid_on__lte=d1)
        live = span.filter(voided_at__isnull=True)
        rows = live.values("paid_on", "org_unit__code", "org_unit__name_en", "org_unit__name_so", "tax_type__code", "tax_type__name_en", "tax_type__name_so", "currency") \
            .annotate(total=Sum("amount"), n=Count("id")).order_by("paid_on", "org_unit__code", "tax_type__code")
        held = base.filter(voided_at__isnull=True, handover__isnull=True).values("org_unit__code", "org_unit__name_en", "org_unit__name_so", "currency") \
            .annotate(total=Sum("amount"), n=Count("id")).order_by("org_unit__code")
        record_read(request, "tax.read_report", entity_type="tax_report", count=live.count())
        unit = lambda r: {"code": r["org_unit__code"], "name_en": r["org_unit__name_en"], "name_so": r["org_unit__name_so"]}  # noqa: E731
        return Response({"from": d0, "to": d1,
                         "rows": [{"date": r["paid_on"], "unit": unit(r), "tax_type": {"code": r["tax_type__code"], "name_en": r["tax_type__name_en"], "name_so": r["tax_type__name_so"]},
                                   "currency": r["currency"], "count": r["n"], "total": _money_str(r["total"])} for r in rows],
                         "voided": span.filter(voided_at__isnull=False).count(),
                         "held_by_collectors": [{"unit": unit(r), "currency": r["currency"], "count": r["n"], "total": _money_str(r["total"])} for r in held]})

    @action(detail=False, methods=["get"], url_path="overdue-export")
    def overdue_export(self, request):
        """Every active vehicle in scope that lacks current cover for a recurring tax type (up to 5000), for printing or a spreadsheet.
        The export is audited (who, how many rows), never the names."""
        today = timezone.localdate()
        types = list(Typ.objects.filter(active=True, recurring=True))
        lacking = Q(pk__in=[])
        for t in types:
            covered = Pay.objects.filter(vehicle=OuterRef("pk"), tax_type=t, voided_at__isnull=True, period_to__gte=today)
            lacking |= Q(pk__in=Veh.objects.exclude(Exists(covered)).values("pk"))
        vs = list(self._vehicles().filter(active=True).filter(lacking).select_related("org_unit").order_by("org_unit__code", "plate_key")[:5000])
        ends = {}
        for vid, code, end in Pay.objects.filter(vehicle__in=[v.pk for v in vs], tax_type__in=types, voided_at__isnull=True) \
                .values_list("vehicle_id", "tax_type__code", "period_to").order_by("period_to"):
            ends[(vid, code)] = end
        record("tax.export_overdue", request=request, entity_type="tax_vehicle_list", metadata={"count": len(vs)})
        return Response({"types": [{"code": t.code, "name_en": t.name_en, "name_so": t.name_so} for t in types], "truncated": len(vs) == 5000,
                         "results": [{**_vehicle_out(v), "paid_until": {t.code: ends.get((v.pk, t.code)) for t in types}} for v in vs]})
