"""Weapon register: serial-numbered weapons, personal custody, issue and return. Built on the restricted asset ledger.

* A weapon is an `Asset` in a weapons category (code starts with "weapon"); its unique serial number is the asset identifier.
* Quantity never lives here: counts per type, unit or status are derived from the register (see views.summary).
* Custody to a soldier is a separate, append-only layer (WeaponCustody). While a weapon is in custody its unit-level status shows
  "issued" (to the soldier's unit) and ordinary asset actions are refused, except reporting it missing or lost, which closes the custody.
"""
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.core.concurrency import VersionConflict, versioned_update
from apps.core.errors import field_error
from apps.logistics import services as logi
from apps.logistics.models import Asset
from apps.personnel.services import NOT_SERVING

from .models import WeaponCustody, WeaponDetail

PREFIX = "weapon"
CONDITIONS = {c.value for c in WeaponDetail.Condition}


def is_weapon_category(category):
    return category.code.startswith(PREFIX)


def effective_unit(asset):
    """The unit that currently holds the weapon: the unit it was issued to, otherwise its holding unit."""
    return asset.issued_to_unit or asset.org_unit


def open_custody(asset):
    return WeaponCustody.objects.filter(asset=asset, returned_at__isnull=True).select_related("personnel__rank", "personnel__org_unit").first()


def register(request, category, unit, serial, d):
    if not is_weapon_category(category):
        raise field_error("category", "not_a_weapon_category")
    serial = (serial or "").strip().upper()
    # A serial number identifies one weapon in the whole register, not just inside one category.
    if Asset.objects.filter(category__code__startswith=PREFIX, identifier=serial).exists():
        raise field_error("serial", "asset_duplicate")
    wtype = (d.get("weapon_type") or "").strip()
    if not wtype:
        raise field_error("weapon_type", "required")
    condition = d.get("condition") or "serviceable"
    if condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    with transaction.atomic():
        asset = logi.register_asset(request, category, unit, serial, (d.get("description") or "")[:200], weapon_register=True)
        WeaponDetail.objects.create(asset=asset, weapon_type=wtype[:60], make_model=(d.get("make_model") or "")[:120],
                                    caliber=(d.get("caliber") or "")[:40], condition=condition)
        record("weapon.register", request=request, entity_type="weapon", entity_id=asset.pk,
               metadata={"unit": str(unit.pk), "type": wtype[:60]})
    return asset


def issue(request, asset, person, condition, authority_ref, note, expected_version):
    user = request.user
    unit = effective_unit(asset)
    logi.authorize(request, unit, asset.category)
    if condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    if not (authority_ref or "").strip():
        raise field_error("authority_ref", "authorization_required")  # a documented authorization is mandatory
    if person.status in NOT_SERVING:
        raise field_error("personnel", "person_not_serving")
    if not person.org_unit.path.startswith(unit.path):
        raise field_error("personnel", "person_outside_unit")
    with transaction.atomic():
        locked = Asset.objects.select_for_update().get(pk=asset.pk)
        if locked.version != expected_version:
            raise VersionConflict()
        if WeaponCustody.objects.filter(asset=locked, returned_at__isnull=True).exists():
            raise field_error("asset", "weapon_already_in_custody")
        if locked.status not in ("in_stock", "issued"):
            raise field_error("asset", "weapon_not_available")
        if locked.weapon.condition == WeaponDetail.Condition.UNSERVICEABLE:
            raise field_error("asset", "weapon_unserviceable")
        before_status, before_unit = locked.status, locked.issued_to_unit
        custody = WeaponCustody.objects.create(
            asset=locked, personnel=person, issued_by_id=user.pk, issued_by_username=user.username,
            authority_ref=authority_ref.strip()[:150], issue_condition=condition, issue_note=(note or "")[:300],
            status_before=before_status, issued_unit_before=before_unit)
        updated = versioned_update(locked, {"status": "issued", "issued_to_unit": person.org_unit}, expected_version)
        WeaponDetail.objects.filter(pk=locked.pk).update(condition=condition)
        logi._event(user, updated, "custody_issue", before_status, "issued", None, person.org_unit,
                    f"Issued to {person.service_number or person.pk} ({authority_ref.strip()[:80]})")
        record("weapon.issued", request=request, entity_type="weapon", entity_id=updated.pk,
               metadata={"custody": str(custody.pk), "personnel": str(person.pk), "authority_ref": authority_ref.strip()[:150]})
    return updated


def give_back(request, asset, condition, note, expected_version):
    user = request.user
    logi.authorize(request, effective_unit(asset), asset.category)
    if condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    with transaction.atomic():
        locked = Asset.objects.select_for_update().get(pk=asset.pk)
        if locked.version != expected_version:
            raise VersionConflict()
        custody = WeaponCustody.objects.select_for_update().filter(asset=locked, returned_at__isnull=True).first()
        if custody is None:
            raise field_error("asset", "weapon_not_in_custody")
        restore_status = custody.status_before if custody.status_before in ("in_stock", "issued") else "in_stock"
        restore_unit = custody.issued_unit_before if restore_status == "issued" else None
        WeaponCustody.objects.filter(pk=custody.pk).update(
            returned_at=timezone.now(), returned_by_id=user.pk, returned_by_username=user.username,
            outcome="returned", return_condition=condition, return_note=(note or "")[:300])
        updated = versioned_update(locked, {"status": restore_status, "issued_to_unit": restore_unit}, expected_version)
        WeaponDetail.objects.filter(pk=locked.pk).update(condition=condition)
        logi._event(user, updated, "custody_return", "issued", restore_status, custody.personnel.org_unit, restore_unit,
                    f"Returned by {custody.personnel.service_number or custody.personnel_id}, condition {condition}")
        record("weapon.returned", request=request, entity_type="weapon", entity_id=updated.pk,
               metadata={"custody": str(custody.pk), "condition": condition})
    return updated


def set_condition(request, asset, condition, note):
    logi.authorize(request, effective_unit(asset), asset.category)
    if condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition")
    old = asset.weapon.condition
    if old == condition:
        raise field_error("condition", "no_change")
    with transaction.atomic():
        WeaponDetail.objects.filter(pk=asset.pk).update(condition=condition)
        logi._event(request.user, asset, "condition", note=f"{old} -> {condition}. {(note or '')[:200]}".strip())
        record("weapon.condition", request=request, entity_type="weapon", entity_id=asset.pk,
               metadata={"from": old, "to": condition})


# ---- hooks called by the ordinary asset ledger (apps.logistics.services.change_asset) -----------------------------------
def guard_asset_change(asset, action):
    """A weapon in a soldier's custody cannot be moved, repaired or retired until it is returned. Only reporting it missing or
    lost is allowed, and that closes the custody (see close_custody_on_loss)."""
    if action not in ("missing", "lost") and WeaponCustody.objects.filter(asset=asset, returned_at__isnull=True).exists():
        raise field_error("asset", "asset_in_custody")


def close_custody_on_loss(asset, action, user):
    custody = WeaponCustody.objects.filter(asset=asset, returned_at__isnull=True).first()
    if custody is not None and action in ("missing", "lost"):
        WeaponCustody.objects.filter(pk=custody.pk).update(
            returned_at=timezone.now(), returned_by_id=user.pk, returned_by_username=user.username,
            outcome=action, return_note=f"Reported {action}")
