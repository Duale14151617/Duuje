"""Sensitive personnel profile: photo, blood type, weapon ID, DOB, emergency contact. Encrypted at rest."""
import hashlib
import hmac
import json
import re
from datetime import date
from io import BytesIO

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image, ImageOps
from rest_framework import serializers

from apps.core import crypto
from apps.core.errors import field_error

from .models import Personnel, PersonnelProfile
from .services import PHONE_RE

BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
GENDERS = ["male", "female"]
WEAPON_RE = re.compile(r"^[A-Za-z0-9/-]{3,32}$")
# Emergency contact / guardian NAME: letters only (any script), with spaces, dots, apostrophes and hyphens between words. No digits.
CONTACT_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ .'\u2019-]+[^\W\d_]+)*\.?$")
# Emergency contact PHONE: digits only, optional leading +.
CONTACT_PHONE_RE = re.compile(r"^\+?[0-9]{6,15}$")
FIELDS = ["blood_type", "gender", "weapon_id", "date_of_birth", "enlistment_date", "home_district",
          "emergency_contact_name", "emergency_contact_phone"]
PHOTO_MAX_BYTES = 5 * 1024 * 1024
PHOTO_SIZE = (360, 450)  # portrait, ID-photo proportions


class ProfileSerializer(serializers.Serializer):
    blood_type = serializers.ChoiceField(choices=BLOOD_TYPES, required=False, allow_blank=True)
    gender = serializers.ChoiceField(choices=GENDERS, required=False, allow_blank=True)
    weapon_id = serializers.CharField(max_length=32, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    enlistment_date = serializers.DateField(required=False, allow_null=True)
    home_district = serializers.CharField(max_length=120, required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    emergency_contact_phone = serializers.CharField(max_length=24, required=False, allow_blank=True)

    def validate_weapon_id(self, value):
        value = value.strip()
        if value and not WEAPON_RE.match(value):
            raise serializers.ValidationError("Invalid weapon ID.", code="weapon_id_invalid")
        return value

    def validate_emergency_contact_name(self, value):
        value = " ".join(value.split())
        if value and not CONTACT_NAME_RE.match(value):
            raise serializers.ValidationError("Use letters only (no numbers).", code="name_letters_only")
        return value

    def validate_emergency_contact_phone(self, value):
        value = value.strip()
        if value and not CONTACT_PHONE_RE.match(value):
            raise serializers.ValidationError("Use numbers only.", code="phone_digits_only")
        return value

    def validate_date_of_birth(self, value):
        if value and not (date(1900, 1, 1) <= value < date.today()):
            raise serializers.ValidationError("Invalid date of birth.", code="date_invalid")
        return value

    def validate_enlistment_date(self, value):
        if value and (value > date.today() or value < date(1950, 1, 1)):
            raise serializers.ValidationError("Invalid enlistment date.", code="date_invalid")
        return value


def _weapon_key(weapon_id):
    if not weapon_id:
        return None
    msg = weapon_id.strip().upper().encode()
    return hmac.new(settings.FIELD_ENCRYPTION_KEY.encode(), msg, hashlib.sha256).hexdigest()


def _load(profile):
    if profile is None or not profile.data_enc:
        return {}
    return json.loads(crypto.decrypt(profile.data_enc))


def read(person: Personnel) -> dict:
    profile = PersonnelProfile.objects.filter(pk=person.pk).first()
    data = _load(profile)
    out = {f: data.get(f, None if f.endswith("_date") or f == "date_of_birth" else "") for f in FIELDS}
    out["has_photo"] = bool(profile and profile.photo_enc)
    out["photo_updated_at"] = profile.photo_updated_at.isoformat() if profile and profile.photo_updated_at else None
    return out


def save(person: Personnel, changes: dict) -> list:
    """Merge validated changes into the encrypted blob. Returns the names of the fields that were sent."""
    try:
        with transaction.atomic():
            profile, _ = PersonnelProfile.objects.select_for_update().get_or_create(personnel=person)
            data = _load(profile)
            for name, value in changes.items():
                if isinstance(value, date):
                    value = value.isoformat()
                if value in ("", None):
                    data.pop(name, None)
                else:
                    data[name] = value
            key = _weapon_key(data.get("weapon_id", ""))
            if key and PersonnelProfile.objects.filter(weapon_key=key).exclude(pk=person.pk).exists():
                raise field_error("weapon_id", "weapon_id_taken", "This weapon ID is already assigned to someone else.")
            profile.data_enc = crypto.encrypt(json.dumps(data)) if data else ""
            profile.weapon_key = key
            profile.save()
    except IntegrityError:
        raise field_error("weapon_id", "weapon_id_taken", "This weapon ID is already assigned to someone else.")
    return sorted(changes)


def process_photo(upload) -> bytes:
    """Validate and normalise an uploaded image: real image, EXIF stripped, cropped to a 4:5 portrait JPEG."""
    if upload.size > PHOTO_MAX_BYTES:
        raise field_error("photo", "photo_too_large", "The photo must be under 5 MB.")
    try:
        probe = Image.open(upload)
        probe.verify()
        upload.seek(0)
        img = Image.open(upload)
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError("unsupported format")
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:  # not an image, corrupt, decompression bomb, unsupported format
        raise field_error("photo", "photo_invalid", "Upload a JPEG, PNG or WebP photo.")
    img = ImageOps.fit(img, PHOTO_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.3))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)  # new JPEG: no metadata carried over
    return buf.getvalue()


def save_photo(person: Personnel, jpeg: bytes) -> None:
    with transaction.atomic():
        profile, _ = PersonnelProfile.objects.select_for_update().get_or_create(personnel=person)
        profile.photo_enc = crypto.encrypt_bytes(jpeg)
        profile.photo_updated_at = timezone.now()
        profile.save()


def read_photo(person: Personnel):
    profile = PersonnelProfile.objects.filter(pk=person.pk).only("photo_enc").first()
    if profile is None or not profile.photo_enc:
        return None
    return crypto.decrypt_bytes(profile.photo_enc)
