import uuid

from django.conf import settings
from django.db import models


class IssuedDocument(models.Model):
    """An officer ID card or an official letter that carries a QR code anyone can scan to check it is genuine.

    What is printed is frozen in `snapshot` / `subject` / `body` at issue time, so a later rank change or transfer never rewrites a
    document that was already handed over. A document is never deleted: it is revoked with a reason, and the public check then says so.
    `code` is the secret-looking verification token printed on the document and encoded in the QR (unguessable, 12 characters)."""

    class Kind(models.TextChoices):
        ID_CARD = "id_card"
        LETTER = "letter"

    class Status(models.TextChoices):
        VALID = "valid"
        REVOKED = "revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    code = models.CharField(max_length=16, unique=True, editable=False)
    reference = models.CharField(max_length=40, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    subject = models.CharField(max_length=200, blank=True)
    recipient = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.VALID)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    revoked_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "issued_documents"
        ordering = ["-issued_at"]
        indexes = [models.Index(fields=["personnel", "kind", "status"], name="issued_person_kind_status"),
                   models.Index(fields=["org_unit", "-issued_at"], name="issued_unit_date")]
