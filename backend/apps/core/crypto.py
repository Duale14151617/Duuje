"""Field encryption with key rotation.

FIELD_ENCRYPTION_KEY holds one Fernet key, or several separated by commas: "NEW,OLD". New data is always written with the FIRST key;
any listed key can read. `manage.py rotate_encryption_key` re-encrypts stored data under the first key, after which the old keys can be
removed. See docs/KEY_ROTATION.md.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


def keys() -> list:
    return [k.strip() for k in settings.FIELD_ENCRYPTION_KEY.split(",") if k.strip()]


@lru_cache(maxsize=8)
def _multi_for(key_tuple):
    return MultiFernet([Fernet(k.encode()) for k in key_tuple])


@lru_cache(maxsize=8)
def _primary_for(key_tuple):
    return Fernet(key_tuple[0].encode())


def _multi():
    return _multi_for(tuple(keys()))


def encrypt(value: str) -> str:
    return _multi().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _multi().decrypt(token.encode()).decode()


def encrypt_bytes(value: bytes) -> bytes:
    return _multi().encrypt(value)


def decrypt_bytes(token: bytes) -> bytes:
    return _multi().decrypt(bytes(token))


def is_current(token: bytes) -> bool:
    """True when the token is already readable with the primary (first) key."""
    try:
        _primary_for(tuple(keys())).decrypt(bytes(token))
        return True
    except InvalidToken:
        return False


def rotate(token: bytes) -> bytes:
    """Re-encrypt a token under the primary key. Raises InvalidToken if no listed key can read it."""
    return _multi().rotate(bytes(token))
