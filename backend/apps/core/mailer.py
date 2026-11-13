"""Outgoing email without making the web request wait for the mail provider.

Used where the reply must not depend on (or reveal) how long sending takes: password-reset and recovery codes, and notices. The message is
queued after the surrounding transaction commits (so a code is in the database before it is mailed) and sent by a small worker pool.
A failed send is logged and never reaches the requester. Inline when EMAIL_SEND_ASYNC is off (development and tests).
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

log = logging.getLogger("armyhq.mail")
_pool = None


def _executor():
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail")
    return _pool


def _send(subject, body, to):
    try:
        send_mail(subject, body, None, list(to), fail_silently=False)
        return True
    except Exception:
        log.warning("email could not be sent")
        return False


def send_background(address, subject, body):
    """Queue (or, when async is off, send) one email. Returns whether it was sent or queued; never raises."""
    if not getattr(settings, "EMAIL_SEND_ASYNC", False):
        return _send(subject, body, [address])
    transaction.on_commit(lambda: _executor().submit(_send, subject, body, [address]))
    return True
