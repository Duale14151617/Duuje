"""Payments (Sahal / bank), arrears, suspended/jailed review and policy endpoints. Every action is mapped to an explicit permission;
read access never grants edit, approval, export or payment execution, and recipient details are masked unless `payment.details`."""
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.personnel.models import Personnel

from . import payments as pay
from . import review
from . import services as svc
from .models import ArrearsClaim, PaymentInstruction, PolicySetting, SalaryProfile, StatusPayDecision, SurvivorCase
from .views import _404, _date, _get, _valid

PAY_VIEW = ("payroll.view", "payment.prepare", "payment.authorize", "payment.execute", "payment.reconcile")


def _inst_out(i):
    return {"id": str(i.pk), "kind": i.kind, "line": str(i.line_id) if i.line_id else None, "claim": str(i.claim_id) if i.claim_id else None,
            "allocation": str(i.allocation_id) if i.allocation_id else None, "personnel": str(i.personnel_id),
            "beneficiary": str(i.beneficiary_id) if i.beneficiary_id else None, "period": f"{i.period_year}-{i.period_month:02d}",
            "method": i.method, "recipient_name": i.recipient_name, "recipient_display": i.recipient_display,
            "amount": str(i.amount), "currency": i.currency, "transaction_reference": i.transaction_reference,
            "status": i.status, "failure_reason": i.failure_reason, "note": i.note, "retry_of": str(i.retry_of_id) if i.retry_of_id else None,
            "paid_on": i.paid_on.isoformat() if i.paid_on else None, "reconciliation_status": i.recon_status,
            "statement_ref": i.statement_ref, "statement_amount": str(i.statement_amount) if i.statement_amount is not None else None,
            "statement_date": i.statement_date.isoformat() if i.statement_date else None, "reconciliation_note": i.recon_note,
            "prepared_by": i.prepared_by_username, "authorized_by": i.authorized_by_username, "authorized_at": i.authorized_at,
            "executed_by": i.executed_by_username, "executed_at": i.executed_at, "reconciled_by": i.reconciled_by_username,
            "reconciled_at": i.reconciled_at, "created_at": i.created_at, "version": i.version}


def _inst_detail(i):
    out = _inst_out(i)
    out["events"] = [{"action": e.action, "from": e.from_status, "to": e.to_status, "actor": e.actor_username, "comment": e.comment,
                      "at": e.created_at} for e in i.events.all()]
    return out


class PaymentViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": (PAY_VIEW, "global"), "retrieve": (PAY_VIEW, "global"), "methods": (PAY_VIEW, "global"),
        "create": ("payment.prepare", "global"), "authorize": ("payment.authorize", "global"),
        "cancel": (("payment.prepare", "payment.authorize"), "global"),
        "process": ("payment.execute", "global"), "mark_pending": ("payment.execute", "global"), "fail": ("payment.execute", "global"),
        "complete": ("payment.execute", "global"), "reconcile": ("payment.reconcile", "global"), "reveal": ("payment.details", "global"),
    }

    def _i(self, pk):
        return _404(_get(PaymentInstruction, pk))

    @action(detail=False, methods=["get"])
    def methods(self, request):
        return Response({"methods": [{"code": c, "label": m["label"], "recipient_fields": m["recipient_fields"], "integration": m["integration"]}
                                     for c, m in pay.METHODS.items()], "integration_note": pay.INTEGRATION_NOTE})

    def list(self, request):
        qs = PaymentInstruction.objects.all()
        q = request.query_params
        for key, field in (("status", "status"), ("method", "method"), ("kind", "kind"), ("reconciliation", "recon_status")):
            if q.get(key):
                qs = qs.filter(**{field: q[key]})
        if q.get("personnel"):
            qs = qs.filter(personnel_id=q["personnel"]) if _valid(q["personnel"]) else qs.none()
        rows = list(qs[:200])
        record_read(request, "payment.read_list", entity_type="payment", count=len(rows))
        return Response({"results": [_inst_out(i) for i in rows]})

    def retrieve(self, request, pk=None):
        i = self._i(pk)
        record_read(request, "payment.read_detail", entity_type="payment", entity_id=i.pk)
        return Response(_inst_detail(i))

    @transaction.atomic
    def create(self, request):
        return Response(_inst_out(pay.prepare_payment(request.user, json_body(request))), status=201)

    @action(detail=True, methods=["post"])
    def authorize(self, request, pk=None):
        return Response(_inst_out(pay.authorize_payment(request.user, self._i(pk))))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(_inst_out(pay.cancel_payment(request.user, self._i(pk), str(json_body(request).get("comment") or ""))))

    @action(detail=True, methods=["post"])
    def process(self, request, pk=None):
        return Response(_inst_out(pay.begin_processing(request.user, self._i(pk))))

    @action(detail=True, methods=["post"], url_path="pending")
    def mark_pending(self, request, pk=None):
        return Response(_inst_out(pay.mark_pending(request.user, self._i(pk), str(json_body(request).get("comment") or ""))))

    @action(detail=True, methods=["post"])
    def fail(self, request, pk=None):
        return Response(_inst_out(pay.fail_payment(request.user, self._i(pk), str(json_body(request).get("reason") or ""))))

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        d = json_body(request)
        i = self._i(pk)
        return Response(_inst_out(pay.complete_payment(request.user, i.pk, d.get("transaction_reference"), _date(d.get("paid_on"), "paid_on"))))

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        d = json_body(request)
        i = self._i(pk)
        return Response(_inst_out(pay.reconcile_payment(request.user, i.pk, d.get("statement_ref"), d.get("statement_amount"),
                                                        _date(d.get("statement_date"), "statement_date"), str(d.get("note") or ""))))

    @action(detail=True, methods=["get"])
    def reveal(self, request, pk=None):
        i = self._i(pk)
        return Response({"id": str(i.pk), "method": i.method, "recipient": pay.reveal_details(request, i)})


# ------------------------------------------------------------------ arrears

def _claim_out(c):
    paid = review.arrears_paid(c)
    return {"id": str(c.pk), "personnel": str(c.personnel_id), "periods": c.periods, "source_lines": c.source_lines, "amount": str(c.amount),
            "currency": c.currency, "evidence_ref": c.evidence_ref, "note": c.note, "status": c.status, "paid": str(paid),
            "outstanding": str(c.amount - paid) if c.status == "approved" else None, "recorded_by": c.recorded_by_username,
            "verified_by": c.verified_by_username, "approved_by": c.approved_by_username, "decision_note": c.decision_note,
            "kept_separate_from": ["payroll_runs", "survivor_benefits"]}


class ArrearsViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": (("payroll.view", "arrears.manage", "arrears.approve"), "global"),
                      "create": ("arrears.manage", "global"), "verify": ("arrears.manage", "global"),
                      "approve": ("arrears.approve", "global")}

    def list(self, request):
        qs = ArrearsClaim.objects.all()
        if request.query_params.get("personnel"):
            pid = request.query_params["personnel"]
            qs = qs.filter(personnel_id=pid) if _valid(pid) else qs.none()
        rows = list(qs[:200])
        record_read(request, "arrears.read_list", entity_type="arrears_claim", count=len(rows))
        return Response({"results": [_claim_out(c) for c in rows]})

    @transaction.atomic
    def create(self, request):
        d = json_body(request)
        person = _404(_get(Personnel, d.get("personnel")))
        return Response(_claim_out(review.record_arrears(request.user, person, d)), status=201)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        d = json_body(request)
        c = _404(_get(ArrearsClaim, pk))
        return Response(_claim_out(review.verify_arrears(request.user, c, bool(d.get("verify", True)), str(d.get("comment") or ""))))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        d = json_body(request)
        c = _404(_get(ArrearsClaim, pk))
        return Response(_claim_out(review.approve_arrears(request.user, c, bool(d.get("approve", True)), str(d.get("comment") or ""))))


# ------------------------------------------------------------------ personnel payroll view, suspended/jailed review

def _decision_out(d):
    return {"id": str(d.pk), "personnel": str(d.personnel_id), "status_at_decision": d.status_at_decision, "kind": d.kind,
            "decision_text": d.decision_text, "deduction_percent": d.deduction_percent, "reason": d.reason, "effective_date": d.effective_date.isoformat(),
            "supporting_ref": d.supporting_ref, "state": d.state, "recorded_by": d.recorded_by_username, "recorded_at": d.recorded_at,
            "decided_by": d.decided_by_username, "decided_at": d.decided_at, "decision_note": d.decision_note,
            "automatic_effect_on_pay": "deduction_percent applies to payroll lines only once approved by a second officer"}


class PayrollPersonnelViewSet(viewsets.ViewSet):
    """list = the review queue (suspended and jailed personnel). retrieve = one person's payroll picture, linked to the personnel record."""

    permission_classes = [ScopedPermission]
    permission_map = {"list": ("payroll.view", "global"), "retrieve": ("payroll.view", "global"),
                      "decisions": ("payroll.review", "global"), "decide": ("payroll.decide", "global")}

    def list(self, request):
        rows = list(review.flagged_people()[:300])
        record_read(request, "payroll.read_review_queue", entity_type="personnel", count=len(rows))
        out = []
        for p in rows:
            d = review.latest_decision(p)
            out.append({"personnel": str(p.pk), "service_number": p.service_number, "full_name": p.full_name, "status": p.status,
                        "org_unit": str(p.org_unit_id), "flag": review.FLAG_TEXT, "salary_treatment": "existing treatment retained",
                        "latest_decision": _decision_out(d) if d else None, "needs_decision": d is None or d.state != "approved"})
        return Response({"results": out})

    def retrieve(self, request, pk=None):
        p = _404(_get(Personnel, pk))
        record_read(request, "payroll.read_personnel", entity_type="personnel", entity_id=p.pk)
        profile = svc.profile_in_force(p, timezone.localdate())
        lines = p.payroll_lines.select_related("period").order_by("-period__year", "-period__month")[:36]
        return Response({
            "personnel": str(p.pk), "service_number": p.service_number, "full_name": p.full_name, "status": p.status,
            "flag": review.FLAG_TEXT if p.status in review.FLAGGED else "",
            "salary_profile": {"base_amount": str(profile.base_amount), "currency": profile.currency,
                               "effective_from": profile.effective_from.isoformat()} if profile else None,
            "lines": [{"id": str(l.pk), "period": f"{l.period.year}-{l.period.month:02d}", "kind": l.kind, "calculated_net": str(l.calculated_net),
                       "approved_net": str(l.approved_net) if l.approved_net is not None else None, "paid": str(svc.paid_total(l)),
                       "status_flag": l.status_flag, "death_month": l.death_month} for l in lines],
            "unpaid_approved_lines": [{"line": str(l.pk), "period": f"{l.period.year}-{l.period.month:02d}", "outstanding": str(due)}
                                      for l, due in review.unpaid_approved_lines(p)],
            "arrears_claims": [_claim_out(c) for c in p.arrears_claims.all()],
            "survivor_cases": [{"id": str(c.pk), "status": c.status} for c in SurvivorCase.objects.filter(personnel=p)],
            "pay_decisions": [_decision_out(d) for d in p.pay_decisions.all()],
        })

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def decisions(self, request, pk=None):
        p = _404(_get(Personnel, pk))
        return Response(_decision_out(review.record_status_decision(request.user, p, json_body(request))), status=201)

    @action(detail=True, methods=["post"], url_path="decisions/(?P<did>[^/.]+)/decide")
    @transaction.atomic
    def decide(self, request, pk=None, did=None):
        p = _404(_get(Personnel, pk))
        dec = _404(_get(StatusPayDecision, did, personnel=p))
        d = json_body(request)
        return Response(_decision_out(review.decide_status_decision(request.user, dec, bool(d.get("approve")), str(d.get("comment") or ""))))


# ------------------------------------------------------------------ policy

class PolicyViewSet(viewsets.ViewSet):
    """Every rule is listed. Values can be revised later by the policy authority (authority reference and reason required, audited)."""

    permission_classes = [ScopedPermission]
    permission_map = {"list": ("payroll.view", "global"), "confirm": ("payroll.policy_confirm", "global"),
                      "revise": ("payroll.policy_confirm", "global")}

    def list(self, request):
        return Response({"results": [{"key": p.key, "title": p.title, "description": p.description, "status": p.status, "value": p.value,
                                      "authority_ref": p.authority_ref, "confirmed_by": p.confirmed_by_username, "confirmed_at": p.confirmed_at}
                                     for p in PolicySetting.objects.all()]})

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        d = json_body(request)
        p = review.confirm_policy(request.user, pk, d.get("value"), d.get("authority_ref"))
        return Response({"key": p.key, "status": p.status, "value": p.value, "authority_ref": p.authority_ref,
                         "note": "Recorded. A confirmed value does not change system behaviour until the rule is implemented."})

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        d = json_body(request)
        p = review.revise_policy(request.user, pk, d.get("value"), d.get("authority_ref"), d.get("reason"))
        return Response({"key": p.key, "status": p.status, "value": p.value, "authority_ref": p.authority_ref,
                         "note": "Recorded. New payroll lines use the new value; lines already prepared are not rewritten."})
