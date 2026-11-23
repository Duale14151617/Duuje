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


@receiver(post_save, sender=OrganizationalUnit, dispatch_uid="org_urur_jail_center")
def give_new_ururs_a_jail_center(sender, instance, created=False, raw=False, **kwargs):
    """A new Urur (battalion) gets a guardroom record in the custody module, NOT VERIFIED until an authorised person checks it on site."""
    from django.conf import settings

    if not settings.CUSTODY_ENABLED or raw or not created or not instance.unit_type_id or instance.unit_type.code != "URUR":
        return
    from apps.detention.facilities import ensure_jail_center

    ensure_jail_center(instance)
