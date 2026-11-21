"""One in-app notification per person per day saying how many dated items are waiting ("Due soon"). Counts only, no names: what the
person may open is checked again when they open the page. Safe to call as often as you like: a person already told today is skipped."""
import logging

from django.utils import timezone

from apps.accounts.models import RoleAssignment, User
from apps.workflows.models import Notification
from apps.workflows.notify_email import email_new

from .due import due_soon

log = logging.getLogger(__name__)
KIND = "due_digest"


def send_due_digests(now=None):
    now = now or timezone.now()
    start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    told = set(Notification.objects.filter(kind=KIND, created_at__gte=start).values_list("recipient_id", flat=True))
    ids = set(RoleAssignment.objects.effective().values_list("user_id", flat=True)) - told
    sent = []
    for user in User.objects.filter(pk__in=ids, is_active=True):
        try:
            if due_soon(user, now)["total"] > 0:
                sent.append(user)
        except Exception:  # one person's problem must not stop everyone else's digest
            log.exception("due digest failed for %s", user.pk)
    Notification.objects.bulk_create([Notification(recipient=u, kind=KIND) for u in sent])
    email_new(sent)
    return len(sent)
