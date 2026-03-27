"""
RTA-GUARD Crypto — Benchmarks

Performance comparison between classical and PQC operations.
"""
import logging
import time
from typing import Any, Dict, List

from .config import CryptoConfig
from .classical import ClassicalCrypto
from .pqc import PQCCrypto
from .hybrid import HybridCrypto

logger = logging.getLogger("discus.crypto.benchmark")


def benchmark(iterations: int = 100) -> Dict[str, Any]:
    """
    Run performance benchmarks comparing classical vs PQC.
    Returns timing data for all operations.
    """
    results = {}

    # ─── Classical Benchmarks ───────────────────────────────────────

    # RSA Key Generation
    start = time.time()
    for _ in range(min(iterations, 10)):  # RSA keygen is slow
        ClassicalCrypto.generate_keypair(2048)
    results["rsa_keygen_ms"] = (time.time() - start) / min(iterations, 10) * 1000

    # RSA Sign
    keys = ClassicalCrypto.generate_keypair(2048)
    data = b"RTA-GUARD audit event payload for benchmarking"
    start = time.time()
    for _ in range(iterations):
        ClassicalCrypto.sign(data, keys.private_key)
    results["rsa_sign_ms"] = (time.time() - start) / iterations * 1000

    # RSA Verify
    sig = ClassicalCrypto.sign(data, keys.private_key)
    start = time.time()
    for _ in range(iterations):
        ClassicalCrypto.verify(data, sig, keys.public_key)
    results["rsa_verify_ms"] = (time.time() - start) / iterations * 1000

    # AES Encrypt
    aes_key = ClassicalCrypto.generate_aes_key()
    start = time.time()
    for _ in range(iterations):
        ClassicalCrypto.aes_encrypt(data, aes_key)
    results["aes_encrypt_ms"] = (time.time() - start) / iterations * 1000

    # ─── PQC Benchmarks ─────────────────────────────────────────────

    pqc = PQCCrypto()

    # ML-DSA Key Generation
    start = time.time()
    for _ in range(iterations):
        pqc.mldsa_keygen()
    results["mldsa_keygen_ms"] = (time.time() - start) / iterations * 1000

    # ML-DSA Sign
    mldsa_keys = pqc.mldsa_keygen()
    start = time.time()
    for _ in range(iterations):
        pqc.mldsa_sign(data, mldsa_keys.secret_key)
    results["mldsa_sign_ms"] = (time.time() - start) / iterations * 1000

    # ML-DSA Verify
    mldsa_sig = pqc.mldsa_sign(data, mldsa_keys.secret_key)
    start = time.time()
    for _ in range(iterations):
        pqc.mldsa_verify(data, mldsa_sig, mldsa_keys.public_key)
    results["mldsa_verify_ms"] = (time.time() - start) / iterations * 1000

    # ML-KEM Key Generation
    start = time.time()
    for _ in range(iterations):
        pqc.mlkem_keygen()
    results["mlkem_keygen_ms"] = (time.time() - start) / iterations * 1000

    # ML-KEM Encapsulate
    kem_keys = pqc.mlkem_keygen()
    start = time.time()
    for _ in range(iterations):
        pqc.mlkem_encapsulate(kem_keys.public_key)
    results["mlkem_encap_ms"] = (time.time() - start) / iterations * 1000

    # ML-KEM Decapsulate
    ct, ss = pqc.mlkem_encapsulate(kem_keys.public_key)
    start = time.time()
    for _ in range(iterations):
        pqc.mlkem_decapsulate(ct, kem_keys.secret_key)
    results["mlkem_decap_ms"] = (time.time() - start) / iterations * 1000

    # ─── Hybrid Benchmarks ─────────────────────────────────────────

    hybrid = HybridCrypto()
    hybrid_keys = hybrid.generate_keys()

    # Hybrid Sign
    start = time.time()
    for _ in range(iterations):
        hybrid.sign(data, hybrid_keys)
    results["hybrid_sign_ms"] = (time.time() - start) / iterations * 1000

    # Hybrid Verify
    hybrid_sig = hybrid.sign(data, hybrid_keys)
    start = time.time()
    for _ in range(iterations):
        hybrid.verify(data, hybrid_sig, hybrid_keys.classical.public_key,
                     hybrid_keys.pqc_signing.public_key)
    results["hybrid_verify_ms"] = (time.time() - start) / iterations * 1000

    # ─── Summary ────────────────────────────────────────────────────

    results["pqc_backend"] = pqc.backend
    results["iterations"] = iterations
    results["signing_overhead_ms"] = round(
        results["hybrid_sign_ms"] - results["rsa_sign_ms"], 3
    )

    return results
