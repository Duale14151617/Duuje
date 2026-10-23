"""Command appointments (Taliye Qaybeed, Taliye Urur ...): who holds a command office, where, from when.

Kept separate from the other three concepts on purpose:
  * military rank              -> Personnel.rank (and its history)
  * organizational assignment  -> Personnel.org_unit (and its history)
  * application role / access  -> accounts.RoleAssignment
An appointment grants nothing by itself. It may be LINKED to a role assignment so that ending the appointment also revokes that
access; rank alone never grants access. Rows are never deleted: appointments are ended, with a reason.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.services import revoke_user_sessions

from . import police_appointments as police
from .models import AppointmentType, CommandAppointment, Personnel
from .services import NOT_SERVING, RuleError, outranks


def is_current(a, today=None):
    today = today or timezone.localdate()
    return a.ended_at is None and a.effective_from <= today and (a.effective_to is None or a.effective_to >= today)


def create(actor, person, org_unit, atype, effective_from, effective_to=None, authority_ref="", assignment=None):
    if person.status in NOT_SERVING:
        raise RuleError("person_not_serving", "personnel")
    if not atype.active or not org_unit.active:
        raise RuleError("appointment_inactive", "appointment_type")
    if atype.unit_type_id and org_unit.unit_type_id != atype.unit_type_id:
        raise RuleError("appointment_unit_mismatch", "org_unit")  # e.g. a Taliye Urur belongs to an Urur
    if atype.code in police.LEVEL_FOR:  # Chief of Police / Station Commander: Police unit of the right kind, Police officer
        if not police.unit_fits(atype.code, org_unit):
            raise RuleError("appointment_unit_mismatch", "org_unit")
        if person.branch.code != "POLICE":
            raise RuleError("appointment_person_not_police", "personnel")
    if effective_to is not None and effective_to < effective_from:
        raise RuleError("appointment_dates", "effective_to")
    if assignment is not None:
        if assignment.revoked_at is not None or person.account_id is None or assignment.user_id != person.account_id:
            raise RuleError("assignment_mismatch", "role_assignment")  # the access must belong to this person's own login
    if atype.exclusive and CommandAppointment.objects.filter(org_unit=org_unit, appointment_type=atype,
                                                             ended_at__isnull=True).exists():
        raise RuleError("appointment_exists", "appointment_type")
    try:
        with transaction.atomic():
            appt = CommandAppointment.objects.create(
                personnel=person, org_unit=org_unit, appointment_type=atype, exclusive=atype.exclusive,
                effective_from=effective_from, effective_to=effective_to, authority_ref=(authority_ref or "")[:150],
                role_assignment=assignment, created_by_id=actor.pk, created_by_username=actor.username)
            _link_police_chain(atype.code, org_unit, person)
            return appt
    except IntegrityError:  # two officers appointing at the same moment: the database refuses the second
        raise RuleError("appointment_exists", "appointment_type")


def _set_supervisor(person, sup):
    from django.db.models import F
    Personnel.objects.filter(pk=person.pk, supervisor__isnull=True).update(
        supervisor=sup, version=F("version") + 1, updated_at=timezone.now())


def _link_police_chain(code, unit, person):
    """Station Commanders report to the Chief of Police of their region. Only fills an EMPTY reporting line, only when the chief
    strictly outranks the commander (the same rule as every reporting line), and never replaces a line someone set by hand."""
    if code == police.CHIEF:
        open_leads = CommandAppointment.objects.filter(
            org_unit__parent=unit, appointment_type__code=police.STATION_LEAD, ended_at__isnull=True).select_related("personnel__rank")
        for a in open_leads:
            if a.personnel.supervisor_id is None and outranks(person.rank, a.personnel.rank):
                _set_supervisor(a.personnel, person)
    elif code == police.STATION_LEAD and unit.parent_id:
        chief = CommandAppointment.objects.filter(
            org_unit_id=unit.parent_id, appointment_type__code=police.CHIEF, ended_at__isnull=True).select_related("personnel__rank").first()
        if chief is not None and person.supervisor_id is None and outranks(chief.personnel.rank, person.rank):
            _set_supervisor(person, chief.personnel)


def end(actor, appt, reason):
    """End an appointment and revoke the access linked to it. Returns True when an access grant was revoked."""
    if appt.ended_at is not None:
        raise RuleError("appointment_ended", "appointment")
    CommandAppointment.objects.filter(pk=appt.pk).update(
        ended_at=timezone.now(), ended_by_id=getattr(actor, "pk", None),
        ended_by_username=getattr(actor, "username", ""), end_reason=(reason or "")[:300])
    revoked = False
    link = appt.role_assignment
    if link is not None and link.revoked_at is None:
        link.revoked_at = timezone.now()
        link.save(update_fields=["revoked_at"])
        revoke_user_sessions(link.user)  # takes effect on the next request
        revoked = True
    return revoked


def end_all_for(actor, person, reason):
    """Authority ends with service: close every open appointment of a person (death, retirement, discharge)."""
    n = revoked = 0
    for a in CommandAppointment.objects.filter(personnel=person, ended_at__isnull=True).select_related("role_assignment__user"):
        revoked += bool(end(actor, a, reason))
        n += 1
    return n, revoked


def out(a, with_person=False):
    d = {
        "id": str(a.pk),
        "appointment_type": {"id": str(a.appointment_type_id), "code": a.appointment_type.code,
                             "name_en": a.appointment_type.name_en, "name_so": a.appointment_type.name_so},
        "org_unit": {"id": str(a.org_unit_id), "code": a.org_unit.code, "name_en": a.org_unit.name_en,
                     "name_so": a.org_unit.name_so},
        "effective_from": a.effective_from.isoformat(),
        "effective_to": a.effective_to.isoformat() if a.effective_to else None,
        "authority_ref": a.authority_ref, "current": is_current(a), "created_by": a.created_by_username,
        "ended_at": a.ended_at, "ended_by": a.ended_by_username, "end_reason": a.end_reason,
        "has_access_link": a.role_assignment_id is not None,
    }
    if with_person:
        p = a.personnel
        d["personnel"] = {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
                          "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}}
    return d
