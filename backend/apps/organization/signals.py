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


@receiver(post_save, sender=OrganizationalUnit, dispatch_uid="org_police_station_kooxo")
def give_new_police_stations_their_kooxo(sender, instance, created=False, raw=False, **kwargs):
    """Every new police station starts with two Kooxo (add more by hand). Only fires for the POLICE_STATION unit type."""
    if raw or not created or not instance.unit_type_id or instance.unit_type.code != "POLICE_STATION":
        return
    from . import police_structure
    from .models import UnitType

    police_structure.create_kooxo_for_station(OrganizationalUnit, UnitType, instance)


@receiver(post_save, sender=OrganizationalUnit, dispatch_uid="org_police_station_jail_center")
def give_new_police_stations_a_jail_center(sender, instance, created=False, raw=False, **kwargs):
    """Every new police station gets its jail center (the station's own lock-up) so people can be booked into it straight away."""
    if raw or not created or not instance.unit_type_id or instance.unit_type.code != "POLICE_STATION":
        return
    from apps.detention.facilities import ensure_jail_center

    ensure_jail_center(instance)
