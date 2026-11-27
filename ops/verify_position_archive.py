#!/usr/bin/env python3
"""Check a position archive WITHOUT the application, the database or the data key. Needs only: pip install cryptography

    python verify_position_archive.py FILE.zip --public-key <base64 public key from archive_keygen>

Prints the signed manifest and says VALID or INVALID (exit code 0 or 1). It proves the file is exactly what the signing machine
wrote. It does not show the rows: those are encrypted with the system's data key.
"""
import argparse
import base64
import hashlib
import json
import sys
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def fail(msg):
    print("INVALID:", msg)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--public-key", required=True, action="append", help="may be given more than once")
    a = ap.parse_args()
    try:
        with zipfile.ZipFile(a.archive) as z:
            if set(z.namelist()) != {"data.jsonl.gz.enc", "manifest.json", "manifest.sig"}:
                fail("unexpected files in the archive")
            mbytes, sig, data = z.read("manifest.json"), z.read("manifest.sig").decode().strip(), z.read("data.jsonl.gz.enc")
        manifest, signature = json.loads(mbytes), bytes.fromhex(sig)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        fail(f"cannot read the archive ({exc})")
    if mbytes != json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode():
        fail("manifest is not in its signed form")
    for k in a.public_key:
        try:
            Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(k)).verify(signature, mbytes)
            break
        except (InvalidSignature, ValueError):
            continue
    else:
        fail("signature does not match any key you gave")
    if hashlib.sha256(data).hexdigest() != manifest["data_sha256"]:
        fail("data file does not match the signed checksum")
    print(json.dumps(manifest, indent=2))
    print("VALID")


if __name__ == "__main__":
    main()
