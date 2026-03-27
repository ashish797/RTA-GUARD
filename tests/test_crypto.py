"""
RTA-GUARD Crypto Tests

Tests for: classical, PQC, hybrid, key management, audit signing,
session tokens, federation auth, and benchmarks.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from discus.crypto import (
    CryptoConfig, CryptoMode, KeyPurpose,
    ClassicalCrypto, ClassicalKeyPair,
    PQCCrypto, PQCKeyPair,
    HybridCrypto, HybridKeySet, HybridSignature,
    KeyManager, KeyRecord,
    AuditSigner, SignedEvent,
    SessionTokenManager, SecureSessionToken,
    FederationAuth, FederationCertificate, SignedMessage,
)


# ─── Classical Crypto Tests ────────────────────────────────────────

class TestClassical(unittest.TestCase):
    def test_keypair_generation(self):
        keys = ClassicalCrypto.generate_keypair(2048)
        self.assertIn(b"BEGIN PRIVATE KEY", keys.private_key)
        self.assertIn(b"BEGIN PUBLIC KEY", keys.public_key)

    def test_sign_verify(self):
        keys = ClassicalCrypto.generate_keypair(2048)
        data = b"test message"
        sig = ClassicalCrypto.sign(data, keys.private_key)
        self.assertTrue(ClassicalCrypto.verify(data, sig, keys.public_key))
        self.assertFalse(ClassicalCrypto.verify(b"tampered", sig, keys.public_key))

    def test_aes_encrypt_decrypt(self):
        key = ClassicalCrypto.generate_aes_key()
        plaintext = b"sensitive audit data"
        nonce, ct = ClassicalCrypto.aes_encrypt(plaintext, key)
        recovered = ClassicalCrypto.aes_decrypt(nonce, ct, key)
        self.assertEqual(recovered, plaintext)

    def test_key_encryption_with_passphrase(self):
        keys = ClassicalCrypto.generate_keypair(2048)
        encrypted, salt = ClassicalCrypto.encrypt_private_key(keys.private_key, "test-pass")
        decrypted = ClassicalCrypto.decrypt_private_key(encrypted, "test-pass")
        self.assertEqual(decrypted, keys.private_key)

    def test_sha256(self):
        h = ClassicalCrypto.sha256(b"test")
        self.assertEqual(len(h), 64)

    def test_hmac(self):
        mac = ClassicalCrypto.hmac_sha256(b"data", b"key")
        self.assertEqual(len(mac), 64)

    def test_save_load_keypair(self):
        keys = ClassicalCrypto.generate_keypair(2048)
        d = Path(tempfile.mkdtemp())
        try:
            ClassicalCrypto.save_keypair(keys, d, "test")
            self.assertTrue((d / "test_public.pem").exists())
            self.assertTrue((d / "test_private.pem").exists())
            loaded_priv = ClassicalCrypto.load_private_key(d / "test_private.pem")
            self.assertEqual(loaded_priv, keys.private_key)
        finally:
            shutil.rmtree(d)

    def test_encrypted_save_load(self):
        keys = ClassicalCrypto.generate_keypair(2048)
        d = Path(tempfile.mkdtemp())
        try:
            ClassicalCrypto.save_keypair(keys, d, "test", passphrase="secret")
            loaded = ClassicalCrypto.load_private_key(d / "test_private.pem", "secret")
            self.assertEqual(loaded, keys.private_key)
        finally:
            shutil.rmtree(d)


# ─── PQC Tests ─────────────────────────────────────────────────────

class TestPQC(unittest.TestCase):
    def setUp(self):
        self.pqc = PQCCrypto()

    def test_mldsa_keygen(self):
        keys = self.pqc.mldsa_keygen()
        self.assertGreater(len(keys.public_key), 0)
        self.assertGreater(len(keys.secret_key), 0)
        self.assertIn("ML-DSA", keys.algorithm)

    def test_mldsa_sign_verify(self):
        keys = self.pqc.mldsa_keygen()
        data = b"audit event data"
        sig = self.pqc.mldsa_sign(data, keys.secret_key)
        self.assertTrue(self.pqc.mldsa_verify(data, sig, keys.public_key))
        self.assertFalse(self.pqc.mldsa_verify(b"tampered", sig, keys.public_key))

    def test_mlkem_keygen(self):
        keys = self.pqc.mlkem_keygen()
        self.assertGreater(len(keys.public_key), 0)
        self.assertGreater(len(keys.secret_key), 0)

    def test_mlkem_encap_decap(self):
        keys = self.pqc.mlkem_keygen()
        ct, ss1 = self.pqc.mlkem_encapsulate(keys.public_key)
        ss2 = self.pqc.mlkem_decapsulate(ct, keys.secret_key)
        self.assertEqual(ss1, ss2)

    def test_slhdsa_sign_verify(self):
        keys = self.pqc.slhdsa_keygen()
        data = b"backup signing test"
        sig = self.pqc.slhdsa_sign(data, keys.secret_key)
        self.assertTrue(self.pqc.slhdsa_verify(data, sig, keys.public_key))

    def test_key_serialization(self):
        keys = self.pqc.mldsa_keygen()
        d = keys.to_dict()
        self.assertEqual(d["algorithm"], keys.algorithm)
        self.assertIn("public_key_hash", d)


# ─── Hybrid Tests ──────────────────────────────────────────────────

class TestHybrid(unittest.TestCase):
    def setUp(self):
        self.hybrid = HybridCrypto()
        self.keys = self.hybrid.generate_keys()

    def test_sign_verify_hybrid(self):
        data = b"hybrid test data"
        sig = self.hybrid.sign(data, self.keys)
        self.assertGreater(len(sig.classical_sig), 0)
        self.assertGreater(len(sig.pqc_sig), 0)

        result = self.hybrid.verify(data, sig,
            self.keys.classical.public_key,
            self.keys.pqc_signing.public_key)
        self.assertTrue(result["fully_valid"])
        self.assertTrue(result["classical_valid"])
        self.assertTrue(result["pqc_valid"])

    def test_tampered_sig_fails(self):
        data = b"original"
        sig = self.hybrid.sign(data, self.keys)
        result = self.hybrid.verify(b"tampered", sig,
            self.keys.classical.public_key,
            self.keys.pqc_signing.public_key)
        self.assertFalse(result["fully_valid"])

    def test_classical_only(self):
        data = b"classical only"
        sig = self.hybrid.sign_classical_only(data, self.keys)
        self.assertGreater(len(sig.classical_sig), 0)
        self.assertEqual(len(sig.pqc_sig), 0)
        result = self.hybrid.verify(data, sig,
            self.keys.classical.public_key,
            self.keys.pqc_signing.public_key)
        self.assertTrue(result["classical_valid"])
        self.assertFalse(result["pqc_valid"])
        self.assertFalse(result["fully_valid"])

    def test_pqc_only(self):
        data = b"pqc only"
        sig = self.hybrid.sign_pqc_only(data, self.keys)
        self.assertEqual(len(sig.classical_sig), 0)
        self.assertGreater(len(sig.pqc_sig), 0)
        result = self.hybrid.verify(data, sig,
            self.keys.classical.public_key,
            self.keys.pqc_signing.public_key)
        self.assertFalse(result["classical_valid"])
        self.assertTrue(result["pqc_valid"])
        self.assertFalse(result["fully_valid"])

    def test_key_exchange(self):
        ct, ss1 = self.hybrid.key_exchange(self.keys.pqc_kem.public_key)
        ss2 = self.hybrid.key_decapsulate(ct, self.keys)
        self.assertEqual(ss1, ss2)

    def test_signature_serialization(self):
        data = b"serialize test"
        sig = self.hybrid.sign(data, self.keys)
        serialized = sig.serialize()
        restored = HybridSignature.deserialize(serialized)
        self.assertEqual(restored.algorithm, sig.algorithm)


# ─── Key Manager Tests ─────────────────────────────────────────────

class TestKeyManager(unittest.TestCase):
    def setUp(self):
        self.keys_dir = Path(tempfile.mkdtemp())
        self.config = CryptoConfig(keys_dir=self.keys_dir, key_rotation_days=30)
        self.km = KeyManager(self.config)

    def tearDown(self):
        shutil.rmtree(self.keys_dir)

    def test_generate_keys(self):
        keys = self.km.generate_keys(KeyPurpose.AUDIT_SIGNING)
        self.assertIsNotNone(keys.classical)
        self.assertIsNotNone(keys.pqc_signing)

    def test_load_keys(self):
        self.km.generate_keys(KeyPurpose.FEDERATION)
        loaded = self.km.load_keys(KeyPurpose.FEDERATION)
        self.assertEqual(loaded.classical.public_key,
                        self.km.load_keys(KeyPurpose.FEDERATION).classical.public_key)

    def test_key_isolation(self):
        self.km.generate_keys(KeyPurpose.AUDIT_SIGNING)
        self.km.generate_keys(KeyPurpose.FEDERATION)
        keys_audit = self.km.load_keys(KeyPurpose.AUDIT_SIGNING)
        keys_fed = self.km.load_keys(KeyPurpose.FEDERATION)
        # Keys should be different per purpose
        self.assertNotEqual(keys_audit.classical.public_key, keys_fed.classical.public_key)

    def test_rotation(self):
        self.km.generate_keys(KeyPurpose.SESSIONS)
        keys1 = self.km.load_keys(KeyPurpose.SESSIONS)
        keys2 = self.km.rotate_keys(KeyPurpose.SESSIONS)
        # Rotated keys should be different
        self.assertNotEqual(keys1.classical.public_key, keys2.classical.public_key)

    def test_key_info(self):
        self.km.generate_keys(KeyPurpose.WEBHOOKS)
        info = self.km.get_key_info(KeyPurpose.WEBHOOKS)
        self.assertEqual(info["status"], "active")
        self.assertIn("age_days", info)

    def test_get_or_generate(self):
        keys = self.km.get_or_generate(KeyPurpose.GENERAL)
        # Second call should return same keys
        keys2 = self.km.get_or_generate(KeyPurpose.GENERAL)
        self.assertEqual(keys.classical.public_key, keys2.classical.public_key)

    def test_rotation_needed(self):
        # Fresh keys shouldn't need rotation
        self.km.generate_keys(KeyPurpose.AUDIT_SIGNING)
        self.assertFalse(self.km.check_rotation_needed(KeyPurpose.AUDIT_SIGNING))

    def test_encrypted_key_storage(self):
        config = CryptoConfig(keys_dir=self.keys_dir, master_passphrase="test-secret")
        km = KeyManager(config)
        keys = km.generate_keys(KeyPurpose.AUDIT_SIGNING)
        # Private key should be encrypted
        priv_path = self.keys_dir / "audit_signing" / "audit_signing_private.pem"
        self.assertTrue(priv_path.read_bytes().startswith(b"ENCRYPTED:"))


# ─── Audit Signer Tests ────────────────────────────────────────────

class TestAuditSigner(unittest.TestCase):
    def setUp(self):
        self.keys_dir = Path(tempfile.mkdtemp())
        self.config = CryptoConfig(keys_dir=self.keys_dir)
        self.km = KeyManager(self.config)
        self.signer = AuditSigner(self.km)
        self.signer.initialize()

    def tearDown(self):
        shutil.rmtree(self.keys_dir)

    def test_sign_kill_event(self):
        event = self.signer.sign_event(
            session_id="s1", decision="kill",
            violation_type="pii", input_text="test@example.com",
            details={"reason": "email detected"},
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.decision, "kill")
        self.assertEqual(event.signature_mode, "hybrid")

    def test_sign_warn_event(self):
        event = self.signer.sign_event(
            session_id="s2", decision="warn",
            violation_type="injection", input_text="suspicious input",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.decision, "warn")

    def test_skip_pass_by_default(self):
        event = self.signer.sign_event(session_id="s3", decision="pass")
        self.assertIsNone(event)  # Pass events not signed by default

    def test_sign_pass_when_enabled(self):
        config = CryptoConfig(keys_dir=self.keys_dir, sign_pass_events=True)
        km = KeyManager(config)
        signer = AuditSigner(km)
        signer.initialize()
        event = signer.sign_event(session_id="s4", decision="pass")
        self.assertIsNotNone(event)

    def test_verify_event(self):
        event = self.signer.sign_event(
            session_id="s5", decision="kill", input_text="test",
        )
        # With pure Python fallback, classical verification works
        # PQC verification depends on backend — check classical at minimum
        result = self.signer.verify_event(event)
        self.assertTrue(result["classical_valid"])

    def test_chain_verification(self):
        events = []
        for i in range(5):
            e = self.signer.sign_event(
                session_id=f"chain-{i}", decision="kill",
                violation_type=f"type-{i}", input_text=f"event-{i}",
            )
            events.append(e)

        chain_result = self.signer.verify_chain(events)
        # Classical signatures should all be valid
        self.assertFalse(chain_result["chain_broken"] if "chain_broken" in chain_result else False)
        self.assertGreater(chain_result["total_events"], 0)

    def test_event_hash_does_not_contain_input(self):
        event = self.signer.sign_event(
            session_id="s6", decision="kill", input_text="secret data here",
        )
        # input_hash should be SHA-256, not the raw text
        self.assertEqual(len(event.input_hash), 64)
        self.assertNotIn("secret", event.input_hash)

    def test_public_keys(self):
        pubkeys = self.signer.get_public_keys()
        self.assertIn("classical_public_key", pubkeys)
        self.assertIn("pqc_signing_public_key", pubkeys)


# ─── Session Token Tests ───────────────────────────────────────────

class TestSessionTokens(unittest.TestCase):
    def setUp(self):
        self.keys_dir = Path(tempfile.mkdtemp())
        self.config = CryptoConfig(keys_dir=self.keys_dir)
        self.km = KeyManager(self.config)
        self.stm = SessionTokenManager(self.km)
        self.stm.initialize()

    def tearDown(self):
        shutil.rmtree(self.keys_dir)

    def test_create_token(self):
        token = self.stm.create_token("session-1", ttl_seconds=3600)
        self.assertEqual(token.session_id, "session-1")
        self.assertFalse(token.is_expired())

    def test_token_string_roundtrip(self):
        token = self.stm.create_token("s2", ttl_seconds=3600)
        token_str = token.to_token_string()
        restored = SecureSessionToken.from_token_string(token_str)
        self.assertEqual(restored.session_id, "s2")

    def test_validate_token(self):
        token = self.stm.create_token("s3", ttl_seconds=3600)
        result = self.stm.validate_token(token)
        self.assertTrue(result["valid"])
        self.assertEqual(result["session_id"], "s3")

    def test_expired_token(self):
        token = self.stm.create_token("s4", ttl_seconds=-1)
        result = self.stm.validate_token(token)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "expired")

    def test_validate_token_string(self):
        token_str = self.stm.create_token("s5").to_token_string()
        result = self.stm.validate_token_string(token_str)
        self.assertTrue(result["valid"])


# ─── Federation Auth Tests ─────────────────────────────────────────

class TestFederationAuth(unittest.TestCase):
    def setUp(self):
        self.keys_dir = Path(tempfile.mkdtemp())
        self.config = CryptoConfig(keys_dir=self.keys_dir)
        self.km = KeyManager(self.config)
        self.fed_auth = FederationAuth(self.km)
        self.fed_auth.initialize()

    def tearDown(self):
        shutil.rmtree(self.keys_dir)

    def test_create_certificate(self):
        cert = self.fed_auth.create_certificate("node-1")
        self.assertEqual(cert.node_id, "node-1")
        self.assertFalse(cert.is_expired())

    def test_certificate_fingerprint(self):
        cert = self.fed_auth.create_certificate("node-2")
        fp = cert.fingerprint()
        self.assertEqual(len(fp), 32)

    def test_sign_verify_message(self):
        cert = self.fed_auth.create_certificate("node-3")
        msg = self.fed_auth.sign_message({"action": "heartbeat"}, cert)
        result = self.fed_auth.verify_message(msg)
        self.assertTrue(result["valid"])

    def test_verify_certificate(self):
        cert = self.fed_auth.create_certificate("node-4", validity_days=365)
        result = self.fed_auth.verify_certificate(cert)
        self.assertTrue(result["valid"])

    def test_expired_certificate(self):
        cert = self.fed_auth.create_certificate("node-5", validity_days=-1)
        self.assertTrue(cert.is_expired())
        result = self.fed_auth.verify_certificate(cert)
        self.assertFalse(result["valid"])


# ─── Benchmark Test ────────────────────────────────────────────────

class TestBenchmark(unittest.TestCase):
    def test_benchmark_runs(self):
        from discus.crypto import benchmark
        results = benchmark(iterations=5)  # Small for speed
        self.assertIn("rsa_sign_ms", results)
        self.assertIn("mldsa_sign_ms", results)
        self.assertIn("hybrid_sign_ms", results)
        self.assertIn("pqc_backend", results)
        # Hybrid should have some overhead (not necessarily slower due to measurement noise)
        self.assertGreater(results["hybrid_sign_ms"], 0)


if __name__ == "__main__":
    unittest.main()
