from django.db.models import F
from django.utils import timezone
from .errors import field_error

from .exceptions import VersionConflict


def require_version(data):
    """Return the client-supplied version or raise a validation error."""
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise field_error("version", "version_required", "Version is required.")
    return version


def versioned_update(instance, changes, expected_version):
    """Compare-and-swap update. Raises VersionConflict if someone else saved first."""
    model = type(instance)
    values = dict(changes)
    values["version"] = F("version") + 1
    values["updated_at"] = timezone.now()
    updated = model.objects.filter(pk=instance.pk, version=expected_version).update(**values)
    if not updated:
        raise VersionConflict()
    instance.refresh_from_db()
    return instance
