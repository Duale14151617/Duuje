"""Promotion eligibility by rank and time in rank. The list is advisory; a proposal only creates rank-change requests in the
normal approval queue (Police order, super administrator decision), it never changes a rank itself."""
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record as audit
from apps.audit.services import record_read
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.organization import change_requests
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING
from apps.ranks.models import Rank

from . import services
from .models import PromotionRule

MAX_PEOPLE = 1000
MAX_PROPOSE = 100
RETIRED_FROM = services.RETIRED_FROM
months_between = services.months_between  # kept importable from here


def _uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _rank_out(r):
    return {"id": str(r.pk), "code": r.code, "name_en": r.name_en, "name_so": r.name_so}


class PromotionViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"eligibility": ("promotion.view", "any"), "rules": ("promotion.view", "any"), "set_rule": ("promotion.configure", "any"),
                      "propose": ("changes.propose", "global")}
    queryset = PromotionRule.objects.none()

    @action(detail=False, methods=["get"])
    def eligibility(self, request):
        """?org_unit=<id>[&state=eligible]: serving people in the unit and below, with time in rank against the rule for their rank."""
        uid = uuid_param(request, "org_unit")
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if unit is None or not scope.can(request.user, "promotion.view", unit=unit):
            raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
        q = scope.unit_scope_q(request.user, "promotion.view", "org_unit__")
        people = list(Personnel.objects.filter(q, org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING)
                      .select_related("rank", "org_unit").order_by("-rank__sort_order", "full_name").distinct()[:MAX_PEOPLE])
        today, wanted = timezone.localdate(), request.query_params.get("state")
        rows, counts = [], {k: 0 for k in services.STATES}
        for e in services.evaluate(people, today):
            p, nxt = e["person"], e["next_rank"]
            counts[e["state"]] += 1
            if wanted and wanted != e["state"]:
                continue
            rows.append({"personnel": {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number, "status": p.status},
                         "unit": {"code": p.org_unit.code, "name_en": p.org_unit.name_en, "name_so": p.org_unit.name_so},
                         "rank": _rank_out(p.rank), "next_rank": _rank_out(nxt) if nxt else None,
                         "rank_since": e["rank_since"].isoformat(), "since_source": e["since_source"], "months": e["months"],
                         "required": e["required"], "months_left": e["months_left"], "state": e["state"]})
        record_read(request, "promotion.read", entity_type="promotion", org_unit=unit, count=len(rows))
        return Response({"org_unit": str(unit.pk), "counts": counts, "results": rows})

    @action(detail=False, methods=["get"])
    def rules(self, request):
        rules = {r.rank_id: r for r in PromotionRule.objects.select_related("next_rank")}
        ranks = Rank.objects.filter(active=True, sort_order__lt=RETIRED_FROM).order_by("branch__code", "sort_order")
        return Response({"results": [{**_rank_out(r), "sort_order": r.sort_order,
                                      "rule": None if r.pk not in rules else {
                                          "min_months": rules[r.pk].min_months, "active": rules[r.pk].active,
                                          "next_rank": _rank_out(rules[r.pk].next_rank) if rules[r.pk].next_rank_id else None}}
                                     for r in ranks]})

    @action(detail=False, methods=["post"], url_path="rules/set")
    def set_rule(self, request):
        """{rank, min_months, next_rank?, active?} sets the rule for a rank; {rank, remove: true} deletes it. Super administrator only."""
        if not scope.can(request.user, "promotion.configure"):
            return Response({"code": "permission_denied", "detail": "Not allowed."}, status=403)
        d = json_body(request)
        rank = Rank.objects.filter(pk=_uid(d.get("rank")), active=True).first() if _uid(d.get("rank")) else None
        if rank is None:
            raise field_error("rank", "rank_not_found", "Unknown rank.")
        if d.get("remove"):
            PromotionRule.objects.filter(rank=rank).delete()
            audit("promotion.rule_removed", request=request, entity_type="promotion", entity_id=rank.pk, metadata={"rank": rank.code})
            return Response(status=204)
        months = d.get("min_months")
        if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= 600:
            raise field_error("min_months", "months_invalid", "Enter a whole number of months from 1 to 600.")
        nxt = None
        if d.get("next_rank"):
            nxt = Rank.objects.filter(pk=_uid(d["next_rank"]), active=True, branch_id=rank.branch_id).first() if _uid(d["next_rank"]) else None
            if nxt is None or nxt.sort_order <= rank.sort_order:
                raise field_error("next_rank", "next_rank_invalid", "Choose a more senior rank of the same service.")
        rule, _ = PromotionRule.objects.update_or_create(rank=rank, defaults={
            "min_months": months, "next_rank": nxt, "active": bool(d.get("active", True)), "updated_by_username": request.user.username})
        audit("promotion.rule_set", request=request, entity_type="promotion", entity_id=rank.pk,
              metadata={"rank": rank.code, "months": months, "active": rule.active})
        return Response({"rank": rank.code, "min_months": rule.min_months, "active": rule.active}, status=201)

    @action(detail=False, methods=["post"])
    def propose(self, request):
        """{items: [{personnel}], order_ref, issuing_officer, order_date, effective_date?}. Turns eligible people into rank-change
        requests in the normal approval queue, each carrying the Police order that authorizes it. Eligibility is worked out again
        here, so a proposal cannot be made for someone the list would not show as eligible. All rows are checked first: if any
        is wrong nothing is created. As everywhere in the queue, a super administrator's own proposal is applied at once."""
        d = json_body(request)
        items = d.get("items")
        if not isinstance(items, list) or not items or len(items) > MAX_PROPOSE:
            raise field_error("items", "items_invalid", "Choose between 1 and 100 people.")
        day = d.get("effective_date") or timezone.localdate().isoformat()
        errors, created = [], []
        with transaction.atomic():
            seen = set()
            for i, item in enumerate(items):
                pid = _uid(item.get("personnel")) if isinstance(item, dict) else None
                person = Personnel.objects.select_related("rank", "org_unit").filter(pk=pid).first() if pid else None
                if person is None or not scope.can(request.user, "promotion.view", unit=person.org_unit):
                    errors.append({"index": i, "code": "personnel_not_found"})
                    continue
                if pid in seen:
                    errors.append({"index": i, "code": "duplicate_entry"})
                    continue
                seen.add(pid)
                e = services.evaluate([person])[0]
                if e["state"] != "eligible":
                    errors.append({"index": i, "code": "not_eligible", "state": e["state"]})
                    continue
                payload = {"personnel": pid, "rank": str(e["next_rank"].pk), "effective_date": day,
                           "reason": f"Promotion: {e['months']} months in rank (minimum {e['required']})"}
                try:
                    created.append(change_requests.propose(request.user, request, kind="rank_change", payload=payload,
                                                           order_ref=d.get("order_ref"), issuing_officer=d.get("issuing_officer"),
                                                           order_date=d.get("order_date")))
                except (ValidationError, APIException) as exc:
                    detail = change_requests._flat(exc.detail)
                    errors.append({"index": i, "code": detail[0]["code"] if detail else "invalid", "field": detail[0]["field"] if detail else ""})
            if errors:
                transaction.set_rollback(True)
            else:
                audit("promotion.propose", request=request, entity_type="promotion", metadata={"count": len(created)})
        if errors:
            return Response({"code": "promotion_invalid", "detail": "Fix the listed people; nothing was created.", "rows": errors}, status=400)
        return Response({"count": len(created), "results": [{"personnel": r.payload["personnel"], "request": str(r.pk), "status": r.status,
                                                              "self_approved": r.self_approved, "summary": r.summary} for r in created]}, status=201)
