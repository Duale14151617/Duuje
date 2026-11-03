from django.contrib.sessions.models import Session
from django.db.models import F
from django.utils import timezone

from apps.organization.models import OrganizationalUnit

from .models import RoleAssignment, User


def revoke_user_sessions(user):
    """Invalidate every session of `user` now (epoch bump) and delete stored sessions."""
    User.objects.filter(pk=user.pk).update(auth_epoch=F("auth_epoch") + 1)
    user.refresh_from_db(fields=["auth_epoch"])
    uid = str(user.pk)
    for s in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if s.get_decoded().get("_auth_user_id") == uid:
            s.delete()


def other_admins_exist(*, excluding_user_id=None, excluding_assignment_id=None):
    """Lock-out guard: is there another effective global user administrator?"""
    qs = RoleAssignment.objects.effective().filter(
        role__permissions__code="users.manage",
        org_unit__level=OrganizationalUnit.Level.HQ,
        branch__isnull=True,
    )
    if excluding_user_id:
        qs = qs.exclude(user_id=excluding_user_id)
    if excluding_assignment_id:
        qs = qs.exclude(pk=excluding_assignment_id)
    return qs.exists()
