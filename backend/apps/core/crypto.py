from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
