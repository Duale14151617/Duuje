"""Sensitive personnel-file records: disciplinary history and service documents.

Both are encrypted at rest (Fernet, FIELD_ENCRYPTION_KEY), scoped like the rest of the personnel data (including the
Police gate and restricted CID units, see apps/accounts/scope.py), and audited on every view and every change by the
views that call these functions. Nothing here writes the audit trail itself except where noted.
"""
import hashlib
import json
from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.core import crypto
from apps.core.errors import field_error

from .models import DisciplinaryRecord, Personnel, PersonnelDocument

# ---------------------------------------------------------------- disciplinary history
# Draft category list: confirm the wording with the Police / Army personnel authorities.
DISCIPLINARY_CATEGORIES = ["verbal_warning", "written_warning", "reprimand", "fine", "suspension", "demotion",
                           "dismissal", "other"]


class DisciplinaryInputSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=DISCIPLINARY_CATEGORIES)
    incident_date = serializers.DateField()
    summary = serializers.CharField(max_length=4000)
    outcome = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    corrects = serializers.UUIDField(required=False, allow_null=True, default=None)
    voided = serializers.BooleanField(required=False, default=False)  # a correction saying "the original was entered in error"

    def validate_incident_date(self, value):
        if value > date.today() or value < date(1950, 1, 1):
            raise serializers.ValidationError("Invalid incident date.", code="date_invalid")
        return value

    def validate_summary(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Describe the incident.", code="summary_required")
        return value

    def validate(self, attrs):
        if attrs.get("voided") and not attrs.get("corrects"):
            raise serializers.ValidationError({"voided": [serializers.ErrorDetail(
                "Only a correction can withdraw an entry.", code="void_needs_correction")]})
        return attrs


def _decode(row):
    return json.loads(crypto.decrypt(row.data_enc))


def add_disciplinary(person: Personnel, actor, data: dict) -> DisciplinaryRecord:
    """Append one entry. A correction (`corrects` set) must target an entry of the same person that has not been
    corrected already, so corrections form a single chain and never fork. The person row is locked while checking, so two
    people correcting the same entry at once cannot both succeed."""
    with transaction.atomic():
        Personnel.objects.select_for_update().get(pk=person.pk)
        target = None
        if data.get("corrects"):
            target = DisciplinaryRecord.objects.filter(pk=data["corrects"], personnel=person).first()
            if target is None:
                raise field_error("corrects", "record_not_found", "That entry does not belong to this person.")
            if target.corrections.exists():
                raise field_error("corrects", "already_corrected",
                                  "That entry was already corrected. Correct the latest entry instead.")
        blob = {"category": data["category"], "incident_date": data["incident_date"].isoformat(),
                "summary": data["summary"], "outcome": data.get("outcome", ""), "voided": bool(data.get("voided"))}
        return DisciplinaryRecord.objects.create(
            personnel=person, corrects=target, data_enc=crypto.encrypt(json.dumps(blob)),
            recorded_by_id=getattr(actor, "pk", None), recorded_by_username=getattr(actor, "username", ""))


def list_disciplinary(person: Personnel) -> list:
    rows = list(DisciplinaryRecord.objects.filter(personnel=person).select_related("corrects").order_by("-recorded_at", "-id"))
    superseded = {r.corrects_id for r in rows if r.corrects_id}
    out = []
    for r in rows:
        d = _decode(r)
        out.append({
            "id": str(r.pk), "category": d.get("category", ""), "incident_date": d.get("incident_date"),
            "summary": d.get("summary", ""), "outcome": d.get("outcome", ""), "voided": bool(d.get("voided")),
            "corrects": str(r.corrects_id) if r.corrects_id else None, "superseded": r.pk in superseded,
            "recorded_at": r.recorded_at.isoformat(), "recorded_by_username": r.recorded_by_username,
        })
    return out


# ---------------------------------------------------------------- service documents
DOCUMENT_MAX_BYTES = 8 * 1024 * 1024
DOCUMENT_MAX_PER_PERSON = 100
MAGIC = ((b"%PDF-", "application/pdf"), (b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"))
EXTENSION = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


class DocumentInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    category = serializers.ChoiceField(choices=[c.value for c in PersonnelDocument.Category])
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_title(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Enter a title.", code="title_required")
        return value


class WithdrawSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give a reason.", code="reason_required")
        return value


def sniff(raw: bytes):
    """Content type judged from the file's own first bytes, never from the name or the browser's claim."""
    for magic, ctype in MAGIC:
        if raw.startswith(magic):
            return ctype
    return None


def read_upload(upload) -> tuple:
    if upload.size > DOCUMENT_MAX_BYTES:
        raise field_error("file", "document_too_large", "The file must be under 8 MB.")
    raw = upload.read()
    if not raw:
        raise field_error("file", "document_empty", "The file is empty.")
    ctype = sniff(raw)
    if ctype is None:
        raise field_error("file", "document_type_invalid", "Upload a PDF, JPEG or PNG file.")
    return raw, ctype


def safe_filename(title: str, ctype: str) -> str:
    stem = "".join(ch if (ch.isalnum() or ch in "-_ ") else "_" for ch in title).strip()[:60] or "document"
    return f"{stem}.{EXTENSION[ctype]}"


def add_document(person: Personnel, actor, meta: dict, raw: bytes, ctype: str) -> PersonnelDocument:
    with transaction.atomic():
        Personnel.objects.select_for_update().get(pk=person.pk)
        if PersonnelDocument.objects.filter(personnel=person).count() >= DOCUMENT_MAX_PER_PERSON:
            raise field_error("file", "too_many_documents", "This file already holds the maximum number of documents.")
        blob = {"title": meta["title"], "note": meta.get("note", ""), "filename": safe_filename(meta["title"], ctype)}
        return PersonnelDocument.objects.create(
            personnel=person, category=meta["category"], meta_enc=crypto.encrypt(json.dumps(blob)),
            content_enc=crypto.encrypt_bytes(raw), content_type=ctype, size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            uploaded_by_id=getattr(actor, "pk", None), uploaded_by_username=getattr(actor, "username", ""))


def document_out(doc: PersonnelDocument) -> dict:
    meta = json.loads(crypto.decrypt(doc.meta_enc))
    return {
        "id": str(doc.pk), "title": meta.get("title", ""), "note": meta.get("note", ""), "category": doc.category,
        "content_type": doc.content_type, "size_bytes": doc.size_bytes, "uploaded_at": doc.uploaded_at.isoformat(),
        "uploaded_by_username": doc.uploaded_by_username,
    }


def list_documents(person: Personnel) -> list:
    qs = PersonnelDocument.objects.filter(personnel=person, withdrawn_at__isnull=True).defer("content_enc")
    return [document_out(d) for d in qs]


def get_document(person: Personnel, doc_id):
    """The live (not withdrawn) document of this person, or None. Bytes are included."""
    try:
        return PersonnelDocument.objects.filter(pk=doc_id, personnel=person, withdrawn_at__isnull=True).first()
    except (ValueError, TypeError, DjangoValidationError):  # malformed id
        return None


def read_document(doc: PersonnelDocument) -> tuple:
    """(plain bytes, file name). Verifies the stored checksum so a damaged row is reported instead of served."""
    raw = crypto.decrypt_bytes(doc.content_enc)
    if hashlib.sha256(raw).hexdigest() != doc.sha256:
        raise ValueError("document checksum mismatch")
    return raw, json.loads(crypto.decrypt(doc.meta_enc)).get("filename", "document")


def withdraw_document(doc: PersonnelDocument, actor, reason: str) -> PersonnelDocument:
    with transaction.atomic():
        locked = PersonnelDocument.objects.select_for_update().defer("content_enc").get(pk=doc.pk)
        if locked.withdrawn_at is not None:
            raise field_error("document", "already_withdrawn", "This document was already withdrawn.")
        locked.withdrawn_at = timezone.now()
        locked.withdrawn_by_id = getattr(actor, "pk", None)
        locked.withdrawn_by_username = getattr(actor, "username", "")
        locked.withdrawn_reason_enc = crypto.encrypt(reason)
        locked.save(update_fields=["withdrawn_at", "withdrawn_by_id", "withdrawn_by_username", "withdrawn_reason_enc"])
        return locked
