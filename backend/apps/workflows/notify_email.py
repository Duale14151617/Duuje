"""Optional email alert when in-app notifications arrive. The notification itself stays in the app; the mail only points to it.

Nothing about the subject matter is mailed (no names, titles or unit): a mailbox is a weaker place than the app, and what the
recipient may see is re-checked in the app when they open it. A failure here never blocks the action that caused it.
"""
import logging

from django.conf import settings
from django.core.cache import cache

from apps.core.mailer import send_background

log = logging.getLogger(__name__)


def email_new(recipients):
    """Mail each opted-in recipient with a verified address, at most once per NOTIFICATION_EMAIL_MIN_MINUTES."""
    if not settings.NOTIFICATION_EMAILS_ENABLED:
        return
    from .models import Notification  # local import: models import this module's callers
    seen = set()
    for user in recipients:
        try:
            if user is None or user.pk in seen:
                continue
            seen.add(user.pk)
            if not (user.is_active and user.notify_email and user.email and user.email_verified_at):
                continue
            if not cache.add(f"notif-mail:{user.pk}", 1, timeout=max(1, settings.NOTIFICATION_EMAIL_MIN_MINUTES) * 60):
                continue  # already mailed recently; the app shows the rest
            unread = Notification.objects.filter(recipient=user, read_at__isnull=True).count()
            link = f"\n\nOpen it here: {settings.SITE_URL}/notifications" if settings.SITE_URL else ""
            send_background(user.email, "ARMY HQ: you have new notifications",
                            f"You have {unread} unread notification{'s' if unread != 1 else ''} waiting in the system.{link}\n\n"
                            "For your security this message does not include any details. Sign in to read them.\n"
                            "You can stop these emails on your Account page.")
        except Exception:
            log.exception("notification email failed")
