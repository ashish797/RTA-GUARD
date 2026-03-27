"""
rta.transport — RTA-GUARD HTTP Transport Layer

Provides curl_cffi-based HTTPX transports for TLS fingerprint spoofing,
browser impersonation, and anti-detection HTTP requests.
"""
from rta.transport.curl_cffi_httpx import (
    CurlCffiAsyncTransport,
    CurlCffiTransport,
    TransportConfig,
)
from rta.transport.fingerprint import (
    FINGERPRINT_PROFILES,
    JARMProfile,
    get_profile,
    list_profiles,
    randomize_fingerprint,
)
from rta.transport.integration import (
    create_async_client,
    create_client,
    replace_httpx_defaults,
)

__all__ = [
    "CurlCffiAsyncTransport",
    "CurlCffiTransport",
    "TransportConfig",
    "FINGERPRINT_PROFILES",
    "JARMProfile",
    "get_profile",
    "list_profiles",
    "randomize_fingerprint",
    "create_async_client",
    "create_client",
    "replace_httpx_defaults",
]
