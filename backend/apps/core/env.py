"""Environment variables of this deployment.

The names are POLICEHQ_*. The older ARMYHQ_* names (and the even older ARMYHQ_DEMO_* ones) keep working, so a deployment that was
set up under them, such as the Render dashboard, needs no change. The new name wins when both are set. An empty value counts as
not set, so a blank new variable (for example one a blueprint creates without a value) never hides the old one.

Plain Python on purpose: config/settings.py imports this before Django is configured.
"""
import os

PREFIXES = ("POLICEHQ_", "ARMYHQ_")


def get(suffix, default="", legacy=()):
    """Value of POLICEHQ_<suffix>, else ARMYHQ_<suffix>, else ARMYHQ_<each legacy suffix>, else `default`."""
    for name in [p + suffix for p in PREFIXES] + ["ARMYHQ_" + s for s in legacy]:
        value = os.environ.get(name)
        if value is not None and value != "":
            return value
    return default


def get_bool(suffix, default=False, legacy=()):
    return get(suffix, str(default), legacy).strip().lower() in ("1", "true", "yes", "on")
