"""Catalogue rules: every change is audited, versioned, and puts a verified entry back to 'unverified' when the facts change."""
import hashlib
import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record
from apps.core import crypto
from apps.core.concurrency import VersionConflict
from apps.core.errors import field_error
from apps.vehicles.models import VehicleCategory

from .models import EquipmentItem, EquipmentPhoto, EquipmentSpec, MountedWeaponCategory

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SPECS = 40
FACT_FIELDS = {"name": 120, "description": 1000, "manufacturer": 120, "source_ref": 300}


def sniff_image(data):
    """Image type by content, never by the client-supplied name or type."""
    return "image/png" if data.startswith(b"\x89PNG") else "image/jpeg" if data[:3] == b"\xff\xd8\xff" else None


def read_image(upload):
    if upload is None:
        raise field_error("file", "required", "Choose a file.")
    data = upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise field_error("file", "too_large", "The file is larger than 5 MB.")
    ctype = sniff_image(data[:8])
    if ctype is None:
        raise field_error("file", "unsupported_type", "Only JPEG or PNG photographs are accepted.")
    return data, ctype


def _actor(request):
    u = getattr(request, "user", None)
    return u if u is not None and u.is_authenticated else None


def _name(request):
    return getattr(_actor(request), "username", "") or ""


def _text(d, name, limit, required=False):
    v = d.get(name)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise field_error(name, "required", "This field is required.")
    if len(v) > limit:
        raise field_error(name, "too_long", "Too long.")
    return v


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60]


def _lock(pk, version):
    item = EquipmentItem.objects.select_for_update().get(pk=pk)
    if item.version != version:
        raise VersionConflict()
    return item


def _classify(d, kind, item=None):
    """Resolve the classification that belongs to the kind: a vehicle category for a vehicle model, a mounted-weapon category otherwise."""
    if kind == EquipmentItem.Kind.VEHICLE_MODEL:
        key = d.get("vehicle_category") if "vehicle_category" in d or item is None else None
        if key is None and item is not None:
            return item.vehicle_category, None
        cat = VehicleCategory.objects.filter(code=str(key), active=True).first() or (VehicleCategory.objects.filter(pk=key, active=True).first() if _is_uuid(key) else None)
        if cat is None:
            raise field_error("vehicle_category", "category_unknown", "Choose an active vehicle classification.")
        return cat, None
    key = d.get("weapon_category") if "weapon_category" in d or item is None else None
    if key is None and item is not None:
        return None, item.weapon_category
    cat = MountedWeaponCategory.objects.filter(code=str(key), active=True).first() or (MountedWeaponCategory.objects.filter(pk=key, active=True).first() if _is_uuid(key) else None)
    if cat is None:
        raise field_error("weapon_category", "category_unknown", "Choose an active mounted-weapon category.")
    return None, cat


def _is_uuid(v):
    import uuid
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False


def snapshot(i):
    return {"name": i.name, "kind": i.kind, "vehicle_category": i.vehicle_category.code if i.vehicle_category_id else None,
            "weapon_category": i.weapon_category.code if i.weapon_category_id else None, "manufacturer": i.manufacturer,
            "description": i.description, "source_ref": i.source_ref, "verification": i.verification, "active": i.active}


@transaction.atomic
def create_item(request, d):
    kind = d.get("kind")
    if kind not in {k.value for k in EquipmentItem.Kind}:
        raise field_error("kind", "invalid_kind", "Choose vehicle model or mounted weapon.")
    name = _text(d, "name", 120, required=True)
    vcat, wcat = _classify(d, kind)
    code = slug(_text(d, "code", 60) or name)
    if not code or EquipmentItem.objects.filter(code=code).exists():
        raise field_error("code", "code_in_use", "An entry with this name or code already exists.")
    try:
        item = EquipmentItem.objects.create(
            code=code, name=name, kind=kind, vehicle_category=vcat, weapon_category=wcat, description=_text(d, "description", 1000),
            manufacturer=_text(d, "manufacturer", 120), source_ref=_text(d, "source_ref", 300), created_by_username=_name(request))
    except IntegrityError:
        raise field_error("code", "code_in_use", "An entry with this name or code already exists.")
    record("equipment.create", request=request, entity_type="equipment_item", entity_id=item.pk, metadata={"after": snapshot(item)})
    return item


@transaction.atomic
def edit_item(request, item, d, version):
    i = _lock(item.pk, version)
    before = snapshot(i)
    for k, n in FACT_FIELDS.items():
        if k in d:
            setattr(i, k, _text(d, k, n, required=(k == "name")))
    if "vehicle_category" in d or "weapon_category" in d:
        i.vehicle_category, i.weapon_category = _classify(d, i.kind, i)
    if "active" in d:
        i.active = bool(d["active"])
    after = snapshot(i)
    if after == before:
        raise field_error("body", "nothing_to_change", "Nothing to change.")
    facts_changed = any(before[k] != after[k] for k in ("name", "vehicle_category", "weapon_category", "manufacturer", "description"))
    if facts_changed and i.verification == EquipmentItem.Verification.VERIFIED:  # a changed description is no longer what was checked
        i.verification, i.verified_at, i.verified_by_username = EquipmentItem.Verification.UNVERIFIED, None, ""
        i.verification_note = "Facts changed after verification"
    i.version += 1
    i.save()
    record("equipment.update", request=request, entity_type="equipment_item", entity_id=i.pk, metadata={"before": before, "after": snapshot(i)})
    return i


@transaction.atomic
def verify_item(request, item, d, version):
    i = _lock(item.pk, version)
    result = d.get("result")
    if result not in ("verified", "needs_review"):
        raise field_error("result", "invalid_result", "Choose verified or needs review.")
    if i.created_by_username and i.created_by_username == _name(request) and result == "verified":
        raise field_error("result", "own_entry", "A different person must verify an entry you entered.")
    note = _text(d, "note", 300, required=(result == "needs_review"))
    before = i.verification
    i.verification, i.verification_note = result, note
    i.verified_by_username, i.verified_at = _name(request), timezone.now()
    i.version += 1
    i.save()
    record("equipment.verify", request=request, entity_type="equipment_item", entity_id=i.pk, metadata={"code": i.code, "before": before, "after": result, "note": note})
    return i


@transaction.atomic
def set_specs(request, item, d, version):
    i = _lock(item.pk, version)
    rows = d.get("specs")
    if not isinstance(rows, list) or len(rows) > MAX_SPECS:
        raise field_error("specs", "invalid", f"Send a list of at most {MAX_SPECS} specification lines.")
    clean = []
    for n, r in enumerate(rows):
        r = r if isinstance(r, dict) else {}
        clean.append({"name": _text(r, "name", 60, required=True), "value": _text(r, "value", 200, required=True), "unit": _text(r, "unit", 20), "sort_order": n})
    before = [{"name": s.name, "value": s.value, "unit": s.unit} for s in i.specs.all()]
    i.specs.all().delete()
    EquipmentSpec.objects.bulk_create([EquipmentSpec(item=i, **c) for c in clean])
    if i.verification == EquipmentItem.Verification.VERIFIED and before != [{k: c[k] for k in ("name", "value", "unit")} for c in clean]:
        i.verification, i.verified_at, i.verified_by_username, i.verification_note = EquipmentItem.Verification.UNVERIFIED, None, "", "Specifications changed after verification"
    i.version += 1
    i.save()
    record("equipment.specs", request=request, entity_type="equipment_item", entity_id=i.pk, metadata={"before": before, "after": clean})
    return i


@transaction.atomic
def add_photo(request, item, caption, upload):
    data, ctype = read_image(upload)
    caption = (caption or "").strip()[:150]
    p = EquipmentPhoto.objects.create(item=item, caption=caption, content_enc=crypto.encrypt_bytes(data), content_type=ctype, size_bytes=len(data),
                                      sha256=hashlib.sha256(data).hexdigest(), uploaded_by_username=_name(request))
    record("equipment.photo_add", request=request, entity_type="equipment_item", entity_id=item.pk, metadata={"photo": str(p.pk), "caption": caption})
    return p


@transaction.atomic
def withdraw_photo(request, photo, reason):
    if photo.withdrawn_at:
        raise field_error("photo", "already_withdrawn", "Already withdrawn.")
    if not (reason or "").strip():
        raise field_error("reason", "required", "Give a reason.")
    photo.withdrawn_at, photo.withdrawn_by_username, photo.withdrawn_reason = timezone.now(), _name(request), reason.strip()[:300]
    photo.save(update_fields=["withdrawn_at", "withdrawn_by_username", "withdrawn_reason"])
    record("equipment.photo_withdraw", request=request, entity_type="equipment_item", entity_id=photo.item_id, metadata={"photo": str(photo.pk), "reason": photo.withdrawn_reason})
    return photo
