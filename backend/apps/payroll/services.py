"""Payroll and survivor-benefit rules. The server decides who may do what, in which state, with what amounts; nothing about
identity, status or money is taken on trust from the client. Callers wrap mutating calls in transaction.atomic()."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.audit.services import record
from apps.core import crypto
from apps.core.errors import field_error
from apps.personnel.models import DeathRecord, Personnel
from apps.personnel.services import NOT_SERVING

from . import breakglass as bg
from .models import (AllocationDecision, ArrearsClaim, BenefitAllocation, Beneficiary, BeneficiaryChange, PaymentTransaction,
                     PayrollAction, PayrollLine, PayrollPeriod, PayrollRun, SalaryProfile, SalaryScale, StatusPayDecision,
                     SurvivorCase, SurvivorPayment)

ZERO = Decimal("0.00")
MAX_AMOUNT = Decimal("999999999999.99")


class InvalidState(APIException):
    status_code = 409
    default_detail = "That action is not allowed in the current state."
    default_code = "invalid_state"


def rule(code, field="non_field_errors"):
    return field_error(field, code)


def money(value, field):
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise rule("invalid_amount", field)
    if not d.is_finite() or d < 0 or d > MAX_AMOUNT:
        raise rule("invalid_amount", field)
    return d


def _actor(user):
    return {"id": user.pk, "username": user.username}


# ------------------------------------------------------------------ salary profiles

def clean_components(items):
    if items in (None, ""):
        return []
    if not isinstance(items, list) or len(items) > 30:
        raise rule("invalid_components", "components")
    out = []
    for c in items:
        if not isinstance(c, dict) or c.get("kind") not in ("allowance", "deduction") or not str(c.get("name") or "").strip():
            raise rule("invalid_components", "components")
        out.append({"kind": c["kind"], "name": str(c["name"]).strip()[:80], "amount": str(money(c.get("amount"), "components"))})
    return out


def create_profile(user, person, data):
    """A proposed salary position. Amounts come from an authorized scale or are typed against a document reference; they do
    not take effect until a DIFFERENT officer approves them."""
    if person.status == Personnel.Status.DIED:
        raise rule("person_deceased", "personnel")
    ref = str(data.get("authority_ref") or "").strip()[:200]
    if not ref:
        raise rule("authority_ref_required", "authority_ref")
    try:
        eff = date.fromisoformat(str(data.get("effective_from")))
    except ValueError:
        raise rule("invalid_date", "effective_from")
    scale = None
    if data.get("scale"):
        scale = SalaryScale.objects.filter(pk=data["scale"], active=True).first()
        if scale is None:
            raise rule("unknown_scale", "scale")
        base, currency = scale.base_amount, scale.currency
    else:
        base = money(data.get("base_amount"), "base_amount")
        currency = str(data.get("currency") or "").upper()
        if len(currency) != 3 or not currency.isalpha():
            raise rule("invalid_currency", "currency")
    if SalaryProfile.objects.filter(personnel=person, effective_from=eff).exclude(status="rejected").exists():
        raise rule("profile_exists_for_date", "effective_from")
    p = SalaryProfile.objects.create(
        personnel=person, scale=scale, base_amount=base, currency=currency, components=clean_components(data.get("components")),
        effective_from=eff, authority_ref=ref, created_by_id=user.pk, created_by_username=user.username)
    record("salary_profile.create", actor=user, entity_type="salary_profile", entity_id=p.pk, metadata={"personnel": str(person.pk)})
    return p


def decide_profile(user, profile, approve, note=""):
    if profile.status != SalaryProfile.Status.PENDING:
        raise InvalidState()
    if profile.created_by_id == user.pk and not bg.bypass(user, "profile_approver", "salary_profile", profile.pk):
        record("salary_profile.decide", actor=user, outcome="denied", entity_type="salary_profile", entity_id=profile.pk,
               metadata={"reason": "self_approval"})
        raise rule("approver_must_differ", "status")
    if not approve and not note.strip():
        raise rule("comment_required", "comment")
    SalaryProfile.objects.filter(pk=profile.pk).update(
        status="approved" if approve else "rejected", decided_by_id=user.pk, decided_by_username=user.username,
        decided_at=timezone.now(), decision_note=note[:300])
    record("salary_profile.approve" if approve else "salary_profile.reject", actor=user, entity_type="salary_profile",
           entity_id=profile.pk, metadata={"personnel": str(profile.personnel_id)})
    profile.refresh_from_db()
    return profile


def profile_in_force(person, on):
    return (SalaryProfile.objects.filter(personnel=person, status="approved", effective_from__lte=on)
            .order_by("-effective_from").first())


def _period_end(period):
    nxt = date(period.year + (period.month == 12), period.month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


# ------------------------------------------------------------------ payroll runs

def _confirmed_death(person):
    return DeathRecord.objects.filter(personnel=person, state=DeathRecord.State.CONFIRMED).first()


def death_month_of(person):
    """(year, month) of a CONFIRMED death, else None. The month of death is paid in full: it is a calendar month, never prorated."""
    rec = _confirmed_death(person)
    return (rec.date_of_death.year, rec.date_of_death.month) if rec else None


def _period_start(period):
    return date(period.year, period.month, 1)


def calculate(profile):
    allowances = sum((Decimal(c["amount"]) for c in profile.components if c["kind"] == "allowance"), ZERO)
    deductions = sum((Decimal(c["amount"]) for c in profile.components if c["kind"] == "deduction"), ZERO)
    gross = profile.base_amount + allowances
    return allowances, deductions, gross, gross - deductions


def _add_exception(items, person, code, severity="excluded"):
    items.append({"personnel": str(person.pk), "service_number": person.service_number or "", "code": code, "severity": severity})


@transaction.atomic
def prepare_run(user, year, month):
    """Prepare (or re-prepare, while still only 'prepared') the regular run for a month. Picks eligible personnel with an
    approved salary profile, calculates, and records everything it had to leave out. Deceased personnel never get an ordinary
    line: their dues go through a survivor case."""
    if not (isinstance(year, int) and isinstance(month, int) and 2000 <= year <= 2100 and 1 <= month <= 12):
        raise rule("invalid_period", "period")
    period, _ = PayrollPeriod.objects.get_or_create(year=year, month=month)
    run = (PayrollRun.objects.select_for_update().filter(period=period, kind="regular").exclude(status="cancelled").first())
    if run is None:
        run = PayrollRun.objects.create(period=period, prepared_by_id=user.pk, prepared_by_username=user.username)
        PayrollAction.objects.create(run=run, action="prepare", from_status="", to_status="prepared", actor_id=user.pk,
                                     actor_username=user.username)
    elif run.status != PayrollRun.Status.PREPARED:
        raise InvalidState()  # a submitted/approved/paid run is final for this period; corrections use adjustments
    else:
        PayrollLine.objects.filter(run=run).delete()  # safe: nothing has been approved or paid on a 'prepared' run
    start, end = _period_start(period), _period_end(period)
    exceptions, lines = [], []
    deaths = {r.personnel_id: r.date_of_death for r in DeathRecord.objects.filter(state=DeathRecord.State.CONFIRMED)}
    for person in Personnel.objects.exclude(status__in=(Personnel.Status.RETIRED, Personnel.Status.DISCHARGED)).select_related("org_unit"):
        died_on = deaths.get(person.pk)
        death_month = False
        pay_on = end
        if person.status == Personnel.Status.DIED:
            if died_on is None:
                _add_exception(exceptions, person, "deceased_without_confirmed_death_record")
                continue
            if died_on < start:
                # died in an earlier month: no ordinary salary any more. Unpaid earlier salary is ARREARS (separate claim),
                # and survivor benefits run through the survivor case.
                _add_exception(exceptions, person, "deceased_use_survivor_workflow", severity="info")
                continue
            if died_on <= end:
                death_month = True  # the month of death: the FULL salary, never prorated
                pay_on = died_on
        profile = profile_in_force(person, pay_on)
        if profile is None:
            _add_exception(exceptions, person, "missing_salary_profile")
            continue
        allowances, deductions, gross, net = calculate(profile)
        if net < 0:
            _add_exception(exceptions, person, "invalid_calculation")
            continue
        flag = person.status if person.status in (Personnel.Status.SUSPENDED, Personnel.Status.JAILED) else ""
        if flag:
            # Paid, with the tier Finance decided (approved by a second officer) deducted from gross. With no approved tier the
            # line is calculated exactly as before and the case stays flagged for a decision.
            from .review import deduction_percent_for
            pct = deduction_percent_for(person, end)
            if pct:
                cut = (gross * Decimal(pct) / Decimal(100)).quantize(Decimal("0.01"))
                deductions, net = deductions + cut, net - cut
                if net < 0:
                    _add_exception(exceptions, person, "invalid_calculation")
                    continue
                _add_exception(exceptions, person, "status_deduction_%d_percent" % pct, severity="info")
            else:
                _add_exception(exceptions, person, "status_needs_decision", severity="warning")
        if death_month:
            _add_exception(exceptions, person, "death_month_full_salary", severity="info")
        lines.append(PayrollLine(run=run, period=period, personnel=person, profile=profile, currency=profile.currency,
                                 base=profile.base_amount, allowances=allowances, deductions=deductions, gross=gross,
                                 calculated_net=net, org_unit=person.org_unit, service_number=person.service_number or "",
                                 status_flag=flag, death_month=death_month))
    PayrollLine.objects.bulk_create(lines)
    PayrollRun.objects.filter(pk=run.pk).update(exceptions=exceptions, updated_at=timezone.now())
    record("payroll.prepare", actor=user, entity_type="payroll_run", entity_id=run.pk,
           metadata={"year": year, "month": month, "lines": len(lines), "exceptions": len(exceptions)})
    run.refresh_from_db()
    return run


def _transition(user, run, action, allowed_from, to, comment="", extra=None):
    with transaction.atomic():
        locked = PayrollRun.objects.select_for_update().get(pk=run.pk)
        if locked.status not in allowed_from:
            raise InvalidState()
        old = locked.status
        PayrollRun.objects.filter(pk=locked.pk).update(status=to, version=locked.version + 1, updated_at=timezone.now(), **(extra or {}))
        PayrollAction.objects.create(run=locked, action=action, from_status=old, to_status=to, actor_id=user.pk,
                                     actor_username=user.username, comment=comment[:500])
        record(f"payroll.{action}", actor=user, entity_type="payroll_run", entity_id=locked.pk, metadata={"from": old, "to": to})
    locked.refresh_from_db()
    return locked


def submit_run(user, run):
    if not run.lines.exists():
        raise rule("empty_run", "run")
    return _transition(user, run, "submit", {"prepared"}, "submitted")


def return_run(user, run, comment):
    if not comment.strip():
        raise rule("comment_required", "comment")
    return _transition(user, run, "return", {"submitted"}, "prepared", comment)


def approve_run(user, run):
    if run.prepared_by_id == user.pk and not bg.bypass(user, "run_approver", "payroll_run", run.pk):
        record("payroll.approve", actor=user, outcome="denied", entity_type="payroll_run", entity_id=run.pk, metadata={"reason": "self_approval"})
        raise rule("approver_must_differ", "status")
    with transaction.atomic():
        locked = PayrollRun.objects.select_for_update().get(pk=run.pk)
        if locked.status != "submitted":
            raise InvalidState()
        for line in locked.lines.select_related("personnel"):
            if line.kind == "regular" and line.personnel.status == Personnel.Status.DIED:
                dm = death_month_of(line.personnel)
                if dm is None or dm < (locked.period.year, locked.period.month):
                    # died BEFORE this period: re-prepare. A death in or after the period is fine (full month of death is paid).
                    raise rule("deceased_line_in_run", "run")
            PayrollLine.objects.filter(pk=line.pk).update(approved_net=line.calculated_net)
    return _transition(user, run, "approve", {"submitted"}, "approved")


def cancel_run(user, run, comment):
    return _transition(user, run, "cancel", {"prepared", "submitted"}, "cancelled", comment)


def paid_total(line):
    return line.transactions.aggregate(t=Sum("amount"))["t"] or ZERO


def deceased_payable_line(line):
    """A deceased soldier's approved line may be paid only for the month of death (full salary). Earlier unpaid salary is ARREARS."""
    dm = death_month_of(line.personnel)
    return dm is not None and dm == (line.period.year, line.period.month)


def ledger_salary_payment(user, line, amount, paid_on, reference, note="", instruction=None):
    """Post money actually paid to the salary ledger. Internal: called by the payment workflow with the line locked, so a
    payment always has a method, recipient, approvals and an audit trail behind it. Never exceeds the approved amount."""
    if line.run.status not in ("approved", "paid") or line.approved_net is None:
        raise InvalidState()
    if line.personnel.status == Personnel.Status.DIED and not deceased_payable_line(line):
        record("payroll.pay", actor=user, outcome="denied", entity_type="payroll_line", entity_id=line.pk, metadata={"reason": "person_deceased"})
        raise rule("deceased_use_arrears_workflow", "line")
    amt = money(amount, "amount")
    if amt == 0:
        raise rule("invalid_amount", "amount")
    if paid_on > timezone.localdate():
        raise rule("future_date", "paid_on")
    if paid_total(line) + amt > line.approved_net:
        raise rule("exceeds_approved_amount", "amount")
    tx = PaymentTransaction.objects.create(line=line, amount=amt, reference=(reference or "")[:80], paid_on=paid_on,
                                           paid_by_id=user.pk, paid_by_username=user.username, note=(note or "")[:300],
                                           instruction=instruction)
    run = line.run
    unpaid = [l for l in run.lines.all() if paid_total(l) < l.approved_net]
    if not unpaid and run.status == "approved":
        PayrollRun.objects.filter(pk=run.pk).update(status="paid", version=run.version + 1, updated_at=timezone.now())
        PayrollAction.objects.create(run=run, action="paid", from_status="approved", to_status="paid", actor_id=user.pk,
                                     actor_username=user.username)
    record("payroll.pay", actor=user, entity_type="payroll_line", entity_id=line.pk, metadata={"run": str(run.pk), "reference": tx.reference})
    return tx


@transaction.atomic
def adjust_line(user, original_id, kind, amount, reason):
    """Correction by new record: a reversal offsets an original line, an adjustment adds a signed delta. The original line
    and its transactions are untouched. Goes into an 'adjustment' run for the same period that is approved like any other."""
    orig = PayrollLine.objects.select_for_update().select_related("run", "period").filter(pk=original_id, kind="regular").first()
    if orig is None:
        raise rule("unknown_line", "line")
    if orig.run.status not in ("approved", "paid"):
        raise InvalidState()
    if not str(reason or "").strip():
        raise rule("comment_required", "reason")
    if kind == "reversal":
        if orig.corrections.filter(kind="reversal").exists():
            raise rule("already_reversed", "line")
        delta = -orig.calculated_net
    elif kind == "adjustment":
        try:
            delta = Decimal(str(amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            raise rule("invalid_amount", "amount")
        if delta == 0 or abs(delta) > MAX_AMOUNT:
            raise rule("invalid_amount", "amount")
    else:
        raise rule("invalid_kind", "kind")
    run = PayrollRun.objects.filter(period=orig.period, kind="adjustment", status="prepared").first()
    if run is None:
        run = PayrollRun.objects.create(period=orig.period, kind="adjustment", prepared_by_id=user.pk, prepared_by_username=user.username)
        PayrollAction.objects.create(run=run, action="prepare", to_status="prepared", actor_id=user.pk, actor_username=user.username)
    line = PayrollLine.objects.create(
        run=run, period=orig.period, personnel=orig.personnel, profile=orig.profile, kind=kind, adjusts=orig, reason=reason[:300],
        currency=orig.currency, calculated_net=delta, gross=delta, org_unit=orig.org_unit, service_number=orig.service_number)
    record(f"payroll.{kind}", actor=user, entity_type="payroll_line", entity_id=line.pk, metadata={"original": str(orig.pk)})
    return line


# ------------------------------------------------------------------ survivor benefits

@transaction.atomic
def open_case(user, person):
    rec = DeathRecord.objects.filter(personnel=person, state=DeathRecord.State.CONFIRMED).first()
    if rec is None or person.status != Personnel.Status.DIED:
        raise rule("death_not_confirmed", "personnel")  # no beneficiary workflow before authorised verification of the death
    if SurvivorCase.objects.filter(personnel=person).exclude(status="closed").exists():
        raise rule("case_already_open", "personnel")
    case = SurvivorCase.objects.create(personnel=person, death_record=rec, opened_by_id=user.pk, opened_by_username=user.username)
    record("survivor_case.open", actor=user, entity_type="survivor_case", entity_id=case.pk, metadata={"personnel": str(person.pk)})
    return case


def _live(case):
    if case.status == "closed":
        raise InvalidState()


def add_beneficiary(user, case, data):
    _live(case)
    rel = data.get("relationship")
    if rel not in Beneficiary.TIER:
        raise rule("invalid_relationship", "relationship")
    name, idref, evid = (str(data.get(k) or "").strip() for k in ("full_name", "identity_ref", "evidence_ref"))
    if not (name and idref and evid):
        raise rule("beneficiary_details_required", "full_name")
    higher_verified = [b for b in case.beneficiaries.filter(state="verified") if b.TIER[rel] > b.tier]
    if higher_verified:
        # A verified wife/child (or parent) already holds the higher priority: a lower class cannot be registered as eligible.
        raise rule("higher_priority_beneficiary_exists", "relationship")
    details = str(data.get("payment_details") or "").strip()[:300]
    b = Beneficiary.objects.create(case=case, full_name=name[:150], relationship=rel, identity_ref=idref[:80], evidence_ref=evid[:200],
                                   payment_details_enc=crypto.encrypt(details) if details else "", created_by_username=user.username)
    record("beneficiary.add", actor=user, entity_type="beneficiary", entity_id=b.pk, metadata={"case": str(case.pk), "relationship": rel})
    return b


def decide_beneficiary(user, b, verify, note=""):
    if b.state != Beneficiary.State.PENDING:
        raise InvalidState()
    _live(b.case)
    if b.created_by_username == user.username and not bg.bypass(user, "beneficiary_verifier", "beneficiary", b.pk):
        raise rule("verifier_must_differ", "state")
    if not verify and not note.strip():
        raise rule("comment_required", "comment")
    if verify:
        # Enforce the priority order at approval: a parent cannot be verified while a wife/child claim is pending or verified,
        # a sibling cannot be verified while a wife/child/parent claim is pending or verified.
        for other in b.case.beneficiaries.exclude(pk=b.pk).exclude(state="rejected"):
            if other.tier < b.tier:
                raise rule("higher_priority_exists", "state")
    Beneficiary.objects.filter(pk=b.pk).update(state="verified" if verify else "rejected", decided_by_id=user.pk,
                                               decided_by_username=user.username, decided_at=timezone.now(), decision_note=note[:300])
    record("beneficiary.verify" if verify else "beneficiary.reject", actor=user, entity_type="beneficiary", entity_id=b.pk)
    b.refresh_from_db()
    return b


def eligible_tier(case):
    """The beneficiary class that may be paid: wife and children first; if none is verified, parents; then siblings. A
    lower class is blocked while a higher class still has a claim awaiting verification."""
    rows = list(case.beneficiaries.exclude(state="rejected"))
    for tier in (1, 2, 3):
        mine = [b for b in rows if b.tier == tier]
        if any(b.state == "pending" for b in mine):
            return None  # undecided higher-priority claim: nothing lower may be paid yet
        if any(b.state == "verified" for b in mine):
            return tier
    return None


def mark_verified(user, case, review):
    _live(case)
    if case.status == "disputed":
        raise InvalidState()
    if eligible_tier(case) is None:
        raise rule("no_eligible_beneficiary", "case")
    if not str(review or "").strip():
        raise rule("outstanding_review_required", "outstanding_review")
    SurvivorCase.objects.filter(pk=case.pk).update(status="verified", outstanding_review=review[:1000], verified_by_id=user.pk,
                                                   verified_by_username=user.username, version=case.version + 1, updated_at=timezone.now())
    record("survivor_case.verify", actor=user, entity_type="survivor_case", entity_id=case.pk)
    case.refresh_from_db()
    return case


def set_dispute(user, case, disputed, note=""):
    _live(case)
    if disputed and not note.strip():
        raise rule("comment_required", "comment")
    SurvivorCase.objects.filter(pk=case.pk).update(status="disputed" if disputed else "open", dispute_note=note[:500] if disputed else "",
                                                   version=case.version + 1, updated_at=timezone.now())
    record("survivor_case.dispute" if disputed else "survivor_case.undispute", actor=user, entity_type="survivor_case", entity_id=case.pk)
    case.refresh_from_db()
    return case


def propose_allocation(user, b, data):
    case = b.case
    if case.status != "verified":
        raise rule("case_not_verified", "case")
    if b.state != "verified" or eligible_tier(case) != b.tier:
        raise rule("beneficiary_not_eligible", "beneficiary")
    basis = str(data.get("basis_ref") or "").strip()[:200]
    if not basis:
        raise rule("basis_ref_required", "basis_ref")  # no invented entitlements: every amount cites the confirmed policy
    amt = money(data.get("amount"), "amount")
    if amt == 0:
        raise rule("invalid_amount", "amount")
    currency = str(data.get("currency") or "").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise rule("invalid_currency", "currency")
    kind = str(data.get("basis_kind") or "per_period")
    if kind not in ("per_period", "lump_sum"):
        raise rule("invalid_basis_kind", "basis_kind")
    eff = None
    if kind == "per_period":
        # A standing monthly entitlement. It has NO end date: it continues until a documented decision changes or ends it.
        try:
            eff = date.fromisoformat(str(data.get("effective_from")))
        except ValueError:
            raise rule("invalid_date", "effective_from")
    a = BenefitAllocation.objects.create(beneficiary=b, amount=amt, currency=currency, basis_ref=basis, basis_kind=kind, effective_from=eff,
                                         proposed_by_id=user.pk, proposed_by_username=user.username)
    record("allocation.propose", actor=user, entity_type="allocation", entity_id=a.pk, metadata={"case": str(case.pk)})
    return a


def authorize_allocation(user, a):
    if a.status != "proposed":
        raise InvalidState()
    case = a.beneficiary.case
    if case.status != "verified" or eligible_tier(case) != a.beneficiary.tier:
        raise rule("case_not_verified", "case")  # disputed, re-opened or superseded claims cannot be authorised
    if a.proposed_by_id == user.pk and not bg.bypass(user, "allocation_authorizer", "allocation", a.pk):
        record("allocation.authorize", actor=user, outcome="denied", entity_type="allocation", entity_id=a.pk, metadata={"reason": "self_approval"})
        raise rule("approver_must_differ", "status")
    BenefitAllocation.objects.filter(pk=a.pk).update(status="authorized", authorized_by_id=user.pk, authorized_by_username=user.username,
                                                     authorized_at=timezone.now())
    record("allocation.authorize", actor=user, entity_type="allocation", entity_id=a.pk)
    a.refresh_from_db()
    return a


def allocation_paid_for(a, year=None, month=None):
    qs = a.payments.all()
    if a.basis_kind == "per_period":
        qs = qs.filter(period_year=year, period_month=month)
    return qs.aggregate(t=Sum("amount"))["t"] or ZERO


def allocation_period_error(a, year, month):
    """Why a standing benefit cannot be paid for this month (None if it can). Only documented decisions create these limits."""
    ym = (year, month)
    if a.effective_from and ym < (a.effective_from.year, a.effective_from.month):
        return "period_before_effective_date"
    if a.ended_on and ym > (a.ended_on.year, a.ended_on.month):
        return "benefit_terminated"
    if a.held_from and a.status == "suspended" and ym >= (a.held_from.year, a.held_from.month):
        return "benefit_suspended"
    return None


def ledger_survivor_payment(user, a, amount, paid_on, reference, year=None, month=None, note="", instruction=None):
    """Post a survivor payment. Internal: called by the payment workflow with the allocation locked. A standing benefit is
    paid month by month (each month capped at the authorised amount) and is NEVER stopped by the passing of time."""
    if a.status not in ("authorized",) or a.beneficiary.case.status != "verified":
        raise InvalidState()  # suspended, terminated, disputed or closed: no payment
    amt = money(amount, "amount")
    if amt == 0:
        raise rule("invalid_amount", "amount")
    if paid_on > timezone.localdate():
        raise rule("future_date", "paid_on")
    if a.basis_kind == "per_period":
        if year is None or month is None:
            raise rule("period_required", "period")
        err = allocation_period_error(a, year, month)
        if err:
            raise rule(err, "period")
    if allocation_paid_for(a, year, month) + amt > a.amount:
        raise rule("exceeds_authorized_amount", "amount")
    p = SurvivorPayment.objects.create(allocation=a, amount=amt, reference=(reference or "")[:80], paid_on=paid_on,
                                       paid_by_id=user.pk, paid_by_username=user.username, note=(note or "")[:300],
                                       period_year=year if a.basis_kind == "per_period" else None,
                                       period_month=month if a.basis_kind == "per_period" else None, instruction=instruction)
    record("survivor.pay", actor=user, entity_type="allocation", entity_id=a.pk, metadata={"reference": p.reference})
    return p


# ---- documented decisions on a standing benefit (the ONLY way it changes or ends)

def propose_allocation_decision(user, a, data):
    if a.status not in ("authorized", "suspended"):
        raise InvalidState()
    kind = data.get("kind")
    if kind not in ("change_amount", "suspend", "resume", "terminate"):
        raise rule("invalid_kind", "kind")
    if kind == "resume" and a.status != "suspended":
        raise InvalidState()
    if kind in ("suspend", "change_amount") and a.status != "authorized":
        raise InvalidState()
    reason = str(data.get("reason") or "").strip()[:500]
    ref = str(data.get("supporting_ref") or "").strip()[:200]
    if not reason:
        raise rule("reason_required", "reason")
    if not ref:
        raise rule("supporting_ref_required", "supporting_ref")
    try:
        eff = date.fromisoformat(str(data.get("effective_date")))
    except ValueError:
        raise rule("invalid_date", "effective_date")
    new_amount = None
    if kind == "change_amount":
        new_amount = money(data.get("new_amount"), "new_amount")
        if new_amount == 0:
            raise rule("invalid_amount", "new_amount")
    if AllocationDecision.objects.filter(allocation=a, state="proposed").exists():
        raise rule("decision_already_proposed", "kind")
    d = AllocationDecision.objects.create(allocation=a, kind=kind, new_amount=new_amount, previous_amount=a.amount, reason=reason,
                                          effective_date=eff, supporting_ref=ref, proposed_by_id=user.pk, proposed_by_username=user.username)
    record("allocation.decision_propose", actor=user, entity_type="allocation", entity_id=a.pk, metadata={"kind": kind, "decision": str(d.pk)})
    return d


@transaction.atomic
def decide_allocation_decision(user, d, approve, note=""):
    d = AllocationDecision.objects.select_for_update().select_related("allocation__beneficiary__case").get(pk=d.pk)
    if d.state != "proposed":
        raise InvalidState()
    if d.proposed_by_id == user.pk and not bg.bypass(user, "allocation_decision_approver", "allocation", d.allocation_id):
        record("allocation.decision_decide", actor=user, outcome="denied", entity_type="allocation", entity_id=d.allocation_id,
               metadata={"reason": "self_approval", "decision": str(d.pk)})
        raise rule("approver_must_differ", "state")
    if not approve and not note.strip():
        raise rule("comment_required", "comment")
    a = BenefitAllocation.objects.select_for_update().get(pk=d.allocation_id)
    if approve:
        if d.kind == "change_amount":
            BenefitAllocation.objects.filter(pk=a.pk).update(amount=d.new_amount)
        elif d.kind == "suspend":
            BenefitAllocation.objects.filter(pk=a.pk).update(status="suspended", held_from=d.effective_date)
        elif d.kind == "resume":
            BenefitAllocation.objects.filter(pk=a.pk).update(status="authorized", held_from=None)
        elif d.kind == "terminate":
            BenefitAllocation.objects.filter(pk=a.pk).update(status="terminated", ended_on=d.effective_date)
        # open payment instructions for a stopped benefit are no longer valid; they are cancelled with the decision recorded
        if d.kind in ("suspend", "terminate"):
            from .payments import cancel_open_for_allocation
            cancel_open_for_allocation(user, a.pk, f"benefit {d.kind} decision {d.pk}")
    AllocationDecision.objects.filter(pk=d.pk).update(state="approved" if approve else "rejected", decided_by_id=user.pk,
                                                      decided_by_username=user.username, decided_at=timezone.now(), decision_note=note[:300])
    record("allocation.decision_approve" if approve else "allocation.decision_reject", actor=user, entity_type="allocation",
           entity_id=a.pk, metadata={"kind": d.kind, "decision": str(d.pk), "effective_date": d.effective_date.isoformat()})
    d.refresh_from_db()
    return d


def update_beneficiary(user, b, data):
    """Edit a beneficiary's details with a reason. The audit entry and the change history hold field NAMES only."""
    _live(b.case)
    reason = str(data.get("reason") or "").strip()[:300]
    if not reason:
        raise rule("reason_required", "reason")
    changed, fields = [], {}
    for key, limit in (("full_name", 150), ("identity_ref", 80), ("evidence_ref", 200)):
        if key in data:
            val = str(data.get(key) or "").strip()[:limit]
            if not val:
                raise rule("beneficiary_details_required", key)
            if val != getattr(b, key):
                fields[key] = val
                changed.append(key)
    if "payment_details" in data:
        details = str(data.get("payment_details") or "").strip()[:300]
        fields["payment_details_enc"] = crypto.encrypt(details) if details else ""
        changed.append("payment_details")
    if not changed:
        raise rule("nothing_to_change", "reason")
    Beneficiary.objects.filter(pk=b.pk).update(**fields)
    BeneficiaryChange.objects.create(beneficiary=b, fields_changed=changed, reason=reason, actor_id=user.pk, actor_username=user.username)
    record("beneficiary.update", actor=user, entity_type="beneficiary", entity_id=b.pk, metadata={"fields": changed})
    b.refresh_from_db()
    return b


def close_case(user, case, reason, effective_date, supporting_ref):
    """Close a survivor case by a documented decision. A case never closes because time passed or because payments were made:
    every standing benefit must first have been ended by its own approved decision."""
    _live(case)
    reason = str(reason or "").strip()[:500]
    supporting_ref = str(supporting_ref or "").strip()[:200]
    if not reason:
        raise rule("reason_required", "reason")
    if not supporting_ref:
        raise rule("supporting_ref_required", "supporting_ref")
    try:
        eff = date.fromisoformat(str(effective_date))
    except ValueError:
        raise rule("invalid_date", "effective_date")
    live = BenefitAllocation.objects.filter(beneficiary__case=case, status__in=("authorized", "suspended"))
    if live.exists():
        raise rule("live_benefits_remain", "case")  # end each benefit with its own documented decision first
    BenefitAllocation.objects.filter(beneficiary__case=case, status="proposed").update(status="cancelled")
    from .payments import cancel_open_for_case
    cancel_open_for_case(user, case.pk, "case closed by documented decision")
    SurvivorCase.objects.filter(pk=case.pk).update(status="closed", closed_by_username=user.username, closure_reason=reason,
                                                   closure_effective_date=eff, closure_ref=supporting_ref,
                                                   version=case.version + 1, updated_at=timezone.now())
    record("survivor_case.close", actor=user, entity_type="survivor_case", entity_id=case.pk,
           metadata={"effective_date": eff.isoformat()})
    case.refresh_from_db()
    return case
