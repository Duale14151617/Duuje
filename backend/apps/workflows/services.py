"""Workflow rules. The server decides actor, scope, ownership, separation of duties and legality of every transition;
nothing about identity or status is read from the client payload."""
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from apps.accounts import scope
from apps.accounts.models import RoleAssignment
from apps.audit.services import record
from apps.core.concurrency import versioned_update
from apps.core.errors import field_error
from apps.core.exceptions import VersionConflict

from .models import ApprovalAction, Notification, Submission, SubmissionRevision

S = Submission.Status
EDITABLE = {S.DRAFT, S.RETURNED, S.AMENDED}
# action -> (allowed from-states, resulting state)
TRANSITIONS = {
    "submit": (EDITABLE, S.SUBMITTED),
    "start_review": ({S.SUBMITTED}, S.UNDER_REVIEW),
    "approve": ({S.UNDER_REVIEW}, S.APPROVED),
    "reject": ({S.UNDER_REVIEW}, S.REJECTED),
    "return": ({S.UNDER_REVIEW}, S.RETURNED),
    "amend": ({S.APPROVED}, S.AMENDED),
}
REVIEW_ACTIONS = {"start_review", "approve", "reject", "return"}
OWNER_ACTIONS = {"submit", "amend"}
COMMENT_REQUIRED = {"reject", "return", "amend"}


class InvalidTransition(APIException):
    status_code = 409
    default_detail = "That action is not allowed in the current state."
    default_code = "invalid_transition"


class NotEditable(InvalidTransition):
    default_code = "not_editable"


def submitters_of(sub):
    ids = set(sub.revisions.values_list("submitted_by_id", flat=True))
    ids.add(sub.submitter_id)
    ids.discard(None)
    return ids


def self_review(user, sub):
    """True when `user` is (or ever was) the submitter and the type forbids reviewing your own work."""
    return sub.report_type.separation_of_duties and user.pk in submitters_of(sub)


def capabilities(user, sub):
    """What this user could do right now (for the UI). The server re-checks on every action."""
    unit = sub.org_unit
    owner = sub.submitter_id == user.pk
    can_submit_scope = scope.can(user, "reports.submit", unit=unit)
    can_review_scope = scope.can(user, "reports.review", unit=unit) and not self_review(user, sub)
    return {
        "edit": owner and can_submit_scope and sub.status in EDITABLE,
        "submit": owner and can_submit_scope and sub.status in EDITABLE,
        "start_review": can_review_scope and sub.status == S.SUBMITTED,
        "decide": can_review_scope and sub.status == S.UNDER_REVIEW,
        "amend": owner and can_submit_scope and sub.status == S.APPROVED,
    }


def validate_completeness(sub):
    if not sub.title.strip():
        raise field_error("title", "incomplete_submission")
    keys = sub.report_type.figure_keys
    missing = [k for k in keys if k not in (sub.figures or {})]
    if missing:
        raise field_error("figures", "incomplete_submission")
    if not keys and not sub.body.strip():
        raise field_error("body", "incomplete_submission")


def reviewers_for(unit, exclude_ids=()):
    seen, users = set(), []
    qs = (RoleAssignment.objects.effective().filter(role__permissions__code="reports.review")
          .select_related("user", "org_unit", "branch").distinct())
    for a in qs:
        if a.user_id in seen or a.user_id in exclude_ids or not scope.covers(a, unit):
            continue
        seen.add(a.user_id)
        users.append(a.user)
    return users


def notify(kind, sub, recipients):
    Notification.objects.bulk_create([Notification(recipient=u, kind=kind, submission=sub) for u in recipients])


def perform_transition(request, sub, action, expected_version, comment=""):
    user = request.user
    allowed_from, target = TRANSITIONS[action]
    if sub.version != expected_version:
        raise VersionConflict()
    if sub.status not in allowed_from:
        raise InvalidTransition()
    if action in OWNER_ACTIONS and sub.submitter_id != user.pk:
        record(f"report.{action}", request=request, outcome="denied", entity_type="submission", entity_id=sub.pk,
               metadata={"reason": "not_owner"})
        raise PermissionDenied("Only the submitter can do this.", code="not_owner")
    if action in REVIEW_ACTIONS and self_review(user, sub):
        # Written before raising and outside any transaction, so the denial is kept.
        record(f"report.{action}", request=request, outcome="denied", entity_type="submission", entity_id=sub.pk,
               metadata={"reason": "self_review", "submitter": str(sub.submitter_id)})
        raise PermissionDenied("You cannot review a report you submitted.", code="self_review_not_allowed")
    if action in COMMENT_REQUIRED and not comment.strip():
        raise field_error("comment", "comment_required")
    if action == "submit":
        validate_completeness(sub)

    now = timezone.now()
    with transaction.atomic():
        locked = Submission.objects.select_for_update().select_related("report_type", "org_unit").get(pk=sub.pk)
        if locked.version != expected_version:
            raise VersionConflict()
        if locked.status not in allowed_from:
            raise InvalidTransition()
        old_status = locked.status  # versioned_update() refreshes `locked` in place
        changes = {"status": target}
        revision_no = locked.current_revision
        verb = action
        if action == "submit":
            revision_no += 1
            verb = "resubmit" if locked.current_revision > 0 else "submit"
            SubmissionRevision.objects.create(
                submission=locked, revision_no=revision_no, title=locked.title, period_start=locked.period_start,
                period_end=locked.period_end, body=locked.body, figures=locked.figures,
                submitted_by=user, submitted_by_username=user.username)
            changes.update(current_revision=revision_no, submitted_at=now, reviewer=None, decided_at=None)
        elif action == "start_review":
            changes["reviewer"] = user
        elif action == "approve":
            rev = SubmissionRevision.objects.get(submission=locked, revision_no=locked.current_revision)
            changes.update(approved_revision=rev, reviewer=user, decided_at=now)
        elif action in ("reject", "return"):
            changes.update(reviewer=user, decided_at=now)
        updated = versioned_update(locked, changes, expected_version)
        ApprovalAction.objects.create(
            submission=updated, revision_no=revision_no, action=verb, from_status=old_status, to_status=target,
            actor=user, actor_username=user.username, comment=comment.strip()[:1000])
        record(f"report.{verb}", request=request, entity_type="submission", entity_id=updated.pk,
               metadata={"from": old_status, "to": target, "revision": revision_no,
                         "self_review": bool(action in REVIEW_ACTIONS and user.pk in submitters_of(updated))})
        if action in ("submit", "amend"):
            notify("resubmitted" if verb == "resubmit" else "submitted" if action == "submit" else "amended",
                   updated, reviewers_for(updated.org_unit, exclude_ids={user.pk}))
        else:
            notify({"start_review": "review_started", "approve": "approved", "reject": "rejected",
                    "return": "returned"}[action], updated, [updated.submitter] if updated.submitter else [])
    return updated


def date_ok(start, end):
    return start is not None and end is not None and end >= start


def build_summary(user, params, code="reports.summary"):
    """Totals of *approved* content only, limited to the caller's `reports.summary` scope."""
    q = scope.unit_scope_q(user, code, "org_unit__")
    empty = {"consolidated": {"submissions": 0, "totals": {}}, "regions": []}
    if q is None:
        return empty
    qs = Submission.objects.filter(q, approved_revision__isnull=False).select_related("approved_revision", "org_unit")
    if params.get("report_type"):
        qs = qs.filter(report_type=params["report_type"])
    if params.get("from"):
        qs = qs.filter(approved_revision__period_end__gte=params["from"])
    if params.get("to"):
        qs = qs.filter(approved_revision__period_start__lte=params["to"])
    if params.get("unit_path"):
        qs = qs.filter(org_unit__path__startswith=params["unit_path"])
    rows = list(qs[:5001])
    if len(rows) > 5000:
        raise field_error("filters", "summary_too_large")
    from apps.organization.models import OrganizationalUnit
    regions = {str(r.pk): r for r in OrganizationalUnit.objects.filter(level="region")}
    grouped, total = {}, {"submissions": 0, "totals": {}}
    for s in rows:
        parts = s.org_unit.path.strip("/").split("/")
        rid = parts[1] if len(parts) > 1 else None
        rid = str(uuid.UUID(rid)) if rid else None
        bucket = grouped.setdefault(rid, {"submissions": 0, "totals": {}})
        for target in (bucket, total):
            target["submissions"] += 1
            for k, v in (s.approved_revision.figures or {}).items():
                if isinstance(v, int) and not isinstance(v, bool):
                    target["totals"][k] = target["totals"].get(k, 0) + v
    out = []
    for rid, bucket in grouped.items():
        r = regions.get(rid)
        out.append({"region": {"id": rid, "code": r.code if r else "", "name_en": r.name_en if r else "",
                               "name_so": r.name_so if r else ""}, **bucket})
    out.sort(key=lambda x: x["region"]["code"])
    return {"consolidated": total, "regions": out}
