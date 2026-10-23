from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


class VersionConflict(APIException):
    status_code = 409
    default_detail = "This record was changed by someone else. Reload and try again."
    default_code = "version_conflict"


def api_exception_handler(exc, context):
    """Uniform error body: {code, detail, errors?}. Clients translate by code."""
    # DRF converts Django's Http404 / PermissionDenied internally but hands *this* handler the original exception,
    # which has no get_codes(); without this every get_object() 404 (an out-of-scope or unknown id) ended in a 500.
    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound(*(exc.args))
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied(*(exc.args))
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, ValidationError):
        response.data = {
            "code": "validation_error",
            "detail": "Validation failed.",
            "errors": exc.get_full_details(),
        }
    else:
        codes = exc.get_codes()
        response.data = {
            "code": codes if isinstance(codes, str) else "error",
            "detail": str(exc.detail) if isinstance(exc.detail, str) else "Request failed.",
        }
    return response
