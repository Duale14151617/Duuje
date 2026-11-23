"""WebAuthn (passkeys) without a third-party library: only the `cryptography` package that the project already depends on.

Scope is deliberately small. We ask for no attestation (the authenticator's make and model are not checked; any passkey the person
owns is welcome), accept ES256 and RS256 keys, and verify sign-in assertions completely: challenge, origin, relying-party hash,
user-presence flag and the signature itself, plus the signature counter when the authenticator keeps one.
"""
import base64
import hashlib
import json
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa


class WebAuthnError(Exception):
    pass


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64d(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception as exc:  # bad padding / alphabet
        raise WebAuthnError("bad base64") from exc


# ---- a minimal CBOR reader (enough for attestation objects and COSE keys) -------------------------------------------------
def _cbor(data: bytes, i: int = 0, depth: int = 0):
    if depth > 8 or i >= len(data):
        raise WebAuthnError("bad cbor")
    head = data[i]
    major, info = head >> 5, head & 31
    i += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        if i + size > len(data):
            raise WebAuthnError("bad cbor")
        n = int.from_bytes(data[i:i + size], "big")
        i += size
    else:
        raise WebAuthnError("unsupported cbor")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        if i + n > len(data):
            raise WebAuthnError("bad cbor")
        raw = data[i:i + n]
        return (raw if major == 2 else raw.decode("utf-8", "strict")), i + n
    if major == 4:
        if n > 64:
            raise WebAuthnError("bad cbor")
        out = []
        for _ in range(n):
            v, i = _cbor(data, i, depth + 1)
            out.append(v)
        return out, i
    if major == 5:
        if n > 64:
            raise WebAuthnError("bad cbor")
        out = {}
        for _ in range(n):
            k, i = _cbor(data, i, depth + 1)
            v, i = _cbor(data, i, depth + 1)
            out[k] = v
        return out, i
    raise WebAuthnError("unsupported cbor")


def cbor_decode(data: bytes):
    value, end = _cbor(data)
    return value, end


# ---- shared checks -------------------------------------------------------------------------------------------------------
FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40


def _client_data(raw_b64: str, *, kind: str, challenge: str, origins):
    raw = b64d(raw_b64)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise WebAuthnError("bad client data") from exc
    if data.get("type") != kind:
        raise WebAuthnError("wrong ceremony")
    if data.get("challenge") != challenge:
        raise WebAuthnError("challenge mismatch")
    if data.get("origin") not in set(origins):
        raise WebAuthnError("origin not allowed")
    if data.get("crossOrigin") is True:
        raise WebAuthnError("cross-origin")
    return raw


def _auth_data(auth: bytes, rp_id: str):
    if len(auth) < 37:
        raise WebAuthnError("short authenticator data")
    if auth[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise WebAuthnError("wrong relying party")
    flags = auth[32]
    if not flags & FLAG_UP:
        raise WebAuthnError("user presence missing")
    return flags, struct.unpack(">I", auth[33:37])[0]


# ---- registration --------------------------------------------------------------------------------------------------------
def verify_registration(credential: dict, *, challenge: str, rp_id: str, origins):
    """Returns (credential_id_b64, public_key_cose_b64, sign_count, transports). Raises WebAuthnError."""
    try:
        response = credential["response"]
        _client_data(response["clientDataJSON"], kind="webauthn.create", challenge=challenge, origins=origins)
        attestation, _ = cbor_decode(b64d(response["attestationObject"]))
        auth = attestation["authData"]
    except (KeyError, TypeError) as exc:
        raise WebAuthnError("malformed registration") from exc
    flags, count = _auth_data(auth, rp_id)
    if not flags & FLAG_AT or len(auth) < 55:
        raise WebAuthnError("no credential data")
    cred_len = struct.unpack(">H", auth[53:55])[0]
    cred_id = auth[55:55 + cred_len]
    if cred_len == 0 or len(cred_id) != cred_len or cred_len > 512:
        raise WebAuthnError("bad credential id")
    key, end = cbor_decode(auth[55 + cred_len:])
    public_key = auth[55 + cred_len:55 + cred_len + end]
    _load_key(key)  # proves we can use it later
    given = credential.get("id")
    if given and b64d(given) != cred_id:
        raise WebAuthnError("credential id mismatch")
    transports = [t for t in (response.get("transports") or []) if isinstance(t, str)][:6]
    return b64e(cred_id), b64e(public_key), count, transports


def _load_key(key):
    """A COSE key as a cryptography public key plus the hash/padding it verifies with."""
    try:
        kty, alg = key[1], key[3]
        if kty == 2 and alg == -7 and key.get(-1) == 1:  # EC2, ES256, P-256
            x, y = key[-2], key[-3]
            if len(x) != 32 or len(y) != 32:
                raise WebAuthnError("bad ec key")
            numbers = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1())
            return numbers.public_key(), "es256"
        if kty == 3 and alg == -257:  # RSA, RS256
            n, e = int.from_bytes(key[-1], "big"), int.from_bytes(key[-2], "big")
            if n.bit_length() < 2048:
                raise WebAuthnError("rsa key too small")
            return rsa.RSAPublicNumbers(e, n).public_key(), "rs256"
    except (KeyError, TypeError, ValueError) as exc:
        raise WebAuthnError("bad key") from exc
    raise WebAuthnError("unsupported key type")


# ---- sign-in -------------------------------------------------------------------------------------------------------------
def verify_assertion(credential: dict, *, stored_public_key: str, stored_sign_count: int, challenge: str, rp_id: str, origins):
    """Returns the new sign count. Raises WebAuthnError on anything that is not a perfect assertion."""
    try:
        response = credential["response"]
        client_raw = _client_data(response["clientDataJSON"], kind="webauthn.get", challenge=challenge, origins=origins)
        auth = b64d(response["authenticatorData"])
        signature = b64d(response["signature"])
    except (KeyError, TypeError) as exc:
        raise WebAuthnError("malformed assertion") from exc
    _flags, count = _auth_data(auth, rp_id)
    key, kind = _load_key(cbor_decode(b64d(stored_public_key))[0])
    signed = auth + hashlib.sha256(client_raw).digest()
    try:
        if kind == "es256":
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise WebAuthnError("bad signature") from exc
    # A counter that fails to move forward means the passkey may have been cloned. (Many passkeys always report 0: that is fine.)
    if (count or stored_sign_count) and count <= stored_sign_count:
        raise WebAuthnError("signature counter did not advance")
    return count
