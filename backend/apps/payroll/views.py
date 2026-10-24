"""Payroll and survivor-benefit API. Every action is gated by ScopedPermission (permission_map) and the rules in services.py.
Payroll is headquarters-level ('global' grants). Money fields are decimals as strings; nothing sensitive goes into audit metadata."""
from datetime import date

from django.db import transaction
from django.db.models import Count, Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record_read
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.personnel.models import Personnel

from . import payments as pay_svc
from . import review
from . import services as svc
from .models import (AllocationDecision, ArrearsClaim, BenefitAllocation, Beneficiary, PayrollLine, PayrollRun, PaymentInstruction,
                     PolicySetting, SalaryProfile, SalaryScale, StatusPayDecision, SurvivorCase)


def _get(model, pk, **kw):
    """First row with this id (a model class or a ready queryset); None for a malformed or unknown id."""
    if not _valid(pk):
        return None
    qs = model if hasattr(model, "filter") and not hasattr(model, "objects") else model.objects.all()
    return qs.filter(pk=pk, **kw).first()


def _404(obj):
    if obj is None:
        from rest_framework.exceptions import NotFound
        raise NotFound()
    return obj


def _date(value, name):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(name, "invalid_date")


def _profile_out(p):
    return {"id": str(p.pk), "personnel": str(p.personnel_id), "personnel_name": p.personnel.full_name,
            "service_number": p.personnel.service_number, "scale": str(p.scale_id) if p.scale_id else None,
            "base_amount": str(p.base_amount), "currency": p.currency, "components": p.components,
            "effective_from": p.effective_from.isoformat(), "authority_ref": p.authority_ref, "status": p.status,
            "created_by": p.created_by_username, "created_at": p.created_at, "decided_by": p.decided_by_username,
            "decided_at": p.decided_at, "decision_note": p.decision_note}


def _line_out(l):
    paid = svc.paid_total(l)
    return {"id": str(l.pk), "personnel": str(l.personnel_id), "service_number": l.service_number, "kind": l.kind,
            "adjusts": str(l.adjusts_id) if l.adjusts_id else None, "reason": l.reason, "currency": l.currency,
            "base": str(l.base), "allowances": str(l.allowances), "deductions": str(l.deductions), "gross": str(l.gross),
            "calculated_net": str(l.calculated_net), "approved_net": str(l.approved_net) if l.approved_net is not None else None,
            "paid": str(paid), "status_flag": l.status_flag, "death_month": l.death_month,
            "status_flag_note": review.FLAG_TEXT if l.status_flag else ""}


def _run_out(r, lines=False):
    out = {"id": str(r.pk), "year": r.period.year, "month": r.period.month, "kind": r.kind, "status": r.status,
           "prepared_by": r.prepared_by_username, "exceptions": r.exceptions, "version": r.version,
           "actions": [{"action": a.action, "from": a.from_status, "to": a.to_status, "actor": a.actor_username,
                        "comment": a.comment, "at": a.created_at} for a in r.actions.all()]}
    if lines:
        out["lines"] = [_line_out(l) for l in r.lines.all()]
    return out


class SalaryProfileViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("payroll.view", "global"), "create": ("payroll.manage", "global"),
                      "approve": ("payroll.approve", "global"), "reject": ("payroll.approve", "global"),
                      "scales": ("payroll.view", "global"), "people": ("payroll.manage", "global")}

    def list(self, request):
        qs = SalaryProfile.objects.all()
        pid = request.query_params.get("personnel")
        if pid:
            qs = qs.filter(personnel_id=pid) if _valid(pid) else qs.none()
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        rows = list(qs.select_related("personnel")[:200])
        record_read(request, "payroll.read_profiles", entity_type="salary_profile", count=len(rows))
        return Response({"results": [_profile_out(p) for p in rows]})

    @action(detail=False, methods=["get"])
    def scales(self, request):
        return Response({"results": [{"id": str(s.pk), "code": s.code, "name": s.name, "base_amount": str(s.base_amount),
                                      "currency": s.currency} for s in SalaryScale.objects.filter(active=True)]})

    @action(detail=False, methods=["get"])
    def people(self, request):
        """Find a living member to propose a salary profile for. Payroll staff hold no personnel access, so this returns only
        name, service number and status, and only for a search of two or more characters."""
        term = (request.query_params.get("q") or "").strip()[:60]
        if len(term) < 2:
            return Response({"results": []})
        from django.db.models import Q
        rows = list(Personnel.objects.filter(Q(full_name__icontains=term) | Q(service_number__icontains=term))
                    .exclude(status__in=("died", "retired", "discharged")).order_by("full_name")[:20])
        record_read(request, "payroll.read_people_lookup", entity_type="personnel", count=len(rows))
        return Response({"results": [{"id": str(x.pk), "full_name": x.full_name, "service_number": x.service_number, "status": x.status} for x in rows]})

    @transaction.atomic
    def create(self, request):
        d = json_body(request)
        person = _404(_get(Personnel, d.get("personnel")))
        return Response(_profile_out(svc.create_profile(request.user, person, d)), status=201)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        p = _404(_get(SalaryProfile.objects.select_for_update(), pk))
        return Response(_profile_out(svc.decide_profile(request.user, p, True, str(json_body(request).get("comment") or ""))))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reject(self, request, pk=None):
        p = _404(_get(SalaryProfile.objects.select_for_update(), pk))
        return Response(_profile_out(svc.decide_profile(request.user, p, False, str(json_body(request).get("comment") or ""))))


def _valid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


class PayrollRunViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("payroll.view", "global"), "retrieve": ("payroll.view", "global"), "prepare": ("payroll.manage", "global"),
        "submit": ("payroll.manage", "global"), "cancel": ("payroll.manage", "global"), "return_run": ("payroll.approve", "global"),
        "approve": ("payroll.approve", "global"), "adjust": ("payroll.manage", "global"),
        "summary": ("payroll.view", "global"),
    }

    def list(self, request):
        return Response({"results": [_run_out(r) for r in PayrollRun.objects.select_related("period")[:60]]})

    def retrieve(self, request, pk=None):
        r = _404(_get(PayrollRun.objects.select_related("period"), pk))
        record_read(request, "payroll.read_run", entity_type="payroll_run", entity_id=r.pk, count=r.lines.count())
        return Response(_run_out(r, lines=True))

    @action(detail=False, methods=["post"])
    def prepare(self, request):
        d = json_body(request)
        run = svc.prepare_run(request.user, d.get("year"), d.get("month"))
        return Response(_run_out(run, lines=True), status=201)

    def _run(self, pk):
        return _404(_get(PayrollRun.objects.select_related("period"), pk))

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return Response(_run_out(svc.submit_run(request.user, self._run(pk))))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(_run_out(svc.cancel_run(request.user, self._run(pk), str(json_body(request).get("comment") or ""))))

    @action(detail=True, methods=["post"], url_path="return")
    def return_run(self, request, pk=None):
        return Response(_run_out(svc.return_run(request.user, self._run(pk), str(json_body(request).get("comment") or ""))))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(_run_out(svc.approve_run(request.user, self._run(pk))))

    @action(detail=False, methods=["post"])
    def adjust(self, request):
        d = json_body(request)
        if not _valid(d.get("line")):
            raise field_error("line", "unknown_line")
        line = svc.adjust_line(request.user, d["line"], d.get("kind"), d.get("amount"), str(d.get("reason") or ""))
        return Response(_line_out(line), status=201)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(payroll_summary())


def payroll_summary():
    """Dashboard figures calculated from the underlying records (counts and totals only, no individual salaries)."""
    runs = PayrollRun.objects.exclude(status="cancelled")
    by_status = dict(runs.values_list("status").annotate(n=Count("pk")))
    serving = Personnel.objects.exclude(status__in=("retired", "discharged", "died"))
    with_profile = serving.filter(salary_profiles__status="approved").distinct().count()
    return {"runs_by_status": by_status, "awaiting_approval": by_status.get("submitted", 0),
            "profiles_pending": SalaryProfile.objects.filter(status="pending").count(),
            "serving_total": serving.count(), "serving_with_approved_profile": with_profile,
            "serving_missing_profile": serving.count() - with_profile,
            "survivor_cases": dict(SurvivorCase.objects.exclude(status="closed").values_list("status").annotate(n=Count("pk"))),
            "beneficiaries_awaiting_verification": Beneficiary.objects.filter(state="pending", case__status__in=("open", "verified")).count(),
            "allocations_awaiting_authorization": BenefitAllocation.objects.filter(status="proposed").count(),
            "payments_by_status": dict(PaymentInstruction.objects.values_list("status").annotate(n=Count("pk"))),
            "payments_unreconciled": PaymentInstruction.objects.filter(status="paid", recon_status="unreconciled").count(),
            "payments_with_discrepancy": PaymentInstruction.objects.filter(recon_status="discrepancy").count(),
            "flagged_suspended_or_jailed": review.flagged_people().count(),
            "arrears_awaiting_decision": ArrearsClaim.objects.filter(status__in=("recorded", "verified")).count(),
            "pay_decisions_awaiting_approval": StatusPayDecision.objects.filter(state="recorded").count(),
            "policy_items_unconfirmed": PolicySetting.objects.filter(status="unconfirmed").count()}


# ------------------------------------------------------------------ survivor benefits

def _b_out(b, reveal=False):
    out = {"id": str(b.pk), "full_name": b.full_name, "relationship": b.relationship, "tier": b.tier, "state": b.state,
           "identity_ref": b.identity_ref, "evidence_ref": b.evidence_ref, "decided_by": b.decided_by_username,
           "decision_note": b.decision_note, "has_payment_details": bool(b.payment_details_enc),
           "allocations": [{"id": str(a.pk), "amount": str(a.amount), "currency": a.currency, "status": a.status,
                            "basis_ref": a.basis_ref, "authorized_by": a.authorized_by_username, "basis_kind": a.basis_kind,
                            "effective_from": a.effective_from.isoformat() if a.effective_from else None,
                            "held_from": a.held_from.isoformat() if a.held_from else None,
                            "ended_on": a.ended_on.isoformat() if a.ended_on else None,  # only ever set by an approved decision
                            "paid_total": str(a.payments.aggregate(t=Sum("amount"))["t"] or 0),
                            "decisions": [_decision_out(x) for x in a.decisions.all()]} for a in b.allocations.all()]}
    return out


def _decision_out(d):
    return {"id": str(d.pk), "allocation": str(d.allocation_id), "kind": d.kind, "state": d.state, "reason": d.reason,
            "effective_date": d.effective_date.isoformat(), "supporting_ref": d.supporting_ref,
            "previous_amount": str(d.previous_amount) if d.previous_amount is not None else None,
            "new_amount": str(d.new_amount) if d.new_amount is not None else None,
            "proposed_by": d.proposed_by_username, "decided_by": d.decided_by_username, "decision_note": d.decision_note}


def _case_out(c):
    return {"id": str(c.pk), "personnel": str(c.personnel_id), "personnel_name": c.personnel.full_name,
            "service_number": c.personnel.service_number, "date_of_death": c.death_record.date_of_death.isoformat(),
            "status": c.status, "outstanding_review": c.outstanding_review, "dispute_note": c.dispute_note,
            "opened_by": c.opened_by_username, "verified_by": c.verified_by_username, "version": c.version,
            "closure_reason": c.closure_reason, "closure_effective_date": c.closure_effective_date.isoformat() if c.closure_effective_date else None,
            "closure_ref": c.closure_ref, "duration": "indefinite",
            "eligible_tier": svc.eligible_tier(c), "beneficiaries": [_b_out(b) for b in c.beneficiaries.all()]}


class SurvivorCaseViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("survivor.view", "global"), "retrieve": ("survivor.view", "global"), "create": ("survivor.manage", "global"),
        "beneficiary": ("survivor.manage", "global"), "decide_beneficiary": ("survivor.verify", "global"),
        "verify": ("survivor.verify", "global"), "dispute": ("survivor.manage", "global"), "propose": ("survivor.manage", "global"),
        "authorize": ("survivor.approve", "global"), "close": ("survivor.approve", "global"),
        "deceased": ("survivor.manage", "global"), "update_beneficiary": ("survivor.manage", "global"), "propose_decision": ("survivor.manage", "global"),
        "decide_decision": ("survivor.approve", "global"),
    }

    def _case(self, pk):
        return _404(_get(SurvivorCase.objects.select_related("personnel", "death_record"), pk))

    def list(self, request):
        rows = list(SurvivorCase.objects.select_related("personnel", "death_record")[:100])
        record_read(request, "survivor.read_list", entity_type="survivor_case", count=len(rows))
        return Response({"results": [_case_out(c) for c in rows]})

    def retrieve(self, request, pk=None):
        c = self._case(pk)
        record_read(request, "survivor.read_case", entity_type="survivor_case", entity_id=c.pk)
        return Response(_case_out(c))

    @action(detail=False, methods=["get"])
    def deceased(self, request):
        """Members whose death is confirmed and who have no open survivor case: the people a case can be opened for.
        Survivor staff hold no personnel access, so this gives them name, service number and date of death only."""
        from apps.personnel.models import DeathRecord
        open_ids = SurvivorCase.objects.exclude(status="closed").values("personnel_id")
        rows = (DeathRecord.objects.filter(state=DeathRecord.State.CONFIRMED, personnel__status=Personnel.Status.DIED)
                .exclude(personnel_id__in=open_ids).select_related("personnel").order_by("-date_of_death")[:100])
        record_read(request, "survivor.read_deceased", entity_type="survivor_case", count=len(rows))
        return Response({"results": [{"personnel": str(r.personnel_id), "full_name": r.personnel.full_name,
                                      "service_number": r.personnel.service_number, "date_of_death": r.date_of_death.isoformat()} for r in rows]})

    @transaction.atomic
    def create(self, request):
        person = _404(_get(Personnel, json_body(request).get("personnel")))
        return Response(_case_out(svc.open_case(request.user, person)), status=201)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def beneficiary(self, request, pk=None):
        b = svc.add_beneficiary(request.user, self._case(pk), json_body(request))
        return Response(_b_out(b), status=201)

    @action(detail=True, methods=["post"], url_path="beneficiary/(?P<bid>[^/.]+)/decide")
    @transaction.atomic
    def decide_beneficiary(self, request, pk=None, bid=None):
        c = self._case(pk)
        b = _404(_get(Beneficiary, bid, case=c))
        d = json_body(request)
        return Response(_b_out(svc.decide_beneficiary(request.user, b, bool(d.get("verify")), str(d.get("comment") or ""))))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def verify(self, request, pk=None):
        c = self._case(pk)
        return Response(_case_out(svc.mark_verified(request.user, c, str(json_body(request).get("outstanding_review") or ""))))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def dispute(self, request, pk=None):
        d = json_body(request)
        return Response(_case_out(svc.set_dispute(request.user, self._case(pk), bool(d.get("disputed", True)), str(d.get("comment") or ""))))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def propose(self, request, pk=None):
        c = self._case(pk)
        d = json_body(request)
        b = _404(_get(Beneficiary, d.get("beneficiary"), case=c)) if _valid(d.get("beneficiary")) else _404(None)
        a = svc.propose_allocation(request.user, b, d)
        return Response({"id": str(a.pk), "status": a.status, "amount": str(a.amount)}, status=201)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def authorize(self, request, pk=None):
        c = self._case(pk)
        d = json_body(request)
        a = _404(_get(BenefitAllocation.objects.select_related("beneficiary__case"), d.get("allocation"), beneficiary__case=c)) \
            if _valid(d.get("allocation")) else _404(None)
        a = svc.authorize_allocation(request.user, a)
        return Response({"id": str(a.pk), "status": a.status})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def close(self, request, pk=None):
        d = json_body(request)
        return Response(_case_out(svc.close_case(request.user, self._case(pk), d.get("reason"), d.get("effective_date"), d.get("supporting_ref"))))

    @action(detail=True, methods=["post"], url_path="beneficiary/(?P<bid>[^/.]+)/update")
    @transaction.atomic
    def update_beneficiary(self, request, pk=None, bid=None):
        c = self._case(pk)
        b = _404(_get(Beneficiary, bid, case=c))
        return Response(_b_out(svc.update_beneficiary(request.user, b, json_body(request))))

    @action(detail=True, methods=["post"], url_path="decision")
    @transaction.atomic
    def propose_decision(self, request, pk=None):
        c = self._case(pk)
        d = json_body(request)
        a = _404(_get(BenefitAllocation.objects.select_for_update().select_related("beneficiary__case"), d.get("allocation"), beneficiary__case=c)) \
            if _valid(d.get("allocation")) else _404(None)
        return Response(_decision_out(svc.propose_allocation_decision(request.user, a, d)), status=201)

    @action(detail=True, methods=["post"], url_path="decision/(?P<did>[^/.]+)/decide")
    @transaction.atomic
    def decide_decision(self, request, pk=None, did=None):
        c = self._case(pk)
        dec = _404(_get(AllocationDecision, did, allocation__beneficiary__case=c))
        d = json_body(request)
        return Response(_decision_out(svc.decide_allocation_decision(request.user, dec, bool(d.get("approve")), str(d.get("comment") or ""))))
