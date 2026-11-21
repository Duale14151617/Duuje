import uuid

from django.db import models

from apps.core.appendonly import AppendOnlyModel


class MedicalEntry(AppendOnlyModel):
    """One fitness assessment for one person. APPEND-ONLY: an entry is never edited or deleted; a correction is a new entry
    whose `corrects` points at the one it replaces. The latest entry nobody has corrected is the person's current fitness.

    Two levels of sensitivity live in one row:
      - fitness (status, review date, duty restriction): what a commander needs to plan duty. The restriction is a short,
        non-diagnostic duty note ("no night duty"), never a diagnosis. Encrypted at rest, read with `fitness.view`.
      - details (diagnosis, treatment, notes): encrypted at rest, read only with `medical.view` (the medical officer).
    """

    class Fitness(models.TextChoices):
        FIT = "fit"
        LIMITED = "limited"        # fit for limited duty
        UNFIT = "unfit"
        UNDER_REVIEW = "under_review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="medical_entries")
    corrects = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections")
    fitness_status = models.CharField(max_length=12, choices=Fitness.choices)
    review_due = models.DateField(null=True, blank=True)  # when the next assessment is due; plain so overdue reviews can be found
    restriction_enc = models.TextField(blank=True)
    details_enc = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_username = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "medical_entries"
        ordering = ["-recorded_at", "-id"]
        indexes = [models.Index(fields=["personnel", "-recorded_at"], name="medical_person_idx")]
