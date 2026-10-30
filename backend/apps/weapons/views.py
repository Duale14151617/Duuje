import uuid

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.logistics.models import Asset, AssetEvent, InventoryCategory, StockLine
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from . import rounds as rnd
from . import services as svc
from .models import SoldierRounds, WeaponCustody, WeaponDetail


def _uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _scoped(user, code="weapons.view"):
    q1 = scope.unit_scope_q(user, code, "org_unit__")
    q2 = scope.unit_scope_q(user, code, "issued_to_unit__")
    if q1 is None and q2 is None:
        return Asset.objects.none()
    q = (q1 if q1 is not None else Q(pk__in=[])) | (q2 if q2 is not None else Q(pk__in=[]))
    return Asset.objects.filter(q, weapon__isnull=False)


def _unit_brief(u):
    return None if u is None else {"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so}


def _custody_out(c):
    p = c.personnel
    return {"id": str(c.pk), "personnel": {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                                           "status": p.status, "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}},
            "issued_at": c.issued_at, "issued_by": c.issued_by_username, "authority_ref": c.authority_ref,
            "issue_condition": c.issue_condition, "issue_note": c.issue_note, "returned_at": c.returned_at,
            "returned_by": c.returned_by_username, "outcome": c.outcome, "return_condition": c.return_condition,
            "return_note": c.return_note}


def _out(a, custody=None, detail=False):
    w = a.weapon
    d = {"id": str(a.pk), "serial": a.identifier, "category": {"id": str(a.category_id), "code": a.category.code,
                                                              "name_en": a.category.name_en, "name_so": a.category.name_so},
         "org_unit": _unit_brief(a.org_unit), "issued_to_unit": _unit_brief(a.issued_to_unit), "status": a.status,
         "weapon_type": w.weapon_type, "make_model": w.make_model, "caliber": w.caliber, "condition": w.condition,
         "description": a.description, "version": a.version,
         "custody": _custody_out(custody) if custody is not None else None}
    if detail:
        d["custody_history"] = [_custody_out(c) for c in WeaponCustody.objects.filter(asset=a).select_related("personnel__rank")]
        d["events"] = [{"kind": e.kind, "from_status": e.from_status, "to_status": e.to_status, "note": e.note,
                        "actor": e.actor_username, "at": e.created_at} for e in AssetEvent.objects.filter(asset=a).order_by("-created_at")[:200]]
    return d


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


class WeaponViewSet(viewsets.GenericViewSet):
    """Auditable weapon register, for explicitly authorized personnel only (weapons.view / weapons.manage inside the unit's scope,
    plus the restricted-category rule of the asset ledger). Weapons are tracked by unique serial number; counts are derived."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    permission_map = {
        "list": ("weapons.view", "any"), "retrieve": ("weapons.view", "unit"), "summary": ("weapons.view", "any"),
        "categories": ("weapons.manage", "any"), "people": ("weapons.manage", "any"), "create": ("weapons.manage", "any"),
        "holdings": ("weapons.view", "any"), "disposition": ("weapons.view", "any"), "rounds_history": ("weapons.view", "any"), "rounds": ("weapons.manage", "any"), "ammo_lines": ("weapons.manage", "any"),
        "issue": ("weapons.manage", "unit"), "give_back": ("weapons.manage", "unit"), "condition": ("weapons.manage", "unit"),
    }

    def scope_unit(self, obj):
        return svc.effective_unit(obj)

    def get_queryset(self):
        return _scoped(self.request.user).select_related("category", "org_unit", "issued_to_unit", "weapon")

    def _custody_map(self, assets):
        ids = [a.pk for a in assets]
        return {c.asset_id: c for c in WeaponCustody.objects.filter(asset_id__in=ids, returned_at__isnull=True)
                .select_related("personnel__rank")}

    def list(self, request):
        qs = self.get_queryset()
        p = request.query_params
        if p.get("q"):
            q = p["q"].strip()[:60]
            qs = qs.filter(Q(identifier__icontains=q) | Q(weapon__weapon_type__icontains=q) | Q(weapon__make_model__icontains=q))
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("condition"):
            qs = qs.filter(weapon__condition=p["condition"])
        unit = uuid_param(request, "org_unit")
        if unit:
            base = OrganizationalUnit.objects.filter(pk=unit).first()
            qs = qs.filter(Q(org_unit__path__startswith=base.path) | Q(issued_to_unit__path__startswith=base.path)) if base else qs.none()
        if p.get("in_custody") == "1":
            qs = qs.filter(custody__isnull=False, custody__returned_at__isnull=True)  # has an OPEN custody row (never-issued weapons have none)
        holder = uuid_param(request, "personnel")
        if holder:
            qs = qs.filter(custody__returned_at__isnull=True, custody__personnel_id=holder)
        page = self.paginate_queryset(qs.distinct().order_by("identifier"))
        cm = self._custody_map(page)
        record_read(request, "weapon.read_list", entity_type="weapon_register", org_unit=unit if unit else None, count=len(page))
        return self.get_paginated_response([_out(a, cm.get(a.pk)) for a in page])

    def retrieve(self, request, pk=None):
        a = self.get_object()
        record_read(request, "weapon.read_detail", entity_type="weapon", entity_id=a.pk, org_unit=svc.effective_unit(a))
        return Response(_out(a, svc.open_custody(a), detail=True))

    @action(detail=False, methods=["get"])
    def categories(self, request):
        rows = InventoryCategory.objects.filter(code__startswith=svc.PREFIX, kind="asset", approval_status="approved", active=True)
        return Response({"results": [{"id": str(c.pk), "code": c.code, "name_en": c.name_en, "name_so": c.name_so} for c in rows]})

    @action(detail=False, methods=["get"])
    def people(self, request):
        """Minimal lookup of serving personnel (name, service number, rank, unit) to issue a weapon to. It does not open any
        personnel record, so a weapons custodian needs no personnel permission."""
        q = scope.unit_scope_q(request.user, "weapons.manage", "org_unit__")
        unit = OrganizationalUnit.objects.filter(pk=_uid(request.query_params.get("org_unit"))).first() if _uid(request.query_params.get("org_unit")) else None
        if q is None or unit is None:
            return Response({"results": []})
        qs = Personnel.objects.filter(q, org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING).select_related("rank", "org_unit")
        term = (request.query_params.get("q") or "").strip()[:60]
        if term:
            qs = qs.filter(Q(full_name__icontains=term) | Q(service_number__icontains=term))
        return Response({"results": [{"id": str(x.pk), "full_name": x.full_name, "service_number": x.service_number,
                                      "rank": {"code": x.rank.code, "name_en": x.rank.name_en, "name_so": x.rank.name_so},
                                      "unit": _unit_brief(x.org_unit)} for x in qs.order_by("full_name")[:20]]})

    @action(detail=False, methods=["get"])
    def ammo_lines(self, request):
        """The ammunition stock lines a unit can issue rounds from (its own store and those above it), with the rounds in store."""
        q = scope.unit_scope_q(request.user, "weapons.manage", "org_unit__")
        uid = _uid(request.query_params.get("org_unit"))
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if q is None or unit is None:
            return Response({"results": []})
        # Rounds can only be issued from the store of the soldier's own unit or one above it (the unit's path starts with the store's).
        qs = StockLine.objects.filter(q, category__code__startswith="ammunition", category__approval_status="approved",
                                      category__active=True).select_related("category", "org_unit")
        lines = [l for l in qs.order_by("category__code", "-org_unit__path") if unit.path.startswith(l.org_unit.path)]
        return Response({"results": [{"id": str(l.pk), "quantity": l.quantity, "uom": l.uom,
                                      "category": {"code": l.category.code, "name_en": l.category.name_en, "name_so": l.category.name_so},
                                      "unit": _unit_brief(l.org_unit)} for l in lines[:50]]})

    @action(detail=False, methods=["post"])
    def rounds(self, request):
        """Issue rounds to a soldier from the store, take unused rounds back, or write off expended or lost rounds."""
        d = json_body(request)
        pid, lid = _uid(d.get("personnel")), _uid(d.get("stock_line"))
        q = scope.unit_scope_q(request.user, "weapons.manage", "org_unit__")
        person = Personnel.objects.filter(q, pk=pid).select_related("rank", "org_unit").first() if (q is not None and pid) else None
        if person is None:
            raise field_error("personnel", "out_of_scope", "That person is outside your scope.")
        line = StockLine.objects.filter(pk=lid).select_related("category", "org_unit").first() if lid else None
        if line is None:
            raise field_error("stock_line", "out_of_scope", "That ammunition line was not found.")
        qty = d.get("quantity")
        row = rnd.post(request, person, line, str(d.get("kind") or ""), qty if isinstance(qty, int) else 0,
                       d.get("reference") or "", d.get("authority_ref") or "", d.get("note") or "")
        return Response({"id": str(row.pk), "kind": row.kind, "delta": row.delta,
                         "held": rnd.held(person.pk, line.pk), "store_balance": StockLine.objects.get(pk=line.pk).quantity}, status=201)

    @action(detail=False, methods=["get"])
    def holdings(self, request):
        """Superior's report: for every soldier in the unit and below, the weapons held (serials) and the rounds held per
        ammunition type with what was issued, returned, expended and lost. Derived from the custody and rounds ledgers."""
        q = scope.unit_scope_q(request.user, "weapons.view", "org_unit__")
        uid = _uid(request.query_params.get("org_unit"))
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if q is None:
            return Response({"results": [], "totals": {"soldiers": 0, "weapons": 0, "rounds": 0}})
        people = Personnel.objects.filter(q)
        if unit is not None:
            people = people.filter(org_unit__path__startswith=unit.path)
        pid = _uid(request.query_params.get("personnel"))
        if pid:
            people = people.filter(pk=pid)
        term = (request.query_params.get("q") or "").strip()[:60]
        if term:
            people = people.filter(Q(full_name__icontains=term) | Q(service_number__icontains=term))
        pk_list = list(people.values_list("pk", flat=True)[:5000])
        rows = {}

        def entry(p):
            return rows.setdefault(p.pk, {"personnel": {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                                                        "status": p.status, "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so},
                                                        "unit": _unit_brief(p.org_unit)},
                                          "weapons": [], "rounds": {}})
        visible = self.get_queryset().values("pk")
        for c in (WeaponCustody.objects.filter(returned_at__isnull=True, personnel_id__in=pk_list, asset__in=visible)
                  .select_related("asset__weapon", "asset__category", "personnel__rank", "personnel__org_unit")):
            w = c.asset.weapon
            entry(c.personnel)["weapons"].append({"id": str(c.asset_id), "serial": c.asset.identifier, "weapon_type": w.weapon_type,
                                                  "caliber": w.caliber, "condition": w.condition, "issued_at": c.issued_at,
                                                  "category": {"code": c.asset.category.code, "name_en": c.asset.category.name_en,
                                                               "name_so": c.asset.category.name_so}})
        ledger = (SoldierRounds.objects.filter(personnel_id__in=pk_list)
                  .values("personnel_id", "stock_line__category__code", "stock_line__category__name_en", "stock_line__category__name_so",
                          "stock_line_id", "kind").annotate(s=Sum("delta")))
        by_person = {}
        for r in ledger:
            by_person.setdefault(r["personnel_id"], {}).setdefault(r["stock_line_id"], {"r": r, "k": {}})["k"][r["kind"]] = r["s"]
        if by_person:
            for p in Personnel.objects.filter(pk__in=by_person.keys()).select_related("rank", "org_unit"):
                e = entry(p)
                for lid, v in by_person[p.pk].items():
                    k, r = v["k"], v["r"]
                    e["rounds"][str(lid)] = {"stock_line": str(lid),
                                             "category": {"code": r["stock_line__category__code"], "name_en": r["stock_line__category__name_en"],
                                                          "name_so": r["stock_line__category__name_so"]},
                                             "issued": k.get("issue", 0), "returned": -k.get("return", 0),
                                             "expended": -k.get("expended", 0), "lost": -k.get("lost", 0),
                                             "held": sum(k.values())}
        show_all = request.query_params.get("all") == "1"  # also list serving soldiers who hold nothing yet (to issue them rounds)
        if show_all:
            for p in people.exclude(status__in=NOT_SERVING).select_related("rank", "org_unit").order_by("full_name")[:500]:
                entry(p)
        results = []
        for e in rows.values():
            lines = sorted(e["rounds"].values(), key=lambda x: x["category"]["code"])
            e["rounds"] = {"total": sum(x["held"] for x in lines), "lines": lines}
            if show_all or e["weapons"] or e["rounds"]["total"] or any(x["issued"] for x in lines):
                e["weapons"].sort(key=lambda x: x["serial"])
                results.append(e)
        results.sort(key=lambda e: (e["personnel"]["unit"]["code"] if e["personnel"]["unit"] else "", e["personnel"]["full_name"]))
        totals = {"soldiers": len(results), "weapons": sum(len(e["weapons"]) for e in results),
                  "rounds": sum(e["rounds"]["total"] for e in results)}
        record_read(request, "weapon.read_holdings", entity_type="weapon_register", org_unit=unit, count=len(results))
        return Response({"results": results[:500], "totals": totals, "truncated": len(results) > 500})

    @action(detail=False, methods=["get"])
    def rounds_history(self, request):
        """One soldier's complete issue, return, expenditure and loss history, with the running balance per ammunition type."""
        q = scope.unit_scope_q(request.user, "weapons.view", "org_unit__")
        pid = _uid(request.query_params.get("personnel"))
        person = Personnel.objects.filter(q, pk=pid).select_related("rank", "org_unit").first() if (q is not None and pid) else None
        if person is None:
            raise field_error("personnel", "out_of_scope", "That person is outside your scope.")
        lid = _uid(request.query_params.get("stock_line"))
        line = StockLine.objects.filter(pk=lid).first() if lid else None
        rows, balances = rnd.history(person, line)
        record_read(request, "weapon.read_rounds_history", entity_type="personnel", entity_id=person.pk, org_unit=person.org_unit, count=len(rows))
        return Response({"results": rows, "held": sum(balances.values())})

    @action(detail=False, methods=["get"])
    def disposition(self, request):
        """Accountability of ammunition. Without stock_line: the unit's ammunition lines with the rounds in store and the rounds held
        by soldiers, side by side. With stock_line (and from/to): the reconciliation of what was issued against what was returned,
        expended, lost and is still held, checked against the unit ledger, per soldier."""
        lid = _uid(request.query_params.get("stock_line"))
        if not lid:
            q = scope.unit_scope_q(request.user, "weapons.view", "org_unit__")
            if q is None:
                return Response({"results": []})
            lines = list(StockLine.objects.filter(q, category__code__startswith="ammunition").select_related("category", "org_unit")
                         .order_by("org_unit__path", "category__code")[:200])
            held = {i: n for i, n in SoldierRounds.objects.filter(stock_line__in=lines).values_list("stock_line_id").annotate(n=Sum("delta"))}
            record_read(request, "weapon.read_disposition", entity_type="stock_line", count=len(lines))
            return Response({"results": [{"id": str(l.pk), "category": {"code": l.category.code, "name_en": l.category.name_en, "name_so": l.category.name_so},
                                          "unit": _unit_brief(l.org_unit), "in_store": l.quantity, "held_by_soldiers": held.get(l.pk, 0)} for l in lines]})
        line = StockLine.objects.filter(pk=lid, category__code__startswith="ammunition").select_related("category", "org_unit").first()
        if line is None or not scope.can(request.user, "weapons.view", unit=line.org_unit):
            raise field_error("stock_line", "out_of_scope", "That ammunition line is outside your scope.")
        today = timezone.localdate()
        try:
            start = timezone.datetime.fromisoformat(request.query_params["from"]).date() if request.query_params.get("from") else today.replace(day=1)
            end = timezone.datetime.fromisoformat(request.query_params["to"]).date() if request.query_params.get("to") else today
        except ValueError:
            raise field_error("from", "invalid_date", "Use a date like 2026-03-01.")
        if end < start:
            raise field_error("to", "period_invalid", "The end must not be before the start.")
        record_read(request, "weapon.read_disposition", entity_type="stock_line", entity_id=line.pk, org_unit=line.org_unit)
        return Response({"line": {"id": str(line.pk), "category": {"code": line.category.code, "name_en": line.category.name_en, "name_so": line.category.name_so},
                                  "unit": _unit_brief(line.org_unit), "uom": line.uom},
                         **rnd.disposition(line, start, end)})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts derived from the register for a unit and below: nothing is stored or typed in."""
        qs = self.get_queryset()
        unit = OrganizationalUnit.objects.filter(pk=_uid(request.query_params.get("org_unit"))).first() if _uid(request.query_params.get("org_unit")) else None
        if unit is not None:
            qs = qs.filter(Q(org_unit__path__startswith=unit.path) | Q(issued_to_unit__path__startswith=unit.path))
        ids = list(qs.values_list("pk", flat=True))
        record_read(request, "weapon.read_summary", entity_type="weapon_register", org_unit=unit, count=len(ids))
        open_c = WeaponCustody.objects.filter(asset_id__in=ids, returned_at__isnull=True)
        return Response({
            "total": len(ids),
            "by_status": dict(qs.values_list("status").annotate(n=Count("pk"))),
            "by_type": dict(qs.values_list("weapon__weapon_type").annotate(n=Count("pk"))),
            "by_condition": dict(qs.values_list("weapon__condition").annotate(n=Count("pk"))),
            "in_custody": open_c.count(),
            "held_by_non_serving": open_c.filter(personnel__status__in=NOT_SERVING).count(),
        })

    def create(self, request):
        d = json_body(request)
        cat = InventoryCategory.objects.filter(pk=_uid(d.get("category"))).first() if _uid(d.get("category")) else None
        unit = OrganizationalUnit.objects.filter(pk=_uid(d.get("org_unit"))).first() if _uid(d.get("org_unit")) else None
        if cat is None:
            raise field_error("category", "not_a_weapon_category")
        if unit is None:
            raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
        asset = svc.register(request, cat, unit, str(d.get("serial") or ""), d)
        asset = Asset.objects.select_related("category", "org_unit", "issued_to_unit", "weapon").get(pk=asset.pk)
        return Response(_out(asset), status=201)

    def _person(self, request):
        pid = _uid(json_body(request).get("personnel"))
        person = Personnel.objects.select_related("org_unit", "rank").filter(pk=pid).first() if pid else None
        if person is None:
            raise field_error("personnel", "person_unknown")
        return person

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        a = self.get_object()
        d = json_body(request)
        person = self._person(request)
        if not scope.can(request.user, "weapons.manage", unit=person.org_unit):
            raise field_error("personnel", "person_unknown")  # outside the officer's reach reads like an unknown person
        updated = svc.issue(request, a, person, d.get("condition") or "", d.get("authority_ref") or "", d.get("note") or "", require_version(d))
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(_out(updated, svc.open_custody(updated), detail=True))

    @action(detail=True, methods=["post"], url_path="return")
    def give_back(self, request, pk=None):
        a = self.get_object()
        d = json_body(request)
        updated = svc.give_back(request, a, d.get("condition") or "", d.get("note") or "", require_version(d))
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(_out(updated, svc.open_custody(updated), detail=True))

    @action(detail=True, methods=["post"])
    def condition(self, request, pk=None):
        a = self.get_object()
        d = json_body(request)
        svc.set_condition(request, a, d.get("condition") or "", d.get("note") or "")
        a = self.get_queryset().get(pk=a.pk)
        return Response(_out(a, svc.open_custody(a), detail=True))
