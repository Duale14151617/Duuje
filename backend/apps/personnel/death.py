"""Death reporting and confirmation. Death is a status, never a deletion.

Flow: an authorized officer REPORTS a death (date of death) -> supporting evidence is uploaded to the personnel file
(category death_evidence) -> a DIFFERENT authorized officer CONFIRMS. Only confirmation changes the status to Died, writes
the status history entry (effective on the date of death) and closes the person's login. Nothing is deleted: profile,
rank/unit/status history, documents and audit trail all stay. A mistaken report can be withdrawn before confirmation;
reversing a *confirmed* death is deliberately not offered here (it needs an institutional decision).

Two controls below are assumptions to confirm with the army: confirmation by a second officer, and at least one
supporting document before confirmation.
"""
from datetime import date

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import revoke_user_sessions
from apps.core.concurrency import versioned_update

from . import appointments, records
from .models import DeathRecord, Personnel, PersonnelDocument
from .services import RuleError, add_history


def open_record(person):
    """The person's current (reported or confirmed) death record, if any."""
    return person.death_records.exclude(state=DeathRecord.State.WITHDRAWN).first()


def evidence(person):
    return PersonnelDocument.objects.filter(personnel=person, category=PersonnelDocument.Category.DEATH_EVIDENCE,
                                            withdrawn_at__isnull=True)


def report(actor, person, day, note=""):
    if person.status == Personnel.Status.DIED:
        raise RuleError("person_deceased", "status")
    if day > date.today():
        raise RuleError("future_date", "date_of_death")
    if open_record(person) is not None:
        raise RuleError("death_already_reported", "date_of_death")
    return DeathRecord.objects.create(
        personnel=person, date_of_death=day, note=(note or "")[:300],
        reported_by_id=actor.pk, reported_by_username=actor.username)


def confirm(actor, person, rec, expected_version):
    """Confirm a reported death. Caller wraps this in a transaction. Returns (updated person, account_closed)."""
    if rec.state != DeathRecord.State.REPORTED:
        raise RuleError("death_not_pending", "state")
    if rec.reported_by_id == actor.pk:
        raise RuleError("confirmer_must_differ", "state")  # separation of duties: the reporter cannot confirm
    if not evidence(person).exists():
        raise RuleError("death_evidence_required", "state")
    old = person.status
    updated = versioned_update(person, {"status": Personnel.Status.DIED}, expected_version)
    add_history(updated, "status", old, "died", old, "died", rec.date_of_death, "Death confirmed", actor)
    DeathRecord.objects.filter(pk=rec.pk).update(
        state=DeathRecord.State.CONFIRMED, confirmed_at=timezone.now(),
        confirmed_by_id=actor.pk, confirmed_by_username=actor.username)
    appointments.end_all_for(actor, updated, "Death confirmed")  # command appointments end, linked access is revoked
    closed = False
    if updated.account_id:  # a deceased person's login ends with their service: access is revoked, the link is kept
        acct = User.objects.get(pk=updated.account_id)
        if acct.is_active:
            User.objects.filter(pk=acct.pk).update(is_active=False)
            revoke_user_sessions(acct)
            closed = True
    return updated, closed


def withdraw(actor, rec, reason):
    if rec.state != DeathRecord.State.REPORTED:
        raise RuleError("death_not_pending", "state")
    DeathRecord.objects.filter(pk=rec.pk).update(
        state=DeathRecord.State.WITHDRAWN, withdrawn_at=timezone.now(), withdrawn_by_id=actor.pk,
        withdrawn_by_username=actor.username, withdrawn_reason=(reason or "")[:300])


def record_out(rec, with_evidence_list=None):
    out = {
        "id": str(rec.pk), "state": rec.state, "date_of_death": rec.date_of_death.isoformat(), "note": rec.note,
        "reported_at": rec.reported_at, "reported_by": rec.reported_by_username,
        "confirmed_at": rec.confirmed_at, "confirmed_by": rec.confirmed_by_username,
        "withdrawn_at": rec.withdrawn_at, "withdrawn_by": rec.withdrawn_by_username,
        "withdrawn_reason": rec.withdrawn_reason,
    }
    if with_evidence_list is not None:
        out["evidence"] = with_evidence_list
    return out


def evidence_list(person):
    return [d for d in records.list_documents(person) if d.get("category") == PersonnelDocument.Category.DEATH_EVIDENCE]
