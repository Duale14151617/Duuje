"""WebAuthn verifier tests with a software authenticator (no Django needed)."""
import hashlib
import json
import struct
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from apps.accounts import webauthn as w

RP, ORIGIN = "police.example.so", "https://police.example.so"


def cb(v):  # tiny CBOR encoder for the shapes the tests need
    def head(major, n):
        if n < 24: return bytes([major << 5 | n])
        if n < 256: return bytes([major << 5 | 24, n])
        return bytes([major << 5 | 25]) + struct.pack(">H", n)
    if isinstance(v, int): return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes): return head(2, len(v)) + v
    if isinstance(v, str): return head(3, len(v.encode())) + v.encode()
    if isinstance(v, dict): return head(5, len(v)) + b"".join(cb(k) + cb(x) for k, x in v.items())
    raise TypeError(v)


class Authenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = b"\x01" * 32
        self.count = 0

    def cose(self):
        n = self.key.public_key().public_numbers()
        return cb({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def register(self, challenge, origin=ORIGIN, rp=RP):
        auth = hashlib.sha256(rp.encode()).digest() + bytes([0x41]) + struct.pack(">I", 0) + b"\0" * 16 \
            + struct.pack(">H", len(self.cred_id)) + self.cred_id + self.cose()
        cd = json.dumps({"type": "webauthn.create", "challenge": challenge, "origin": origin}).encode()
        att = cb({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": w.b64e(self.cred_id), "response": {"clientDataJSON": w.b64e(cd), "attestationObject": w.b64e(att)}}

    def sign(self, challenge, origin=ORIGIN, rp=RP, flags=0x01, bump=1):
        self.count += bump
        auth = hashlib.sha256(rp.encode()).digest() + bytes([flags]) + struct.pack(">I", self.count)
        cd = json.dumps({"type": "webauthn.get", "challenge": challenge, "origin": origin}).encode()
        sig = self.key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": w.b64e(self.cred_id), "response": {"clientDataJSON": w.b64e(cd), "authenticatorData": w.b64e(auth), "signature": w.b64e(sig)}}


class WebAuthnTests(unittest.TestCase):
    def setUp(self):
        self.dev = Authenticator()
        cid, pub, count, _ = w.verify_registration(self.dev.register("abc"), challenge="abc", rp_id=RP, origins=[ORIGIN])
        self.pub, self.cid = pub, cid

    def check(self, cred, challenge="c1", count=0, **kw):
        return w.verify_assertion(cred, stored_public_key=self.pub, stored_sign_count=count, challenge=challenge,
                                  rp_id=kw.get("rp", RP), origins=kw.get("origins", [ORIGIN]))

    def test_register_returns_credential_id(self):
        self.assertEqual(self.cid, w.b64e(self.dev.cred_id))

    def test_register_rejects_wrong_challenge_origin_and_rp(self):
        with self.assertRaises(w.WebAuthnError):
            w.verify_registration(self.dev.register("abc"), challenge="other", rp_id=RP, origins=[ORIGIN])
        with self.assertRaises(w.WebAuthnError):
            w.verify_registration(self.dev.register("abc", origin="https://evil.example"), challenge="abc", rp_id=RP, origins=[ORIGIN])
        with self.assertRaises(w.WebAuthnError):
            w.verify_registration(self.dev.register("abc", rp="evil.example"), challenge="abc", rp_id=RP, origins=[ORIGIN])

    def test_good_assertion_returns_counter(self):
        self.assertEqual(self.check(self.dev.sign("c1")), 1)

    def test_rejects_wrong_challenge_origin_rp_and_missing_presence(self):
        for cred, kw in [(self.dev.sign("c1"), {"challenge": "c2"}),
                         (self.dev.sign("c1", origin="https://evil.example"), {}),
                         (self.dev.sign("c1", rp="evil.example"), {}),
                         (self.dev.sign("c1", flags=0x00), {})]:
            with self.assertRaises(w.WebAuthnError):
                self.check(cred, **kw)

    def test_rejects_signature_from_another_key(self):
        other = Authenticator()
        with self.assertRaises(w.WebAuthnError):
            self.check(other.sign("c1"))

    def test_rejects_tampered_signature(self):
        cred = self.dev.sign("c1")
        sig = bytearray(w.b64d(cred["response"]["signature"]))
        sig[-1] ^= 1
        cred["response"]["signature"] = w.b64e(bytes(sig))
        with self.assertRaises(w.WebAuthnError):
            self.check(cred)

    def test_counter_must_advance_but_zero_counters_are_allowed(self):
        self.dev.count = 5
        with self.assertRaises(w.WebAuthnError):
            self.check(self.dev.sign("c1", bump=0), count=5)  # replayed counter 5 <= 5
        zero = Authenticator()
        zero.count = 0
        cid, pub, _, _ = w.verify_registration(zero.register("abc"), challenge="abc", rp_id=RP, origins=[ORIGIN])
        self.assertEqual(w.verify_assertion(zero.sign("c1", bump=0), stored_public_key=pub, stored_sign_count=0,
                                            challenge="c1", rp_id=RP, origins=[ORIGIN]), 0)

    def test_garbage_input_is_an_error_not_a_crash(self):
        for bad in ({}, {"response": {}}, {"response": {"clientDataJSON": "!!", "authenticatorData": "x", "signature": "y"}}):
            with self.assertRaises(w.WebAuthnError):
                self.check(bad)


if __name__ == "__main__":
    unittest.main()
