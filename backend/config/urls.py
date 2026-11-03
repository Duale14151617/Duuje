from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path

from apps.core.middleware import get_correlation_id


def serve_frontend(request, *args, **kwargs):
    """Serve the React SPA for non-API routes in the single-origin Render demo."""
    index = Path(settings.BASE_DIR) / "frontend_dist" / "index.html"
    if not index.is_file():
        raise Http404("Frontend build is missing")
    return FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")

def server_error(request):
    return JsonResponse(
        {"code": "server_error", "detail": "Unexpected error.", "correlation_id": get_correlation_id()},
        status=500,
    )


def not_found(request, exception=None):
    return JsonResponse({"code": "not_found", "detail": "Not found."}, status=404)


handler500 = "config.urls.server_error"
handler404 = "config.urls.not_found"

urlpatterns = [
    path("api/v1/", include("config.api_v1")),
    path("", serve_frontend),
    re_path(r"^(?!api/).*$", serve_frontend),
]
