import contextvars
import uuid

_correlation_id = contextvars.ContextVar("correlation_id", default="")


def get_correlation_id():
    return _correlation_id.get()


class CorrelationIdMiddleware:
    """Attach a correlation ID to every request, log line, audit event and response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        ok = incoming and len(incoming) <= 64 and incoming.replace("-", "").isalnum()
        cid = incoming if ok else uuid.uuid4().hex
        token = _correlation_id.set(cid)
        request.correlation_id = cid
        try:
            response = self.get_response(request)
        finally:
            _correlation_id.reset(token)
        response["X-Request-ID"] = cid
        return response


class SecurityHeadersMiddleware:
    """Defence-in-depth headers. API responses are never cached and may not be framed or scripted."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response.setdefault("Cache-Control", "no-store")
            response.setdefault("Pragma", "no-cache")
            response.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response


class RequestSizeLimitMiddleware:
    """Reject oversized bodies before anything parses them (CSV imports are capped separately at 1 MB)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import JsonResponse
        length = request.META.get("CONTENT_LENGTH") or "0"
        try:
            too_big = int(length) > settings.MAX_REQUEST_BYTES
        except ValueError:
            too_big = True
        if too_big:
            return JsonResponse({"code": "payload_too_large", "detail": "Request too large."}, status=413)
        return self.get_response(request)
