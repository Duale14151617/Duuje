import uuid

from django.conf import settings
from django.db import models


class ReportSchedule(models.Model):
    """A report that is emailed on a timetable, e.g. the weekly strength report to a region's commanders.

    The figures are built with the permissions of the person who created the schedule (counts only, no names), and each recipient must
    be an active user with a verified email who could open the same report in the app. Delivery is attempted only when the schedule
    is due; `next_run_at` is claimed atomically before sending so two server processes never send the same report twice."""

    class Frequency(models.TextChoices):
        DAILY = "daily"
        WEEKLY = "weekly"
        MONTHLY = "monthly"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    report = models.CharField(max_length=20, default="strength")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    frequency = models.CharField(max_length=8, choices=Frequency.choices, default=Frequency.WEEKLY)
    weekday = models.PositiveSmallIntegerField(default=0)       # 0 = Monday ... 6 = Sunday (weekly)
    day_of_month = models.PositiveSmallIntegerField(default=1)  # 1-28 (monthly)
    send_hour = models.PositiveSmallIntegerField(default=7)     # 0-23, in SCHEDULES_TIMEZONE
    period_days = models.PositiveSmallIntegerField(default=7)   # how far back "joined / left / promoted" look
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+", blank=True)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=24, blank=True)
    last_detail = models.CharField(max_length=200, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "report_schedules"
        ordering = ["name", "id"]


class AlertPreference(models.Model):
    """One row = this person has chosen to receive emails about this kind of event (see alerts.KINDS). No row, no email. Which events
    they actually hear about is still limited to the units they may see: the choice never widens access."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "alert_preferences"
        constraints = [models.UniqueConstraint(fields=["user", "kind"], name="alertpref_user_kind_uniq")]


class AlertLog(models.Model):
    """Remembers which alerts were already sent, so a condition that lasts (a tracker that stays silent) is mailed once, not at every check."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20)
    key = models.CharField(max_length=120)
    sent_at = models.DateTimeField(auto_now_add=True)
    recipients = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "alert_log"
        ordering = ["-sent_at"]
        constraints = [models.UniqueConstraint(fields=["kind", "key"], name="alertlog_kind_key_uniq")]
