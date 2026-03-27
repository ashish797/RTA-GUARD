"""
Anti-Fingerprint Capabilities for RTA-GUARD Transport.

Provides JA3 TLS fingerprint profiles matching real-world browser TLS
configurations, randomization for evasion, and JARM adversary simulation
profiles for security testing.

JARM profiles simulate known threat actor TLS fingerprints so RTA-GUARD
can test defensive infrastructure against realistic attack traffic patterns.
"""
from __future__ import annotations

import random
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from curl_cffi.requests import BrowserType, ExtraFingerprints


# ---------------------------------------------------------------------------
# JARM Adversary Simulation Profiles
# ---------------------------------------------------------------------------

@dataclass
class JARMProfile:
    """
    JARM fingerprint profile for adversary simulation.

    JARM (Joy/Active Response Module) fingerprints TLS server configurations
    by sending 10 specially crafted TLS Client Hello packets and recording
    the responses. Different attacker toolkits produce different JARM hashes.

    By spoofing these TLS Client Hello characteristics on the CLIENT side
    (JA3), we can simulate how specific threat actor toolkits appear to
    WAFs and TLS inspection infrastructure.
    """

    name: str
    description: str
    threat_actors: List[str] = field(default_factory=list)

    # JA3 string — TLS Client Hello fingerprint
    ja3: Optional[str] = None

    # Akamai HTTP/2 fingerprint (pseudo-header order, settings, etc.)
    akamai: Optional[str] = None

    # Browser impersonation preset
    impersonate: Optional[Union[BrowserType, str]] = None

    # Extra fingerprint options for fine-grained control
    extra_fp: Optional[ExtraFingerprints] = None

    # TLS version preferences
    tls_min_version: Optional[int] = None

    # HTTP/2 settings
    http2_no_priority: Optional[bool] = None
    http2_stream_exclusive: Optional[bool] = None
    http2_stream_weight: Optional[int] = None

    # TLS extensions and features
    tls_permute_extensions: Optional[bool] = None
    tls_grease: Optional[bool] = None
    tls_record_size_limit: Optional[int] = None
    tls_cert_compression: Optional[bool] = None

    def to_extra_fp(self) -> Optional[ExtraFingerprints]:
        """Build ExtraFingerprints from profile settings."""
        if self.extra_fp is not None:
            return self.extra_fp

        kwargs: Dict[str, Any] = {}
        if self.tls_permute_extensions is not None:
            kwargs["tls_permute_extensions"] = self.tls_permute_extensions
        if self.tls_grease is not None:
            kwargs["tls_grease"] = self.tls_grease
        if self.tls_record_size_limit is not None:
            kwargs["tls_record_size_limit"] = self.tls_record_size_limit
        if self.tls_cert_compression is not None:
            kwargs["tls_cert_compression"] = self.tls_cert_compression
        if self.tls_min_version is not None:
            kwargs["tls_min_version"] = self.tls_min_version

        if kwargs:
            return ExtraFingerprints(**kwargs)
        return None

    def __repr__(self) -> str:
        return f"JARMProfile({self.name!r}, actors={self.threat_actors!r})"


# ---------------------------------------------------------------------------
# Pre-built Fingerprint Profiles
# ---------------------------------------------------------------------------

FINGERPRINT_PROFILES: Dict[str, JARMProfile] = {


    # ── Legitimate Browser Profiles ────────────────────────────────────────

    "chrome_131_windows": JARMProfile(
        name="Chrome 131 (Windows)",
        description="Standard Chrome 131 TLS fingerprint on Windows 10/11",
        impersonate="chrome131",
        tls_permute_extensions=True,
        tls_grease=True,
    ),

    "chrome_136_windows": JARMProfile(
        name="Chrome 136 (Windows)",
        description="Latest Chrome 136 TLS fingerprint on Windows",
        impersonate="chrome136",
        tls_permute_extensions=True,
        tls_grease=True,
    ),

    "safari_18_macos": JARMProfile(
        name="Safari 18.0 (macOS)",
        description="Safari 18.0 on macOS Sequoia",
        impersonate="safari18_0",
        tls_permute_extensions=False,
        tls_grease=False,
    ),

    "firefox_135": JARMProfile(
        name="Firefox 135",
        description="Mozilla Firefox 135 on Linux/Windows",
        impersonate="firefox135",
        tls_permute_extensions=True,
        tls_grease=True,
    ),

    "edge_101": JARMProfile(
        name="Edge 101",
        description="Microsoft Edge 101 (Chromium-based)",
        impersonate="edge101",
        tls_permute_extensions=True,
        tls_grease=True,
    ),

    # ── Adversary Simulation Profiles ──────────────────────────────────────

    "cobalt_strike_default": JARMProfile(
        name="Cobalt Strike (Default Malleable C2)",
        description=(
            "Simulates default Cobalt Strike C2 HTTPS beacon traffic. "
            "Default malleable profile uses Java TLS stack characteristics "
            "that differ from browser JA3 hashes."
        ),
        threat_actors=[
            "APT29 (Cozy Bear)",
            "APT41 (Winnti)",
            "FIN7",
            "Various ransomware operators",
        ],
        # Cobalt Strike defaults to Java TLS — impersonate an older Chrome
        # that approximates the cipher/order characteristics
        impersonate="chrome107",
        # Disable grease and permutation (Java doesn't use these)
        tls_permute_extensions=False,
        tls_grease=False,
        # HTTP/2 not typically used by default Cobalt Strike
        http2_no_priority=True,
    ),

    "cobalt_strike_custom_malleable": JARMProfile(
        name="Cobalt Strike (Custom Malleable C2)",
        description=(
            "Simulates Cobalt Strike with a custom malleable profile "
            "configured to match Chrome TLS characteristics. Common in "
            "advanced red team operations."
        ),
        threat_actors=["Advanced red teams", "APT groups with custom C2 profiles"],
        impersonate="chrome131",
        tls_permute_extensions=True,
        tls_grease=True,
    ),

    "sliver_c2": JARMProfile(
        name="Sliver C2",
        description=(
            "Simulates Sliver C2 HTTPS listener traffic. Sliver uses Go's "
            "crypto/tls which has distinctive JA3 characteristics."
        ),
        threat_actors=[
            "FIN12",
            "Various ransomware operators (Conti successors)",
        ],
        # Go TLS has different cipher ordering than browsers
        impersonate="chrome119",
        tls_permute_extensions=False,
        tls_grease=False,
        http2_no_priority=False,
    ),

    "metasploit_meterpreter": JARMProfile(
        name="Metasploit Meterpreter (HTTPS)",
        description=(
            "Simulates Metasploit's HTTPS Meterpreter transport. "
            "Uses Ruby/OpenSSL TLS stack characteristics."
        ),
        threat_actors=[
            "Penetration testers",
            "Low-sophistication attackers",
        ],
        impersonate="chrome99",
        tls_permute_extensions=False,
        tls_grease=False,
    ),

    "brute_ratel_c4": JARMProfile(
        name="Brute Ratel C4 (Badger)",
        description=(
            "Simulates Brute Ratel C4 badger HTTPS traffic. "
            "Designed to evade Cobalt Strike detection signatures."
        ),
        threat_actors=[
            "APT29 (used post-Cobalt Strike detection)",
            "BlackCat/ALPHV ransomware affiliates",
        ],
        impersonate="chrome131",
        tls_permute_extensions=True,
        tls_grease=True,
        tls_cert_compression=True,
    ),

    "havoc_c2": JARMProfile(
        name="Havoc C2",
        description=(
            "Simulates Havoc C2 framework HTTPS traffic. "
            "Modern C2 framework with browser-like TLS characteristics."
        ),
        threat_actors=["Emerging threat actors", "Red teams"],
        impersonate="chrome124",
        tls_permute_extensions=True,
        tls_grease=True,
    ),

    "mythic_c2": JARMProfile(
        name="Mythic C2",
        description=(
            "Simulates Mythic C2 framework HTTPS agents. "
            "Supports multiple agent types with different TLS profiles."
        ),
        threat_actors=["Red teams", "Penetration testers"],
        impersonate="chrome120",
        tls_permute_extensions=True,
        tls_grease=True,
    ),

    "tor_exit_node": JARMProfile(
        name="Tor Exit Node Traffic",
        description=(
            "Simulates HTTP traffic originating from Tor exit nodes. "
            "Tor has distinctive TLS characteristics in its exit relay traffic."
        ),
        threat_actors=[
            "Anonymous threat actors",
            "APT groups using Tor for C2",
            "Hacktivists",
        ],
        impersonate="tor145",
        tls_permute_extensions=False,
        tls_grease=False,
    ),

    "python_requests": JARMProfile(
        name="Python requests/httpx",
        description=(
            "Simulates standard Python HTTP client TLS fingerprint. "
            "Used by many automated tools, scanners, and scripts."
        ),
        threat_actors=[
            "Automated scanners",
            "Script-based attacks",
            "Bug bounty recon tools",
        ],
        # Python's ssl module has a distinctive JA3
        impersonate="chrome99",
        tls_permute_extensions=False,
        tls_grease=False,
        http2_no_priority=True,
    ),

    "wget_curl_default": JARMProfile(
        name="curl/wget default",
        description=(
            "Simulates command-line curl or wget TLS fingerprint. "
            "Default OpenSSL TLS characteristics."
        ),
        threat_actors=[
            "Manual reconnaissance",
            "Script kiddies",
            "Automated tools",
        ],
        impersonate="chrome99",
        tls_permute_extensions=False,
        tls_grease=False,
        tls_cert_compression=False,
    ),
}


# ---------------------------------------------------------------------------
# Profile lookup
# ---------------------------------------------------------------------------

def get_profile(name: str) -> JARMProfile:
    """
    Get a fingerprint profile by name.

    Raises KeyError if profile not found.
    """
    if name not in FINGERPRINT_PROFILES:
        available = ", ".join(sorted(FINGERPRINT_PROFILES.keys()))
        raise KeyError(
            f"Unknown profile {name!r}. Available: {available}"
        )
    return FINGERPRINT_PROFILES[name]


def list_profiles(category: Optional[str] = None) -> List[str]:
    """
    List available profile names.

    Args:
        category: Filter by category. Options:
            - "browser": Legitimate browser profiles
            - "adversary": Threat actor / C2 profiles
            - None: All profiles
    """
    if category is None:
        return sorted(FINGERPRINT_PROFILES.keys())

    if category == "browser":
        return sorted(
            name for name, p in FINGERPRINT_PROFILES.items()
            if not p.threat_actors
        )
    elif category == "adversary":
        return sorted(
            name for name, p in FINGERPRINT_PROFILES.items()
            if p.threat_actors
        )
    else:
        raise ValueError(f"Unknown category {category!r}. Use 'browser' or 'adversary'.")


# ---------------------------------------------------------------------------
# Fingerprint Randomization
# ---------------------------------------------------------------------------

# Chrome TLS cipher suites (subset, for randomization)
_CHROME_CIPHER_SUITES = [
    "4865",  # TLS_AES_128_GCM_SHA256
    "4866",  # TLS_AES_256_GCM_SHA384
    "4867",  # TLS_CHACHA20_POLY1305_SHA256
    "49195", # TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256
    "49199", # TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
    "49196", # TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384
    "49200", # TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
    "52393", # TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256
    "52392", # TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256
    "49171", # TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA
    "49172", # TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA
    "156",   # TLS_RSA_WITH_AES_128_GCM_SHA256
    "157",   # TLS_RSA_WITH_AES_256_GCM_SHA384
]

# TLS extensions commonly used by browsers
_TLS_EXTENSIONS = "0-23-65281-10-11-35-16-5-13-18-51-45-43-27-17513"

# EC point formats
_EC_POINT_FORMATS = "0"

# Supported groups (elliptic curves)
_CHROME_GROUPS = "29-23-24"


def _build_ja3_string(
    tls_version: str = "771",
    ciphers: Optional[List[str]] = None,
    extensions: Optional[str] = None,
    groups: Optional[str] = None,
    ec_formats: Optional[str] = None,
) -> str:
    """Build a JA3 fingerprint string from components."""
    if ciphers is None:
        ciphers = _CHROME_CIPHER_SUITES
    if extensions is None:
        extensions = _TLS_EXTENSIONS
    if groups is None:
        groups = _CHROME_GROUPS
    if ec_formats is None:
        ec_formats = _EC_POINT_FORMATS

    cipher_str = "-".join(ciphers)
    return f"{tls_version},{cipher_str},{extensions},{groups},{ec_formats}"


def randomize_fingerprint(
    base: str = "chrome_131_windows",
    vary_ciphers: bool = True,
    vary_extensions: bool = False,
    vary_groups: bool = False,
) -> JARMProfile:
    """
    Create a randomized fingerprint profile based on a base profile.

    Applies slight randomization to JA3 components while maintaining
    browser plausibility. This helps evade statistical JA3 clustering
    detections that flag identical TLS fingerprints across many requests.

    Args:
        base: Base profile name to randomize from.
        vary_ciphers: Randomize cipher suite ordering (within TLS rules).
        vary_extensions: Slightly vary extension order.
        vary_groups: Vary supported groups ordering.

    Returns:
        A new JARMProfile with randomized TLS characteristics.
    """
    base_profile = get_profile(base)

    ciphers = list(_CHROME_CIPHER_SUITES)
    ext_parts = _TLS_EXTENSIONS.split("-")
    groups = _CHROME_GROUPS.split("-")

    if vary_ciphers:
        # Shuffle TLS 1.3 ciphers (first 3) separately from TLS 1.2
        t13 = ciphers[:3]
        t12 = ciphers[3:]
        random.shuffle(t13)
        random.shuffle(t12)
        ciphers = t13 + t12

    if vary_extensions:
        # Keep critical extensions in place, shuffle others
        critical = {"0", "65281", "10", "11", "13"}  # SNI, compression, SG, supported_versions, PSK
        crit_ext = [e for e in ext_parts if e in critical]
        other_ext = [e for e in ext_parts if e not in critical]
        random.shuffle(other_ext)
        ext_parts = crit_ext + other_ext

    if vary_groups:
        random.shuffle(groups)

    ja3 = _build_ja3_string(
        ciphers=ciphers,
        extensions="-".join(ext_parts),
        groups="-".join(groups),
    )

    return JARMProfile(
        name=f"{base_profile.name} (randomized)",
        description=f"Randomized variant of {base_profile.name}",
        threat_actors=list(base_profile.threat_actors),
        ja3=ja3,
        akamai=base_profile.akamai,
        impersonate=base_profile.impersonate,
        tls_permute_extensions=True,  # Always enable for randomized profiles
        tls_grease=base_profile.tls_grease,
        tls_record_size_limit=base_profile.tls_record_size_limit,
        tls_cert_compression=base_profile.tls_cert_compression,
        http2_no_priority=base_profile.http2_no_priority,
        http2_stream_exclusive=base_profile.http2_stream_exclusive,
        http2_stream_weight=base_profile.http2_stream_weight,
    )


def get_ja3_hash(ja3_string: str) -> str:
    """Compute MD5 hash of a JA3 string (the JA3 digest)."""
    return hashlib.md5(ja3_string.encode()).hexdigest()
