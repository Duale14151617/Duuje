"""Leave notifications: approvers hear about a pending request, the requester hears how it was decided.

A notification only says that something happened; what the recipient may still see of it is checked when they read it
(see NotificationSerializer), so a change of scope after sending reveals nothing. A failure here never blocks the leave action.
"""
import logging

from apps.workflows.models import Notification
from apps.workflows.notify_email import email_new
from apps.workflows.services import reviewers_for

log = logging.getLogger(__name__)


def _send(kind, leave, users):
    try:
        seen, rows = set(), []
        for u in users:
            if u is not None and u.pk not in seen and u.is_active:
                seen.add(u.pk)
                rows.append(Notification(recipient=u, kind=kind, leave_request=leave))
        Notification.objects.bulk_create(rows)
        email_new([r.recipient for r in rows])
    except Exception:  # a notification must never undo the leave action itself
        log.exception("leave notification failed")


def _requesters(leave):
    """The person who asked, and the person the leave is for when they have a login of their own."""
    from apps.accounts.models import User
    ids = {leave.requested_by_id}
    if leave.personnel.account_id:
        ids.add(leave.personnel.account_id)
    return list(User.objects.filter(pk__in=[i for i in ids if i], is_active=True))


def pending(leave):
    """A request was made: tell everyone who can approve it for this unit, except the person who made it."""
    exclude = {leave.requested_by_id, leave.personnel.account_id} - {None}
    _send("leave_pending", leave, reviewers_for(leave.org_unit, exclude_ids=exclude, code="leave.approve"))


def decided(leave, kind, decider):
    """Approved or rejected: tell the requester (and the person, if different), never the decider."""
    _send(kind, leave, [u for u in _requesters(leave) if u.pk != getattr(decider, "pk", None)])


def cancelled(leave, canceller):
    """Cancelled by the requester: tell the approvers. Cancelled by someone else: tell the requester."""
    if canceller.pk in {leave.requested_by_id, leave.personnel.account_id}:
        exclude = {canceller.pk}
        _send("leave_cancelled", leave, reviewers_for(leave.org_unit, exclude_ids=exclude, code="leave.approve"))
    else:
        _send("leave_cancelled", leave, [u for u in _requesters(leave) if u.pk != canceller.pk])
