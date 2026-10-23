"""Suspended/jailed pay review, arrears claims, and configurable policy. None of this changes a salary on its own."""
import re
from datetime import date

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record
from apps.personnel.models import Personnel

from . import services as svc
from .models import ArrearsClaim, PayrollLine, PolicySetting, StatusPayDecision

FLAGGED = (Personnel.Status.SUSPENDED, Personnel.Status.JAILED)

def deduction_tiers():
    """The allowed deduction percentages, read from the (changeable) policy row. Falls back to the institution's 5/10/20."""
    row = PolicySetting.objects.filter(pk="suspended_jailed_deduction_tiers", status="confirmed").first()
    try:
        tiers = sorted({int(x) for x in (row.value if row else "5,10,20").split(",") if x.strip()})
    except ValueError:
        tiers = [5, 10, 20]
    return [t for t in tiers if 0 < t < 100]


def deduction_percent_for(person, on):
    """Percent to deduct from a suspended/jailed person's pay for a period ending `on`: the latest APPROVED decision in force.
    No approved decision (or retain_existing) means 0: nothing is deducted until Finance has decided and a second officer approved."""
    d = (StatusPayDecision.objects.filter(personnel=person, state="approved", effective_date__lte=on)
         .order_by("-effective_date", "-recorded_at").first())
    return d.deduction_percent if d else 0


FLAG_TEXT = "Under review: existing pay treatment retained pending an authorized decision. Nothing is stopped, reduced or withheld automatically."


def flagged_people():
    return Personnel.objects.filter(status__in=FLAGGED).select_related("org_unit")


def latest_decision(person):
    return StatusPayDecision.objects.filter(personnel=person).exclude(state="rejected").order_by("-recorded_at").first()


# ------------------------------------------------------------------ suspended / jailed decisions

def record_status_decision(user, person, data):
    if person.status not in FLAGGED:
        raise svc.rule("person_not_flagged", "personnel")
    kind = data.get("kind")
    if kind not in ("retain_existing", "formal_decision"):
        raise svc.rule("invalid_kind", "kind")
    reason = str(data.get("reason") or "").strip()[:500]
    if not reason:
        raise svc.rule("reason_required", "reason")
    try:
        eff = date.fromisoformat(str(data.get("effective_date")))
    except ValueError:
        raise svc.rule("invalid_date", "effective_date")
    text = str(data.get("decision_text") or "").strip()[:500]
    ref = str(data.get("supporting_ref") or "").strip()[:200]
    if kind == "formal_decision" and not (text and ref):
        raise svc.rule("decision_text_and_document_required", "decision_text")  # a real decision needs wording and a document
    try:
        pct = int(data.get("deduction_percent") or 0)
    except (TypeError, ValueError):
        raise svc.rule("invalid_deduction_percent", "deduction_percent")
    if pct and (kind != "formal_decision" or pct not in deduction_tiers()):
        raise svc.rule("invalid_deduction_percent", "deduction_percent")  # only a formal decision, only an allowed tier
    d = StatusPayDecision.objects.create(personnel=person, status_at_decision=person.status, kind=kind, decision_text=text, deduction_percent=pct, reason=reason,
                                         effective_date=eff, supporting_ref=ref, recorded_by_id=user.pk, recorded_by_username=user.username)
    record("pay_decision.record", actor=user, entity_type="status_pay_decision", entity_id=d.pk,
           metadata={"personnel": str(person.pk), "kind": kind, "status": person.status, "deduction_percent": pct})
    return d


@transaction.atomic
def decide_status_decision(user, d, approve, note=""):
    d = StatusPayDecision.objects.select_for_update().get(pk=d.pk)
    if d.state != "recorded":
        raise svc.InvalidState()
    if d.recorded_by_id == user.pk:
        record("pay_decision.decide", actor=user, outcome="denied", entity_type="status_pay_decision", entity_id=d.pk, metadata={"reason": "self_approval"})
        raise svc.rule("approver_must_differ", "state")
    if not approve and not str(note).strip():
        raise svc.rule("comment_required", "comment")
    StatusPayDecision.objects.filter(pk=d.pk).update(state="approved" if approve else "rejected", decided_by_id=user.pk,
                                                     decided_by_username=user.username, decided_at=timezone.now(), decision_note=str(note)[:300])
    record("pay_decision.approve" if approve else "pay_decision.reject", actor=user, entity_type="status_pay_decision", entity_id=d.pk,
           metadata={"personnel": str(d.personnel_id), "kind": d.kind})
    d.refresh_from_db()
    return d


# ------------------------------------------------------------------ arrears

PERIOD_RE = re.compile(r"^(20\d\d)-(0[1-9]|1[0-2])$")


def unpaid_approved_lines(person):
    """Approved salary lines that were never fully paid: the starting evidence for an arrears claim. Reported, never claimed
    or forfeited automatically."""
    out = []
    for line in PayrollLine.objects.filter(personnel=person, kind="regular", approved_net__isnull=False).select_related("period"):
        due = line.approved_net - svc.paid_total(line)
        if due > 0 and not (person.status == "died" and svc.deceased_payable_line(line)):
            out.append((line, due))
    return out


def record_arrears(user, person, data):
    periods = data.get("periods")
    if not isinstance(periods, list) or not periods or len(periods) > 60 or not all(isinstance(p, str) and PERIOD_RE.match(p) for p in periods) \
            or len(set(periods)) != len(periods):
        raise svc.rule("invalid_periods", "periods")
    amount = svc.money(data.get("amount"), "amount")
    if amount == 0:
        raise svc.rule("invalid_amount", "amount")
    currency = str(data.get("currency") or "").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise svc.rule("invalid_currency", "currency")
    evidence = str(data.get("evidence_ref") or "").strip()[:200]
    if not evidence:
        raise svc.rule("evidence_required", "evidence_ref")
    lines = data.get("source_lines") or []
    if not isinstance(lines, list) or len(lines) > 60 or not all(svc_valid(x) for x in lines):
        raise svc.rule("invalid_source_lines", "source_lines")
    if lines and PayrollLine.objects.filter(pk__in=lines, personnel=person).count() != len(set(lines)):
        raise svc.rule("unknown_line", "source_lines")
    c = ArrearsClaim.objects.create(personnel=person, periods=sorted(periods), source_lines=[str(x) for x in lines], amount=amount,
                                    currency=currency, evidence_ref=evidence, note=str(data.get("note") or "")[:500],
                                    recorded_by_id=user.pk, recorded_by_username=user.username)
    record("arrears.record", actor=user, entity_type="arrears_claim", entity_id=c.pk, metadata={"personnel": str(person.pk), "periods": len(periods)})
    return c


def svc_valid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


@transaction.atomic
def verify_arrears(user, claim, verify, note=""):
    c = ArrearsClaim.objects.select_for_update().get(pk=claim.pk)
    if c.status != "recorded":
        raise svc.InvalidState()
    if c.recorded_by_id == user.pk:
        raise svc.rule("verifier_must_differ", "status")
    if not verify and not str(note).strip():
        raise svc.rule("comment_required", "comment")
    ArrearsClaim.objects.filter(pk=c.pk).update(status="verified" if verify else "rejected", verified_by_id=user.pk,
                                                verified_by_username=user.username, verified_at=timezone.now(), decision_note=str(note)[:300])
    record("arrears.verify" if verify else "arrears.reject", actor=user, entity_type="arrears_claim", entity_id=c.pk)
    c.refresh_from_db()
    return c


@transaction.atomic
def approve_arrears(user, claim, approve, note=""):
    c = ArrearsClaim.objects.select_for_update().get(pk=claim.pk)
    if c.status != "verified":
        raise svc.InvalidState()
    if user.pk in (c.recorded_by_id, c.verified_by_id):
        record("arrears.approve", actor=user, outcome="denied", entity_type="arrears_claim", entity_id=c.pk, metadata={"reason": "approver_not_independent"})
        raise svc.rule("approver_must_differ", "status")
    if not approve and not str(note).strip():
        raise svc.rule("comment_required", "comment")
    ArrearsClaim.objects.filter(pk=c.pk).update(status="approved" if approve else "rejected", approved_by_id=user.pk,
                                                approved_by_username=user.username, approved_at=timezone.now(), decision_note=str(note)[:300])
    record("arrears.approve" if approve else "arrears.reject", actor=user, entity_type="arrears_claim", entity_id=c.pk)
    c.refresh_from_db()
    return c


def arrears_paid(c):
    return c.payments.aggregate(t=Sum("amount"))["t"] or svc.ZERO


# ------------------------------------------------------------------ policy

def confirm_policy(user, key, value, authority_ref):
    p = PolicySetting.objects.filter(pk=key).first()
    if p is None:
        from rest_framework.exceptions import NotFound
        raise NotFound()
    if p.status == "confirmed":
        raise svc.InvalidState("Confirmed rules are implemented defaults and cannot be edited here.")
    value, authority_ref = str(value or "").strip()[:300], str(authority_ref or "").strip()[:200]
    if not value:
        raise svc.rule("value_required", "value")
    if not authority_ref:
        raise svc.rule("authority_ref_required", "authority_ref")
    PolicySetting.objects.filter(pk=key).update(status="confirmed", value=value, authority_ref=authority_ref,
                                                confirmed_by_username=user.username, confirmed_at=timezone.now())
    record("policy.confirm", actor=user, entity_type="policy_setting", entity_id=key, metadata={"authority_ref": authority_ref})
    p.refresh_from_db()
    return p


def revise_policy(user, key, value, authority_ref, reason):
    """Change a policy value later (confirmed or not). Needs the new value, an authority reference and a reason; the old and new
    value are written to the audit log. Changing a value never rewrites past payroll lines."""
    p = PolicySetting.objects.filter(pk=key).first()
    if p is None:
        from rest_framework.exceptions import NotFound
        raise NotFound()
    value, authority_ref, reason = str(value or "").strip()[:300], str(authority_ref or "").strip()[:200], str(reason or "").strip()[:300]
    for field, v in (("value", value), ("authority_ref", authority_ref), ("reason", reason)):
        if not v:
            raise svc.rule(field + "_required", field)
    if key == "suspended_jailed_deduction_tiers":
        try:
            ok = all(0 < int(x) < 100 for x in value.split(","))
        except ValueError:
            ok = False
        if not ok:
            raise svc.rule("invalid_tiers", "value")
    old = p.value
    PolicySetting.objects.filter(pk=key).update(status="confirmed", value=value, authority_ref=authority_ref,
                                                confirmed_by_username=user.username, confirmed_at=timezone.now())
    record("policy.revise", actor=user, entity_type="policy_setting", entity_id=key,
           metadata={"authority_ref": authority_ref, "reason": reason, "old_value": old, "new_value": value})
    p.refresh_from_db()
    return p
