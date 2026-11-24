"""Account profile pictures: set by an administrator, shown in the header, Account page and user administration."""
from django.db import transaction

from apps.core import crypto

from .models import UserAvatar


def save_avatar(user, jpeg: bytes, by_username: str = "") -> None:
    with transaction.atomic():
        row, _ = UserAvatar.objects.select_for_update().get_or_create(user=user, defaults={"image_enc": b""})
        row.image_enc = crypto.encrypt_bytes(jpeg)
        row.updated_by_username = by_username[:150]
        row.save()


def read_avatar(user):
    """Decrypted JPEG of the account's own picture, or None."""
    row = UserAvatar.objects.filter(pk=user.pk).only("image_enc").first()
    if row is None or not bytes(row.image_enc):
        return None
    return crypto.decrypt_bytes(bytes(row.image_enc))


def remove_avatar(user) -> bool:
    deleted, _ = UserAvatar.objects.filter(pk=user.pk).delete()
    return bool(deleted)
