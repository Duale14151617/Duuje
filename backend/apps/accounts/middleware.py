import time

from django.conf import settings
from django.contrib.auth import logout


class SessionEpochMiddleware:
    """Reject sessions created before the user's last disable / role change / password change."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            expired = int(time.time()) - int(request.session.get("login_at", 0)) > settings.SESSION_ABSOLUTE_SECONDS
            if request.session.get("auth_epoch") != user.auth_epoch or not user.is_active or expired:
                logout(request)
        return self.get_response(request)
