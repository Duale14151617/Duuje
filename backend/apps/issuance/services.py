"""Issuing officer ID cards and official letters, and the public check that a scanned QR code is genuine.

Rules (written here so they can be explained to the ministry):
* An ID card needs a person who is still serving and has a photo on file. Issuing a new card for the same person revokes the old one,
  so only one card is valid at a time. A card lasts ID_CARD_VALID_YEARS (default 2).
* A letter is issued by someone who holds `credentials.issue` for the unit it comes from. Its subject and text are frozen when issued;
  the letter prints a short fingerprint of that text, so an altered paper no longer matches what the public check shows.
* The public check never shows a photo, date of birth, phone or any profile field. A valid card shows name, rank, unit and a partly
  hidden service number so a checkpoint can compare it with the card in hand. Anything not valid shows only that it is not valid.
* Documents are never deleted. A revoked document stays on record with who revoked it and why.
"""
import hashlib
import logging
import secrets
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.errors import field_error
from apps.personnel.models import Personnel, PersonnelProfile
from apps.personnel.services import NOT_SERVING

from .models import IssuedDocument

log = logging.getLogger("armyhq.issuance")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I, easy to read out over a radio
CODE_LEN = 12


def new_code():
    for _ in range(10):
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        if not IssuedDocument.objects.filter(code=code).exists():
            return code
    raise RuntimeError("could not allocate a verification code")


def verify_url(code):
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return f"{base}/verify/{code}"


def qr_data_uri(code):
    """The QR code for the verification link as an inline SVG data URI (no external service, nothing leaves the server)."""
    try:
        import segno
        return segno.make(verify_url(code), error="m").svg_data_uri(scale=6, border=1, dark="#000000", light="#ffffff")
    except Exception:
        log.warning("QR code could not be generated")
        return ""


def fingerprint(doc):
    text = f"{doc.subject}\n{doc.recipient}\n{doc.body}".encode("utf-8")
    return hashlib.sha256(text).hexdigest()[:10].upper()


def _reference(kind, code):
    prefix = getattr(settings, "ISSUANCE_REF_PREFIX", "PHQ")
    return f"{prefix}-{'ID' if kind == IssuedDocument.Kind.ID_CARD else 'LTR'}-{timezone.localdate().year}-{code[:6]}"


def state(doc):
    if doc.status == IssuedDocument.Status.REVOKED:
        return "revoked"
    if doc.expires_on and doc.expires_on < timezone.localdate():
        return "expired"
    if doc.kind == IssuedDocument.Kind.ID_CARD and doc.personnel_id and doc.personnel.status in [s.value for s in NOT_SERVING]:
        return "not_serving"
    return "valid"


def _has_photo(person):
    return PersonnelProfile.objects.filter(pk=person.pk, photo_enc__isnull=False).exists()


def _person_snapshot(person):
    return {"full_name": person.full_name, "service_number": person.service_number or "",
            "rank_en": person.rank.name_en, "rank_so": person.rank.name_so,
            "unit_en": person.org_unit.name_en, "unit_so": person.org_unit.name_so}


@transaction.atomic
def issue_id_card(user, person):
    person = Personnel.objects.select_related("rank", "org_unit").get(pk=person.pk)
    if person.status in [s.value for s in NOT_SERVING]:
        raise field_error("personnel", "not_serving", "This person is no longer serving.")
    if not _has_photo(person):
        raise field_error("personnel", "photo_required", "Add a profile photo before issuing an ID card.")
    now = timezone.now()
    IssuedDocument.objects.filter(personnel=person, kind=IssuedDocument.Kind.ID_CARD, status=IssuedDocument.Status.VALID).update(
        status=IssuedDocument.Status.REVOKED, revoked_at=now, revoked_by=user, revoked_reason="Replaced by a newer card")
    years = int(getattr(settings, "ID_CARD_VALID_YEARS", 2))
    today = timezone.localdate()
    try:
        expires = today.replace(year=today.year + years)
    except ValueError:  # 29 February
        expires = today.replace(year=today.year + years, day=28)
    code = new_code()
    return IssuedDocument.objects.create(
        kind=IssuedDocument.Kind.ID_CARD, code=code, reference=_reference(IssuedDocument.Kind.ID_CARD, code), personnel=person,
        org_unit=person.org_unit, subject="Officer identity card", snapshot=_person_snapshot(person), issued_by=user, expires_on=expires)


@transaction.atomic
def issue_letter(user, unit, *, subject, body, recipient="", signed_title=""):
    subject, body, recipient, signed_title = subject.strip(), body.strip(), recipient.strip(), signed_title.strip()
    if not subject:
        raise field_error("subject", "required", "A subject is required.")
    if not body:
        raise field_error("body", "required", "The letter text is required.")
    if len(subject) > 200 or len(recipient) > 200 or len(signed_title) > 120:
        raise field_error("subject", "too_long", "Too long.")
    if len(body) > 8000:
        raise field_error("body", "too_long", "The letter text is too long (8000 characters at most).")
    code = new_code()
    return IssuedDocument.objects.create(
        kind=IssuedDocument.Kind.LETTER, code=code, reference=_reference(IssuedDocument.Kind.LETTER, code), org_unit=unit,
        subject=subject, recipient=recipient, body=body, issued_by=user,
        snapshot={"signed_by": user.full_name, "signed_title": signed_title, "unit_en": unit.name_en, "unit_so": unit.name_so})


@transaction.atomic
def revoke(user, doc, reason):
    reason = (reason or "").strip()
    if not reason:
        raise field_error("reason", "required", "Give a reason.")
    if len(reason) > 300:
        raise field_error("reason", "too_long", "Too long.")
    if doc.status == IssuedDocument.Status.REVOKED:
        raise field_error("status", "already_revoked", "This document is already revoked.")
    doc.status = IssuedDocument.Status.REVOKED
    doc.revoked_at = timezone.now()
    doc.revoked_by = user
    doc.revoked_reason = reason
    doc.save(update_fields=["status", "revoked_at", "revoked_by", "revoked_reason"])
    return doc


def _mask(number):
    number = number or ""
    return ("*" * max(len(number) - 3, 0)) + number[-3:] if number else ""


def public_view(doc):
    """What anyone holding the code may see. See the module notes for what is deliberately left out."""
    st = state(doc)
    out = {"state": st, "kind": doc.kind, "reference": doc.reference, "issued_on": timezone.localtime(doc.issued_at).date().isoformat()}
    if st != "valid":
        return out
    snap = doc.snapshot or {}
    if doc.kind == IssuedDocument.Kind.ID_CARD:
        out.update({"full_name": snap.get("full_name", ""), "service_number": _mask(snap.get("service_number", "")),
                    "rank_en": snap.get("rank_en", ""), "rank_so": snap.get("rank_so", ""),
                    "unit_en": snap.get("unit_en", ""), "unit_so": snap.get("unit_so", ""),
                    "expires_on": doc.expires_on.isoformat() if doc.expires_on else None})
    else:
        out.update({"subject": doc.subject, "recipient": doc.recipient, "signed_by": snap.get("signed_by", ""),
                    "signed_title": snap.get("signed_title", ""), "unit_en": snap.get("unit_en", ""), "unit_so": snap.get("unit_so", ""),
                    "fingerprint": fingerprint(doc)})
    return out


def detail(doc):
    """Full payload for the signed-in issuer: everything needed to print the document."""
    st = state(doc)
    return {
        "id": str(doc.pk), "kind": doc.kind, "code": doc.code, "reference": doc.reference, "state": st, "status": doc.status,
        "personnel_id": str(doc.personnel_id) if doc.personnel_id else None,
        "org_unit": {"id": str(doc.org_unit_id), "name_en": doc.org_unit.name_en, "name_so": doc.org_unit.name_so},
        "subject": doc.subject, "recipient": doc.recipient, "body": doc.body, "snapshot": doc.snapshot,
        "issued_at": doc.issued_at.isoformat(), "issued_by": doc.issued_by.full_name,
        "expires_on": doc.expires_on.isoformat() if doc.expires_on else None,
        "revoked_at": doc.revoked_at.isoformat() if doc.revoked_at else None, "revoked_reason": doc.revoked_reason,
        "verify_url": verify_url(doc.code), "qr": qr_data_uri(doc.code),
        "fingerprint": fingerprint(doc) if doc.kind == IssuedDocument.Kind.LETTER else None,
    }


def brief(doc):
    snap = doc.snapshot or {}
    return {"id": str(doc.pk), "kind": doc.kind, "reference": doc.reference, "state": state(doc),
            "title": snap.get("full_name") if doc.kind == IssuedDocument.Kind.ID_CARD else doc.subject,
            "issued_at": doc.issued_at.isoformat(), "expires_on": doc.expires_on.isoformat() if doc.expires_on else None,
            "unit": {"id": str(doc.org_unit_id), "name_en": doc.org_unit.name_en, "name_so": doc.org_unit.name_so}}
