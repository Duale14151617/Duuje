import uuid

from django.db import models


class PromotionRule(models.Model):
    """How long someone must hold a rank before they can be considered for the next one. Policy, so it is data set by the
    super administrator; nothing is seeded because the minimums are the institution's to decide.

    Eligibility only says "has served long enough and is in good standing". It never changes a rank: a promotion is still made
    through the normal personnel rank change."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rank = models.OneToOneField("ranks.Rank", on_delete=models.CASCADE, related_name="promotion_rule")
    next_rank = models.ForeignKey("ranks.Rank", null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # none = the next rank up
    min_months = models.PositiveSmallIntegerField()
    active = models.BooleanField(default=True)
    updated_by_username = models.CharField(max_length=150, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "promotion_rules"
        constraints = [models.CheckConstraint(condition=models.Q(min_months__gte=1, min_months__lte=600), name="promotion_months_range")]
