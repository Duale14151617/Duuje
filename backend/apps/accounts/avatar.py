"""Account profile pictures: set by an administrator, shown in the header, Account page and user administration."""
from django.db import transaction

from apps.core import crypto

from . import scope
from .models import UserAvatar

HQ_ROLE, SUPER_ROLE = "hq_admin", "super_admin"


def _role_codes(user) -> set:
    return {a.role.code for a in scope.assignments(user)}


def can_set_avatar(actor, target) -> bool:
    """Profile pictures are set only by HQ administrators and super administrators.
    A super administrator may change anyone's. An HQ administrator may change their own and the pictures of lower roles,
    never another HQ administrator's or a super administrator's."""
    mine = _role_codes(actor)
    if SUPER_ROLE in mine or scope.has_full_access(actor):
        return True
    if HQ_ROLE not in mine:
        return False
    if target.pk == actor.pk:
        return True
    return not (_role_codes(target) & {HQ_ROLE, SUPER_ROLE}) and not scope.has_full_access(target)


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
