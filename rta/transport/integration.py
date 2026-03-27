"""
RTA Transport Integration — Factory functions and helpers.

Provides drop-in replacements for httpx.Client / httpx.AsyncClient
that use curl_cffi for TLS fingerprint spoofing. Also includes
helpers for rotating fingerprints across requests and integrating
with RTA-GUARD's existing HTTP infrastructure.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    Generator,
    List,
    Optional,
    Sequence,
    Union,
)

import httpx
from curl_cffi.requests import BrowserType, ExtraFingerprints

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

logger = logging.getLogger("rta.transport.integration")


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

def _env_config() -> Dict[str, Any]:
    """Read transport config from environment variables."""
    config: Dict[str, Any] = {}

    impersonate = os.getenv("RTA_CURL_IMPERSONATE")
    if impersonate:
        config["impersonate"] = impersonate

    ja3 = os.getenv("RTA_CURL_JA3")
    if ja3:
        config["ja3"] = ja3

    akamai = os.getenv("RTA_CURL_AKAMAI")
    if akamai:
        config["akamai"] = akamai

    proxy = os.getenv("RTA_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        config["proxy"] = proxy

    verify = os.getenv("RTA_TLS_VERIFY", "true").lower()
    config["verify"] = verify not in ("false", "0", "no")

    timeout = os.getenv("RTA_TIMEOUT")
    if timeout:
        config["timeout"] = float(timeout)

    return config


# ---------------------------------------------------------------------------
# Factory Functions
# ---------------------------------------------------------------------------

def create_transport(
    profile: Optional[str] = None,
    impersonate: Optional[Union[BrowserType, str]] = None,
    ja3: Optional[str] = None,
    akamai: Optional[str] = None,
    extra_fp: Optional[ExtraFingerprints] = None,
    verify: Optional[bool] = None,
    proxy: Optional[Union[str, Dict[str, str]]] = None,
    timeout: Optional[float] = None,
    randomized: bool = False,
    **kwargs: Any,
) -> CurlCffiTransport:
    """
    Create a synchronous curl_cffi httpx transport.

    Args:
        profile: Named profile from rta.transport.fingerprint (e.g., "chrome_131_windows").
        impersonate: Browser type to impersonate (overrides profile).
        ja3: Raw JA3 string (overrides profile and impersonate).
        akamai: Akamai HTTP/2 fingerprint string.
        extra_fp: ExtraFingerprints for fine-grained control.
        verify: Whether to verify TLS certificates.
        proxy: Proxy URL or dict of per-scheme proxies.
        timeout: Request timeout in seconds.
        randomized: If True, apply randomization to the selected profile.

    Returns:
        Configured CurlCffiTransport ready for use with httpx.Client.

    Example::

        transport = create_transport(profile="chrome_131_windows")
        with httpx.Client(transport=transport) as client:
            resp = client.get("https://example.com")
    """
    env = _env_config()
    config = _build_config(
        profile=profile,
        impersonate=impersonate,
        ja3=ja3,
        akamai=akamai,
        extra_fp=extra_fp,
        verify=verify,
        proxy=proxy,
        timeout=timeout,
        randomized=randomized,
        env=env,
        **kwargs,
    )
    return CurlCffiTransport(config=config)


def create_async_transport(
    profile: Optional[str] = None,
    impersonate: Optional[Union[BrowserType, str]] = None,
    ja3: Optional[str] = None,
    akamai: Optional[str] = None,
    extra_fp: Optional[ExtraFingerprints] = None,
    verify: Optional[bool] = None,
    proxy: Optional[Union[str, Dict[str, str]]] = None,
    timeout: Optional[float] = None,
    randomized: bool = False,
    max_clients: int = 10,
    **kwargs: Any,
) -> CurlCffiAsyncTransport:
    """
    Create an async curl_cffi httpx transport.

    Same parameters as create_transport(), plus:
        max_clients: Maximum concurrent connections.

    Example::

        transport = create_async_transport(impersonate="chrome131")
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get("https://example.com")
    """
    env = _env_config()
    config = _build_config(
        profile=profile,
        impersonate=impersonate,
        ja3=ja3,
        akamai=akamai,
        extra_fp=extra_fp,
        verify=verify,
        proxy=proxy,
        timeout=timeout,
        randomized=randomized,
        env=env,
        **kwargs,
    )
    return CurlCffiAsyncTransport(config=config, max_clients=max_clients)


def create_client(
    profile: Optional[str] = None,
    impersonate: Optional[Union[BrowserType, str]] = None,
    ja3: Optional[str] = None,
    akamai: Optional[str] = None,
    extra_fp: Optional[ExtraFingerprints] = None,
    verify: Optional[bool] = None,
    proxy: Optional[Union[str, Dict[str, str]]] = None,
    timeout: Optional[float] = None,
    randomized: bool = False,
    base_url: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    follow_redirects: bool = True,
    **kwargs: Any,
) -> httpx.Client:
    """
    Create an httpx.Client with curl_cffi TLS fingerprinting.

    Drop-in replacement for httpx.Client() with anti-fingerprint capabilities.

    Example::

        with create_client(impersonate="chrome131") as client:
            resp = client.get("https://target.com/api")
    """
    transport = create_transport(
        profile=profile,
        impersonate=impersonate,
        ja3=ja3,
        akamai=akamai,
        extra_fp=extra_fp,
        verify=verify,
        proxy=proxy,
        timeout=timeout,
        randomized=randomized,
        **kwargs,
    )
    client_kwargs: Dict[str, Any] = {
        "transport": transport,
        "follow_redirects": follow_redirects,
    }
    if base_url is not None:
        client_kwargs["base_url"] = base_url
    if headers is not None:
        client_kwargs["headers"] = headers
    return httpx.Client(**client_kwargs)


def create_async_client(
    profile: Optional[str] = None,
    impersonate: Optional[Union[BrowserType, str]] = None,
    ja3: Optional[str] = None,
    akamai: Optional[str] = None,
    extra_fp: Optional[ExtraFingerprints] = None,
    verify: Optional[bool] = None,
    proxy: Optional[Union[str, Dict[str, str]]] = None,
    timeout: Optional[float] = None,
    randomized: bool = False,
    base_url: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    follow_redirects: bool = True,
    max_clients: int = 10,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """
    Create an httpx.AsyncClient with curl_cffi TLS fingerprinting.

    Drop-in replacement for httpx.AsyncClient() with anti-fingerprint capabilities.

    Example::

        async with create_async_client(impersonate="chrome131") as client:
            resp = await client.get("https://target.com/api")
    """
    transport = create_async_transport(
        profile=profile,
        impersonate=impersonate,
        ja3=ja3,
        akamai=akamai,
        extra_fp=extra_fp,
        verify=verify,
        proxy=proxy,
        timeout=timeout,
        randomized=randomized,
        max_clients=max_clients,
        **kwargs,
    )
    client_kwargs: Dict[str, Any] = {
        "transport": transport,
        "follow_redirects": follow_redirects,
    }
    if base_url is not None:
        client_kwargs["base_url"] = base_url
    if headers is not None:
        client_kwargs["headers"] = headers
    return httpx.AsyncClient(**client_kwargs)


# ---------------------------------------------------------------------------
# Context Managers
# ---------------------------------------------------------------------------

@contextmanager
def spoofed_client(
    profile: Optional[str] = None,
    impersonate: Optional[str] = None,
    randomized: bool = False,
    **kwargs: Any,
) -> Generator[httpx.Client, None, None]:
    """
    Context manager for an httpx.Client with TLS spoofing.

    Example::

        with spoofed_client(impersonate="chrome131") as client:
            resp = client.get("https://example.com")
    """
    client = create_client(
        profile=profile,
        impersonate=impersonate,
        randomized=randomized,
        **kwargs,
    )
    try:
        yield client
    finally:
        client.close()


@asynccontextmanager
async def async_spoofed_client(
    profile: Optional[str] = None,
    impersonate: Optional[str] = None,
    randomized: bool = False,
    **kwargs: Any,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Async context manager for an httpx.AsyncClient with TLS spoofing.

    Example::

        async with async_spoofed_client(impersonate="chrome131") as client:
            resp = await client.get("https://example.com")
    """
    client = create_async_client(
        profile=profile,
        impersonate=impersonate,
        randomized=randomized,
        **kwargs,
    )
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Rotating Fingerprints (Connection Pooling Evasion)
# ---------------------------------------------------------------------------

class RotatingTransport:
    """
    Transport that rotates TLS fingerprints across requests.

    Useful for evading statistical fingerprint clustering where a WAF
    tracks identical JA3 hashes from a single source IP.

    Usage::

        transport = RotatingTransport(
            profiles=["chrome_131_windows", "safari_18_macos", "firefox_135"],
            strategy="random",
        )
        with httpx.Client(transport=transport) as client:
            for url in urls:
                resp = client.get(url)  # Each request may use a different fingerprint
    """

    def __init__(
        self,
        profiles: Optional[List[str]] = None,
        browser_pool: Optional[List[str]] = None,
        adversary_pool: Optional[List[str]] = None,
        strategy: str = "random",
        randomize: bool = True,
    ) -> None:
        """
        Args:
            profiles: Specific profile names to rotate through.
            browser_pool: Use all browser profiles (if profiles is None).
            adversary_pool: Include adversary profiles in rotation.
            strategy: "random", "round_robin", or "weighted".
            randomize: Apply additional randomization to each profile.
        """
        self._profiles: List[JARMProfile] = []
        self._strategy = strategy
        self._randomize = randomize
        self._index = 0

        if profiles:
            self._profiles = [get_profile(p) for p in profiles]
        else:
            pool_names: List[str] = []
            if browser_pool or (browser_pool is None and adversary_pool is None):
                pool_names.extend(list_profiles("browser"))
            if adversary_pool:
                pool_names.extend(adversary_pool)
            self._profiles = [get_profile(p) for p in pool_names]

        if not self._profiles:
            raise ValueError("No profiles available for rotation")

        self._transports: List[CurlCffiTransport] = []
        for profile in self._profiles:
            if randomize:
                profile = randomize_fingerprint(profile.name.split(" (")[0].lower().replace(" ", "_"))
            self._transports.append(
                CurlCffiTransport(
                    config=TransportConfig(
                        impersonate=profile.impersonate,
                        ja3=profile.ja3,
                        akamai=profile.akamai,
                        extra_fp=profile.to_extra_fp(),
                    )
                )
            )

    def _get_next_transport(self) -> CurlCffiTransport:
        if self._strategy == "random":
            return random.choice(self._transports)
        elif self._strategy == "round_robin":
            t = self._transports[self._index % len(self._transports)]
            self._index += 1
            return t
        else:
            return self._transports[0]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        transport = self._get_next_transport()
        return transport.handle_request(request)

    def close(self) -> None:
        for t in self._transports:
            t.close()


class AsyncRotatingTransport(httpx.AsyncBaseTransport):
    """
    Async transport that rotates TLS fingerprints across requests.

    Usage::

        transport = AsyncRotatingTransport(
            profiles=["chrome_131_windows", "safari_18_macos"],
            strategy="round_robin",
        )
        async with httpx.AsyncClient(transport=transport) as client:
            for url in urls:
                resp = await client.get(url)
    """

    def __init__(
        self,
        profiles: Optional[List[str]] = None,
        browser_pool: bool = True,
        adversary_pool: Optional[List[str]] = None,
        strategy: str = "random",
        randomize: bool = True,
        max_clients: int = 10,
    ) -> None:
        self._strategy = strategy
        self._randomize = randomize
        self._index = 0
        self._transports: List[CurlCffiAsyncTransport] = []

        profile_list: List[JARMProfile] = []
        if profiles:
            profile_list = [get_profile(p) for p in profiles]
        else:
            pool_names: List[str] = []
            if browser_pool:
                pool_names.extend(list_profiles("browser"))
            if adversary_pool:
                pool_names.extend(adversary_pool)
            profile_list = [get_profile(p) for p in pool_names]

        for profile in profile_list:
            if randomize:
                # Use the profile name as base key
                base_key = [k for k, v in FINGERPRINT_PROFILES.items() if v.name == profile.name]
                if base_key:
                    profile = randomize_fingerprint(base_key[0])
            self._transports.append(
                CurlCffiAsyncTransport(
                    config=TransportConfig(
                        impersonate=profile.impersonate,
                        ja3=profile.ja3,
                        akamai=profile.akamai,
                        extra_fp=profile.to_extra_fp(),
                    ),
                    max_clients=max_clients,
                )
            )

        if not self._transports:
            raise ValueError("No profiles available for rotation")

    def _get_next_transport(self) -> CurlCffiAsyncTransport:
        if self._strategy == "random":
            return random.choice(self._transports)
        elif self._strategy == "round_robin":
            t = self._transports[self._index % len(self._transports)]
            self._index += 1
            return t
        else:
            return self._transports[0]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        transport = self._get_next_transport()
        return await transport.handle_async_request(request)

    async def aclose(self) -> None:
        for t in self._transports:
            await t.aclose()


# ---------------------------------------------------------------------------
# Monkey-patching helper
# ---------------------------------------------------------------------------

def replace_httpx_defaults(
    impersonate: str = "chrome131",
    verify: bool = True,
    **kwargs: Any,
) -> None:
    """
    Replace httpx's default transport factory with curl_cffi.

    WARNING: This monkey-patches httpx globally. Use with caution in
    libraries — prefer explicit transport configuration instead.

    After calling this, all new httpx.AsyncClient/httpx.Client instances
    will use curl_cffi with the specified fingerprint.

    Example::

        replace_httpx_defaults(impersonate="chrome131")
        # Now all httpx.AsyncClient() calls use curl_cffi
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://example.com")
    """
    config = TransportConfig(
        impersonate=impersonate,
        verify=verify,
        **kwargs,
    )

    _original_async_client_init = httpx.AsyncClient.__init__

    def _patched_async_client_init(self: httpx.AsyncClient, **client_kwargs: Any) -> None:
        if "transport" not in client_kwargs:
            client_kwargs["transport"] = CurlCffiAsyncTransport(config=config)
        _original_async_client_init(self, **client_kwargs)

    httpx.AsyncClient.__init__ = _patched_async_client_init  # type: ignore

    _original_client_init = httpx.Client.__init__

    def _patched_client_init(self: httpx.Client, **client_kwargs: Any) -> None:
        if "transport" not in client_kwargs:
            client_kwargs["transport"] = CurlCffiTransport(config=config)
        _original_client_init(self, **client_kwargs)

    httpx.Client.__init__ = _patched_client_init  # type: ignore

    logger.info(
        "httpx defaults replaced with curl_cffi (impersonate=%s)",
        impersonate,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_config(
    profile: Optional[str],
    impersonate: Optional[Union[BrowserType, str]],
    ja3: Optional[str],
    akamai: Optional[str],
    extra_fp: Optional[ExtraFingerprints],
    verify: Optional[bool],
    proxy: Optional[Union[str, Dict[str, str]]],
    timeout: Optional[float],
    randomized: bool,
    env: Dict[str, Any],
    **kwargs: Any,
) -> TransportConfig:
    """Build TransportConfig from arguments, profile, and environment."""
    # Start with environment config
    config_dict: Dict[str, Any] = dict(env)

    # Apply profile if specified
    if profile is not None:
        if randomized:
            p = randomize_fingerprint(profile)
        else:
            p = get_profile(profile)
        if p.impersonate is not None:
            config_dict["impersonate"] = p.impersonate
        if p.ja3 is not None:
            config_dict["ja3"] = p.ja3
        if p.akamai is not None:
            config_dict["akamai"] = p.akamai
        fp = p.to_extra_fp()
        if fp is not None:
            config_dict["extra_fp"] = fp

    # Explicit arguments override profile and env
    if impersonate is not None:
        config_dict["impersonate"] = impersonate
    if ja3 is not None:
        config_dict["ja3"] = ja3
    if akamai is not None:
        config_dict["akamai"] = akamai
    if extra_fp is not None:
        config_dict["extra_fp"] = extra_fp
    if verify is not None:
        config_dict["verify"] = verify
    if proxy is not None:
        config_dict["proxy"] = proxy
    if timeout is not None:
        config_dict["timeout"] = timeout

    # Merge remaining kwargs
    for k, v in kwargs.items():
        if v is not None:
            config_dict[k] = v

    return TransportConfig(**config_dict)
