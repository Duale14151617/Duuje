import uuid

from .errors import field_error


def uuid_param(request, name):
    """Return a query-string UUID (as str) or None; malformed values are a 400, not a 500."""
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise field_error(name, "invalid_id", "Invalid identifier.")
