from rest_framework.permissions import BasePermission

from apps.audit.services import record

from . import scope
from .security import restrictions


class IsFullyAuthenticated(BasePermission):
    """Signed in, active, and not confined to password-change / MFA-enrolment screens."""

    code = "permission_denied"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if getattr(view, "allow_restricted", False):
            return True
        if restrictions(user):
            self.code = "restricted"
            self.message = "Complete the required account steps first."
            return False
        return True


class ScopedPermission(IsFullyAuthenticated):
    """Views declare permission_map = {action: (permission_code, mode)}.

    mode 'global': needs an unscoped (HQ) grant. 'any': needs the permission anywhere
    (the queryset then narrows). 'unit': like 'any', plus object-level scope check via
    view.scope_unit(obj). Actions not in the map are denied.
    """

    def _rule(self, view):
        return getattr(view, "permission_map", {}).get(getattr(view, "action", None))

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        rule = self._rule(view)
        allowed = False
        if rule:
            codes = (rule[0],) if isinstance(rule[0], str) else tuple(rule[0])
            mode = rule[1]
            allowed = any((scope.can(request.user, c) if mode == "global" else scope.has_anywhere(request.user, c))
                          for c in codes)
        if not allowed:
            record("access.denied", request=request, outcome="denied", entity_type=view.__class__.__name__,
                   metadata={"action": getattr(view, "action", None), "permission": (rule[0] if isinstance(rule[0], str) else "|".join(rule[0])) if rule else None})
        return allowed

    def has_object_permission(self, request, view, obj):
        rule = self._rule(view)
        if not rule:
            return False
        codes = (rule[0],) if isinstance(rule[0], str) else tuple(rule[0])
        if rule[1] == "unit":
            unit = view.scope_unit(obj)
            return any(scope.can(request.user, c, unit=unit) for c in codes)
        return True
