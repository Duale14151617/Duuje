"""Security alert emails to the people who own the system.

Recipients: ARMYHQ_ALERT_EMAILS (comma list) plus the verified email of every active super administrator. Unlike the privileged-grant
alert, the person who caused the event is NOT excluded: if a thief used the owner's session, the owner is the one who must hear
about it. Alerts never raise, never block the request, and never carry secrets (no passwords, codes or tokens).
"""
import logging
import threading

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

log = logging.getLogger("armyhq.security")


def recipients():
    from .models import RoleAssignment, User
    from .scope import FULL_ACCESS
    addresses = {a.strip() for a in getattr(settings, "SECURITY_ALERT_EMAILS", []) if a and a.strip()}
    owner_ids = RoleAssignment.objects.effective().filter(role__permissions__code=FULL_ACCESS).values_list("user_id", flat=True)
    addresses |= set(User.objects.filter(pk__in=list(owner_ids), is_active=True, email_verified_at__isnull=False)
                     .exclude(email="").values_list("email", flat=True))
    return sorted(addresses)


def _deliver(subject, body, to):
    for address in to:
        try:
            send_mail(subject, body, None, [address], fail_silently=False)
        except Exception:  # an unreachable mail provider must never affect the action being reported
            log.warning("security alert email could not be sent")


def notify(event, summary, *, request=None, actor=None):
    try:
        to = recipients()
        if not to:
            return
        from apps.audit.services import client_ip
        ip = client_ip(request) if request is not None else None
        lines = [summary, "", f"Event: {event}", f"Time (UTC): {timezone.now():%Y-%m-%d %H:%M:%S}"]
        if actor is not None:
            lines.append(f"Account: {actor.username}")
        if ip:
            lines.append(f"Address: {ip}")
        lines += ["", "If you do not recognise this, sign in, review the audit log, and reset the account's credentials now."]
        subject, body = f"Puntland Defence Forces HQ security alert: {event}", "\n".join(lines)

        def dispatch():
            if getattr(settings, "SECURITY_ALERTS_ASYNC", False):
                threading.Thread(target=_deliver, args=(subject, body, to), daemon=True).start()
            else:
                _deliver(subject, body, to)

        transaction.on_commit(dispatch)
    except Exception:
        log.warning("security alert could not be prepared")
