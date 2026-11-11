import uuid


def region_id(path):
    """Region UUID (str) from a unit's materialised path, or None for the HQ node itself."""
    parts = path.strip("/").split("/")
    return str(uuid.UUID(parts[1])) if len(parts) > 1 else None
