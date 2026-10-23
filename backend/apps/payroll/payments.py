"""Payment workflow for Sahal mobile money and bank transfer.

IMPORTANT: no Sahal or bank API is integrated. Nothing here moves money. An authorised officer sends the payment outside the
system and records the result; a different officer reconciles it against the provider or bank statement. Duties are separated:
prepare -> authorise (a different person) -> execute and record the outcome (not the authoriser) -> reconcile (not the executor).
Recipient details are encrypted at rest, shown masked, and revealed only to holders of `payment.details` (every reveal is audited)."""
import json
import re
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import record
from apps.core import crypto

from . import services as svc
from .models import (ArrearsClaim, ArrearsPayment, BenefitAllocation, Beneficiary, PayrollLine, PaymentEvent, PaymentInstruction)

METHODS = {
    "sahal": {"label": "Sahal mobile money", "recipient_fields": ["mobile_number"], "integration": "none"},
    "bank_transfer": {"label": "Bank transfer", "recipient_fields": ["bank_name", "account_number"], "integration": "none"},
}
INTEGRATION_NOTE = ("No direct integration with Sahal or any bank exists. Payments are made outside the system by an authorised "
                    "officer; this module records them, controls the approvals and reconciles them.")
ZERO = Decimal("0.00")
I = PaymentInstruction


def clean_recipient(method, data):
    """Validate the recipient for a method. Returns (details_dict, masked_display)."""
    if method not in METHODS:
        raise svc.rule("invalid_method", "method")
    if not isinstance(data, dict):
        raise svc.rule("recipient_required", "recipient")
    if method == "sahal":
        number = re.sub(r"[\s\-()]", "", str(data.get("mobile_number") or ""))
        number = number[1:] if number.startswith("+") else number
        if not number.isdigit() or not 7 <= len(number) <= 15:
            raise svc.rule("invalid_mobile_number", "recipient")
        return {"mobile_number": number}, f"Sahal ••••{number[-4:]}"
    bank = str(data.get("bank_name") or "").strip()[:100]
    acct = re.sub(r"[\s\-]", "", str(data.get("account_number") or ""))
    if not bank:
        raise svc.rule("bank_name_required", "recipient")
    if not acct.isalnum() or not 4 <= len(acct) <= 34:
        raise svc.rule("invalid_account_number", "recipient")
    return {"bank_name": bank, "account_number": acct}, f"{bank} ••••{acct[-4:]}"


def _event(inst, user, action, frm, to, comment=""):
    PaymentEvent.objects.create(instruction=inst, action=action, from_status=frm, to_status=to, actor_id=user.pk,
                                actor_username=user.username, comment=(comment or "")[:500])


def inflight(**target):
    return I.objects.filter(status__in=I.OPEN, **target).aggregate(t=Sum("amount"))["t"] or ZERO


def _beneficiary_for_deceased(person, ben_id):
    """The month-of-death salary and arrears of a deceased soldier are paid only to a VERIFIED beneficiary of his survivor case
    (official recipient rule: pending policy confirmation, see policy setting `deceased_salary_recipient`)."""
    b = Beneficiary.objects.select_related("case").filter(pk=ben_id).first() if svc_valid(ben_id) else None
    if b is None or b.case.personnel_id != person.pk or b.state != "verified":
        raise svc.rule("verified_beneficiary_required", "beneficiary")
    if b.case.status in ("disputed", "closed") or svc.eligible_tier(b.case) != b.tier:
        raise svc.rule("beneficiary_not_eligible", "beneficiary")
    return b


def svc_valid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _resolve_target(data):
    """Return (kind, target, person, beneficiary, (year, month), cap_remaining, currency, locked objects). Raises 400/409."""
    kind = data.get("kind")
    ben_id = data.get("beneficiary")
    if kind == "salary":
        line = PayrollLine.objects.select_for_update().select_related("run", "period", "personnel").filter(pk=data.get("line")).first() \
            if svc_valid(data.get("line")) else None
        if line is None:
            raise svc.rule("unknown_line", "line")
        if line.run.status not in ("approved", "paid") or line.approved_net is None or line.approved_net <= 0:
            raise svc.InvalidState()
        person, ben = line.personnel, None
        if person.status == "died":
            if not svc.deceased_payable_line(line):
                raise svc.rule("deceased_use_arrears_workflow", "line")  # earlier salary of a deceased soldier is arrears
            ben = _beneficiary_for_deceased(person, ben_id)
        remaining = line.approved_net - svc.paid_total(line) - inflight(line=line)
        return kind, {"line": line}, person, ben, (line.period.year, line.period.month), remaining, line.currency
    if kind == "arrears":
        claim = ArrearsClaim.objects.select_for_update().select_related("personnel").filter(pk=data.get("claim")).first() \
            if svc_valid(data.get("claim")) else None
        if claim is None:
            raise svc.rule("unknown_claim", "claim")
        if claim.status != "approved":
            raise svc.InvalidState()
        person, ben = claim.personnel, None
        if person.status == "died":
            ben = _beneficiary_for_deceased(person, ben_id)
        paid = claim.payments.aggregate(t=Sum("amount"))["t"] or ZERO
        last = max(claim.periods) if claim.periods else None
        ym = (int(last[:4]), int(last[5:7])) if last else (timezone.localdate().year, timezone.localdate().month)
        return kind, {"claim": claim}, person, ben, ym, claim.amount - paid - inflight(claim=claim), claim.currency
    if kind == "survivor":
        a = BenefitAllocation.objects.select_for_update().select_related("beneficiary__case__personnel").filter(pk=data.get("allocation")).first() \
            if svc_valid(data.get("allocation")) else None
        if a is None:
            raise svc.rule("unknown_allocation", "allocation")
        case = a.beneficiary.case
        if a.status != "authorized" or case.status != "verified":
            raise svc.InvalidState()  # suspended / terminated / disputed / closed
        if svc.eligible_tier(case) != a.beneficiary.tier:
            raise svc.rule("beneficiary_not_eligible", "allocation")
        try:
            year, month = int(data.get("period_year")), int(data.get("period_month"))
            if not (2000 <= year <= 2100 and 1 <= month <= 12):
                raise ValueError
        except (TypeError, ValueError):
            if a.basis_kind == "per_period":
                raise svc.rule("period_required", "period")
            today = timezone.localdate()
            year, month = today.year, today.month
        if a.basis_kind == "per_period":
            err = svc.allocation_period_error(a, year, month)
            if err:
                raise svc.rule(err, "period")
        in_flight = (inflight(allocation=a, period_year=year, period_month=month) if a.basis_kind == "per_period" else inflight(allocation=a))
        remaining = a.amount - svc.allocation_paid_for(a, year, month) - in_flight
        return kind, {"allocation": a}, case.personnel, a.beneficiary, (year, month), remaining, a.currency
    raise svc.rule("invalid_kind", "kind")


@transaction.atomic
def prepare_payment(user, data):
    kind, target, person, ben, (year, month), remaining, currency = _resolve_target(data)
    method = data.get("method")
    details, display = clean_recipient(method, data.get("recipient"))
    amount = svc.money(data.get("amount"), "amount")
    if amount == 0:
        raise svc.rule("invalid_amount", "amount")
    if amount > remaining:
        raise svc.rule("exceeds_remaining_amount", "amount")  # approved/authorised amount, minus paid and already in flight
    name = str(data.get("recipient_name") or "").strip()[:150] or (ben.full_name if ben else person.full_name)
    if ben is not None and kind != "survivor" and not name:
        name = ben.full_name
    retry_of = None
    if data.get("retry_of"):
        retry_of = I.objects.filter(pk=data["retry_of"], status="failed").first() if svc_valid(data["retry_of"]) else None
        if retry_of is None:
            raise svc.rule("retry_requires_failed_payment", "retry_of")
    inst = I.objects.create(kind=kind, personnel=person, beneficiary=ben, period_year=year, period_month=month, method=method,
                            recipient_name=name, recipient_display=display, recipient_details_enc=crypto.encrypt(json.dumps(details)),
                            amount=amount, currency=currency, note=str(data.get("note") or "")[:300], retry_of=retry_of,
                            prepared_by_id=user.pk, prepared_by_username=user.username, **target)
    _event(inst, user, "prepare", "", "prepared")
    record("payment.prepare", actor=user, entity_type="payment", entity_id=inst.pk,
           metadata={"kind": kind, "method": method, "period": f"{year}-{month:02d}"})  # no recipient details, no amounts of persons
    return inst


def _locked(inst_id):
    return I.objects.select_for_update().get(pk=inst_id)


def _still_valid(inst):
    """Re-check at every later step: a dispute, suspension, termination, closure or death-rule change stops the payment."""
    if inst.kind == "survivor":
        a = BenefitAllocation.objects.select_related("beneficiary__case").get(pk=inst.allocation_id)
        if a.status != "authorized" or a.beneficiary.case.status != "verified":
            raise svc.InvalidState()
        if a.basis_kind == "per_period" and svc.allocation_period_error(a, inst.period_year, inst.period_month):
            raise svc.InvalidState()
    elif inst.kind == "arrears":
        if ArrearsClaim.objects.get(pk=inst.claim_id).status != "approved":
            raise svc.InvalidState()
    if inst.beneficiary_id and inst.kind != "survivor":
        b = Beneficiary.objects.select_related("case").get(pk=inst.beneficiary_id)
        if b.state != "verified" or b.case.status in ("disputed", "closed"):
            raise svc.InvalidState()


class _Denied(ValidationError):
    """A refusal that must be audited. The audit row is written AFTER the transaction rolls back, otherwise the rollback
    that undoes the refused move would also erase the record of who tried it."""

    def __init__(self, error, audit_action, inst_id, reason):
        super().__init__(error.detail)
        self.audit_action, self.inst_id, self.reason = audit_action, inst_id, reason


def _move(user, inst_id, action, allowed, to, comment="", extra=None, check=None):
    try:
        with transaction.atomic():
            inst = _locked(inst_id)
            if inst.status not in allowed:
                raise svc.InvalidState()
            if check:
                check(inst)
            old = inst.status
            I.objects.filter(pk=inst.pk).update(status=to, version=inst.version + 1, updated_at=timezone.now(), **(extra or {}))
            _event(inst, user, action, old, to, comment)
            record(f"payment.{action}", actor=user, entity_type="payment", entity_id=inst.pk, metadata={"from": old, "to": to})
    except _Denied as d:
        record(d.audit_action, actor=user, outcome="denied", entity_type="payment", entity_id=d.inst_id, metadata={"reason": d.reason})
        raise
    inst.refresh_from_db()
    return inst


def authorize_payment(user, inst):
    def check(i):
        if i.prepared_by_id == user.pk:
            raise _Denied(svc.rule("authorizer_must_differ", "status"), "payment.authorize", i.pk, "self_authorization")
        _still_valid(i)
    return _move(user, inst.pk, "authorize", {"prepared"}, "authorized", extra={"authorized_by_id": user.pk,
                 "authorized_by_username": user.username, "authorized_at": timezone.now()}, check=check)


def cancel_payment(user, inst, comment):
    if not str(comment or "").strip():
        raise svc.rule("comment_required", "comment")
    return _move(user, inst.pk, "cancel", {"prepared", "authorized"}, "cancelled", comment, extra={"failure_reason": comment[:300]})


def begin_processing(user, inst):
    """The executing officer starts the EXTERNAL payment (Sahal app/agent or bank). Cannot be the person who authorised it."""
    def check(i):
        if i.authorized_by_id == user.pk:
            raise _Denied(svc.rule("executor_must_differ", "status"), "payment.process", i.pk, "authorizer_cannot_execute")
        _still_valid(i)
    return _move(user, inst.pk, "process", {"authorized"}, "processing", extra={"executed_by_id": user.pk,
                 "executed_by_username": user.username, "executed_at": timezone.now()}, check=check)


def mark_pending(user, inst, comment=""):
    return _move(user, inst.pk, "pending", {"processing"}, "pending", comment)


def fail_payment(user, inst, reason):
    if not str(reason or "").strip():
        raise svc.rule("comment_required", "reason")
    return _move(user, inst.pk, "fail", {"processing", "pending"}, "failed", reason, extra={"failure_reason": reason[:300]})


@transaction.atomic
def complete_payment(user, inst_id, reference, paid_on):
    """Record that the external payment succeeded. A transaction reference and date are mandatory; the money is then posted to
    the matching ledger (salary, arrears or survivor), which re-checks every cap. The reference cannot be reused for a method."""
    inst = _locked(inst_id)
    if inst.status not in ("processing", "pending"):
        raise svc.InvalidState()
    if inst.executed_by_id not in (None, user.pk):
        raise svc.rule("only_executor_can_complete", "status")
    reference = str(reference or "").strip()[:80]
    if not reference:
        raise svc.rule("reference_required", "transaction_reference")
    if paid_on > timezone.localdate():
        raise svc.rule("future_date", "paid_on")
    if I.objects.filter(method=inst.method, transaction_reference=reference, status="paid").exclude(pk=inst.pk).exists():
        raise svc.rule("reference_already_used", "transaction_reference")
    _still_valid(inst)
    if inst.kind == "salary":
        line = PayrollLine.objects.select_for_update().select_related("run", "period", "personnel").get(pk=inst.line_id)
        svc.ledger_salary_payment(user, line, inst.amount, paid_on, reference, instruction=inst)
    elif inst.kind == "arrears":
        claim = ArrearsClaim.objects.select_for_update().get(pk=inst.claim_id)
        if (claim.payments.aggregate(t=Sum("amount"))["t"] or ZERO) + inst.amount > claim.amount:
            raise svc.rule("exceeds_approved_amount", "amount")
        ArrearsPayment.objects.create(claim=claim, amount=inst.amount, reference=reference, paid_on=paid_on, paid_by_id=user.pk,
                                      paid_by_username=user.username, instruction=inst)
        record("arrears.pay", actor=user, entity_type="arrears_claim", entity_id=claim.pk, metadata={"reference": reference})
    else:
        a = BenefitAllocation.objects.select_for_update().select_related("beneficiary__case").get(pk=inst.allocation_id)
        svc.ledger_survivor_payment(user, a, inst.amount, paid_on, reference, inst.period_year, inst.period_month, instruction=inst)
    old = inst.status
    I.objects.filter(pk=inst.pk).update(status="paid", transaction_reference=reference, paid_on=paid_on, version=inst.version + 1,
                                        updated_at=timezone.now())
    _event(inst, user, "complete", old, "paid", f"reference {reference}")
    record("payment.complete", actor=user, entity_type="payment", entity_id=inst.pk, metadata={"from": old, "to": "paid", "reference": reference})
    inst.refresh_from_db()
    return inst


@transaction.atomic
def reconcile_payment(user, inst_id, statement_ref, statement_amount, statement_date, note=""):
    """Compare a PAID instruction with the provider/bank statement. A match marks it reconciled; any difference is recorded as a
    discrepancy for follow-up. The reconciler cannot be the person who executed it."""
    inst = _locked(inst_id)
    if inst.status != "paid" or inst.recon_status == "reconciled":
        raise svc.InvalidState()
    if inst.executed_by_id == user.pk:
        record("payment.reconcile", actor=user, outcome="denied", entity_type="payment", entity_id=inst.pk, metadata={"reason": "executor_cannot_reconcile"})
        raise svc.rule("reconciler_must_differ", "status")
    sref = str(statement_ref or "").strip()[:80]
    if not sref:
        raise svc.rule("statement_ref_required", "statement_ref")
    amt = svc.money(statement_amount, "statement_amount")
    matches = amt == inst.amount and sref == inst.transaction_reference
    if not matches and not str(note or "").strip():
        raise svc.rule("comment_required", "note")  # a mismatch must be explained
    to = "reconciled" if matches else "discrepancy"
    I.objects.filter(pk=inst.pk).update(recon_status=to, statement_ref=sref, statement_amount=amt, statement_date=statement_date,
                                        recon_note=str(note or "")[:300], reconciled_by_id=user.pk, reconciled_by_username=user.username,
                                        reconciled_at=timezone.now(), version=inst.version + 1, updated_at=timezone.now())
    _event(inst, user, "reconcile", inst.recon_status, to, note)
    record("payment.reconcile", actor=user, entity_type="payment", entity_id=inst.pk, metadata={"result": to})
    inst.refresh_from_db()
    return inst


def reveal_details(request, inst):
    """Decrypted recipient details. Only for `payment.details` holders; every reveal is audited with who and which payment."""
    record("payment.reveal_details", request=request, entity_type="payment", entity_id=inst.pk)
    return json.loads(crypto.decrypt(inst.recipient_details_enc))


# ---- cancelling instructions that a documented decision has made invalid

def _cancel_open(user, qs, why):
    for inst in qs.filter(status__in=("prepared", "authorized", "processing", "pending")):
        old = inst.status
        if old in ("processing", "pending"):
            # money may already have been sent outside the system: it is failed for a person to follow up, never silently dropped
            to = "failed"
        else:
            to = "cancelled"
        I.objects.filter(pk=inst.pk).update(status=to, failure_reason=why[:300], version=inst.version + 1, updated_at=timezone.now())
        _event(inst, user, "auto_" + ("fail" if to == "failed" else "cancel"), old, to, why)
        record("payment.cancel_by_decision", actor=user, entity_type="payment", entity_id=inst.pk, metadata={"from": old, "to": to})


def cancel_open_for_allocation(user, allocation_id, why):
    _cancel_open(user, I.objects.filter(allocation_id=allocation_id), why)


def cancel_open_for_case(user, case_id, why):
    _cancel_open(user, I.objects.filter(allocation__beneficiary__case_id=case_id), why)
