from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OrganizationalUnit


@receiver(post_save, sender=OrganizationalUnit, dispatch_uid="org_standard_departments")
def establish_departments_for_new_units(sender, instance, raw=False, **kwargs):
    """A new (or re-typed) headquarters, region, regional command, brigade or battalion is ready with the standard
    departments straight away. Existing rows are never touched, so a retired department stays retired."""
    if raw:
        return
    from . import profiles

    if profiles.qualifies_for_standard_departments(instance):
        profiles.establish_standard_departments(instance)
