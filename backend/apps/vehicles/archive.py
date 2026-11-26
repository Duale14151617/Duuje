"""Signed, encrypted archives of old vehicle positions, used by `archive_positions` and `purge_positions`.

An archive is one .zip with three files:
  data.jsonl.gz.enc   the rows, one JSON object per line, gzipped, then encrypted with the system's data key (FIELD_ENCRYPTION_KEY)
  manifest.json       what the archive holds: batch id, who made it, the date range, the row count, SHA-256 of the data file
  manifest.sig        Ed25519 signature (hex) over the exact bytes of manifest.json

Integrity can be checked by anyone holding the PUBLIC key, with no access to the data key (the signature covers the SHA-256 of the
encrypted file). Reading the rows needs the data key. The private signing key never has to be on the database server's backups.
"""
import base64
import gzip
import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import timezone as dt_timezone
from decimal import Decimal

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from django.conf import settings
from django.utils import timezone

from apps.core import crypto

FORMAT = "armyhq-position-archive/1"
DATA, MANIFEST, SIGNATURE = "data.jsonl.gz.enc", "manifest.json", "manifest.sig"
MIN_AGE_DAYS = 30  # also enforced by the database trigger
DEFAULT_MAX_ROWS = 200_000


class ArchiveError(Exception):
    pass


# ---- keys -------------------------------------------------------------------------------------------------------------------
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def _unb64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text.strip().encode())
    except Exception as exc:  # noqa: BLE001 - any decoding problem is a bad key
        raise ArchiveError("A signing key is not valid base64.") from exc


def keygen():
    """A new signing key pair as (private, public), both base64 text."""
    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    raw_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(raw_priv), _b64(raw_pub)


def fingerprint(public: Ed25519PublicKey) -> str:
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def signing_key() -> Ed25519PrivateKey:
    text = getattr(settings, "ARCHIVE_SIGNING_KEY", "")
    if not text:
        raise ArchiveError("ARCHIVE_SIGNING_KEY is not set. Make one with `python manage.py archive_keygen`.")
    raw = _unb64(text)
    if len(raw) != 32:
        raise ArchiveError("ARCHIVE_SIGNING_KEY must be a 32-byte Ed25519 private key.")
    return Ed25519PrivateKey.from_private_bytes(raw)


def trusted_public_keys():
    """Public keys allowed to vouch for an archive: ARCHIVE_PUBLIC_KEYS, else the public half of ARCHIVE_SIGNING_KEY."""
    listed = getattr(settings, "ARCHIVE_PUBLIC_KEYS", [])
    if listed:
        out = []
        for k in listed:
            raw = _unb64(k)
            if len(raw) != 32:
                raise ArchiveError("ARCHIVE_PUBLIC_KEYS holds a key that is not a 32-byte Ed25519 public key.")
            out.append(Ed25519PublicKey.from_public_bytes(raw))
        return out
    return [signing_key().public_key()]


# ---- rows -------------------------------------------------------------------------------------------------------------------
def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _iso(value):
    return None if value is None else value.astimezone(dt_timezone.utc).isoformat()


def serialize_row(p) -> dict:
    """One position as plain, stable text. Used both to write the archive and to check, at purge time, that the row in the database
    still equals what was archived (a position voided since then is NOT deleted)."""
    return {
        "id": str(p.pk), "vehicle_id": str(p.vehicle_id), "vehicle_code": p.vehicle.vehicle_id, "trip_id": str(p.trip_id) if p.trip_id else None,
        "latitude": f"{Decimal(str(p.latitude)):.6f}", "longitude": f"{Decimal(str(p.longitude)):.6f}", "accuracy_m": p.accuracy_m,
        "place": p.place, "source": p.source, "recorded_at": _iso(p.recorded_at), "note": p.note, "created_by_username": p.created_by_username,
        "voided_at": _iso(p.voided_at), "voided_by_username": p.voided_by_username, "voided_reason": p.voided_reason, "version": p.version,
        "created_at": _iso(p.created_at),
    }


# ---- build and verify -------------------------------------------------------------------------------------------------------
def build_archive(rows, *, out_dir, by, cutoff, batch_id=None):
    """Write an archive of `rows` (oldest first, already fetched) into out_dir. Returns (path, manifest, signature_hex).
    Nothing is deleted and nothing is written to the database here."""
    if not rows:
        raise ArchiveError("No rows to archive.")
    key = signing_key()
    batch_id = str(batch_id or uuid.uuid4())
    data = b"\n".join(canonical(serialize_row(r)) for r in rows) + b"\n"
    encrypted = crypto.encrypt_bytes(gzip.compress(data, mtime=0))
    first, last = rows[0].recorded_at, rows[-1].recorded_at
    manifest = {
        "format": FORMAT, "batch_id": batch_id, "created_at": _iso(timezone.now()), "created_by": by, "cutoff": _iso(cutoff),
        "range_start": _iso(min(first, last)), "range_end": _iso(max(first, last)), "row_count": len(rows),
        "data_file": DATA, "data_sha256": hashlib.sha256(encrypted).hexdigest(), "encryption": "fernet (FIELD_ENCRYPTION_KEY)",
        "key_fingerprint": fingerprint(key.public_key()),
    }
    manifest_bytes = canonical(manifest)
    signature = key.sign(manifest_bytes).hex()
    name = f"positions-{manifest['range_start'][:10].replace('-', '')}-{manifest['range_end'][:10].replace('-', '')}-{batch_id[:8]}.zip"
    final, tmp = os.path.join(out_dir, name), os.path.join(out_dir, f".{name}.part")
    with open(tmp, "wb") as fh:
        with zipfile.ZipFile(fh, "w", zipfile.ZIP_STORED) as z:
            z.writestr(DATA, encrypted)
            z.writestr(MANIFEST, manifest_bytes)
            z.writestr(SIGNATURE, signature)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)
    return final, manifest, signature


def verify_archive(path, trusted=None):
    """Check an archive file: right shape, signed by a trusted key, data file matches the signed SHA-256.
    Returns (manifest, signature_hex). Does not need the data key. Raises ArchiveError on any problem."""
    try:
        with zipfile.ZipFile(path) as z:
            if set(z.namelist()) != {DATA, MANIFEST, SIGNATURE}:
                raise ArchiveError("The archive does not hold exactly the expected files.")
            manifest_bytes, sig_text, data = z.read(MANIFEST), z.read(SIGNATURE).decode().strip(), z.read(DATA)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveError(f"Cannot read the archive: {exc}") from exc
    try:
        signature = bytes.fromhex(sig_text)
        manifest = json.loads(manifest_bytes)
    except ValueError as exc:
        raise ArchiveError("The archive's manifest or signature is damaged.") from exc
    if manifest_bytes != canonical(manifest):
        raise ArchiveError("The manifest is not in its signed form.")
    for pub in (trusted if trusted is not None else trusted_public_keys()):
        try:
            pub.verify(signature, manifest_bytes)
            break
        except InvalidSignature:
            continue
    else:
        raise ArchiveError("The signature is not valid for any trusted key. Do not use this archive.")
    if manifest.get("format") != FORMAT:
        raise ArchiveError("Unknown archive format.")
    if hashlib.sha256(data).hexdigest() != manifest.get("data_sha256"):
        raise ArchiveError("The data file does not match the signed checksum. The archive was changed or damaged.")
    return manifest, sig_text


def read_rows(path, manifest):
    """The archived rows as dicts. Needs the data key. Checks the row count against the signed manifest."""
    with zipfile.ZipFile(path) as z:
        encrypted = z.read(DATA)
    try:
        raw = gzip.decompress(crypto.decrypt_bytes(encrypted))
    except InvalidToken as exc:
        raise ArchiveError("The data key (FIELD_ENCRYPTION_KEY) cannot open this archive.") from exc
    rows = [json.loads(line) for line in io.BytesIO(raw).read().decode().splitlines() if line]
    if len(rows) != manifest["row_count"]:
        raise ArchiveError("The archive holds a different number of rows than its manifest says.")
    return rows
