"""
CurlCffi HTTPX Transport — Production-grade TLS fingerprint spoofing.

Drop-in replacement for httpx.AsyncHTTPTransport / httpx.HTTPTransport that
routes requests through curl_cffi for browser-grade TLS fingerprinting,
JA3/Akamai impersonation, and HTTP/2 pseudo-header ordering.

Usage:
    import httpx
    from rta.transport import CurlCffiAsyncTransport

    transport = CurlCffiAsyncTransport(impersonate="chrome131")
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://example.com")
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import httpx
from curl_cffi import requests as curl_requests
from curl_cffi.requests import BrowserType, ExtraFingerprints

logger = logging.getLogger("rta.transport.curl_cffi_httpx")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TransportConfig:
    """Configuration for curl_cffi HTTPX transport."""

    # Browser impersonation — a BrowserType enum value or string like "chrome131"
    impersonate: Optional[Union[BrowserType, str]] = None

    # Raw JA3 fingerprint string (overrides impersonate for TLS)
    ja3: Optional[str] = None

    # Akamai HTTP/2 fingerprint string (overrides impersonate for H2)
    akamai: Optional[str] = None

    # Extra TLS/HTTP2 fingerprint options
    extra_fp: Optional[ExtraFingerprints] = None

    # TLS certificate verification
    verify: bool = True

    # Proxy configuration
    #   Single proxy: "http://proxy:8080"
    #   Per-scheme: {"http": "...", "https": "..."}
    proxy: Optional[Union[str, Dict[str, str]]] = None

    # Proxy authentication
    proxy_auth: Optional[Tuple[str, str]] = None

    # Default timeout in seconds (can be overridden per-request)
    timeout: float = 30.0

    # HTTP version preference
    http_version: Optional[str] = None  # "h2", "h1.1", or None for auto

    # Network interface to bind to
    interface: Optional[str] = None

    # Maximum redirects to follow (-1 = unlimited)
    max_redirects: int = 30

    # Accept-Encoding header
    accept_encoding: str = "gzip, deflate, br"

    # Custom default headers
    headers: Optional[Dict[str, str]] = None

    # Client certificate (cert_file, key_file)
    cert: Optional[Tuple[str, str]] = None


# ---------------------------------------------------------------------------
# httpx Response stream wrapper
# ---------------------------------------------------------------------------

class CurlByteStream(httpx.SyncByteStream):
    """Synchronous byte stream from curl_cffi response content."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def __iter__(self) -> Iterator[bytes]:
        yield self._content


class CurlAsyncByteStream(httpx.AsyncByteStream):
    """Asynchronous byte stream from curl_cffi response content."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._content


# ---------------------------------------------------------------------------
# Helper: convert httpx.Request → curl_cffi params
# ---------------------------------------------------------------------------

def _build_curl_params(
    request: httpx.Request,
    config: TransportConfig,
) -> Dict[str, Any]:
    """Build curl_cffi request kwargs from an httpx.Request and config."""
    params: Dict[str, Any] = {
        "method": request.method,
        "url": str(request.url),
        "headers": list(request.headers.raw),
        "data": request.content,
        "allow_redirects": config.max_redirects != 0,
        "max_redirects": config.max_redirects if config.max_redirects > 0 else 999,
        "verify": config.verify,
        "accept_encoding": config.accept_encoding,
    }

    # Impersonation
    if config.impersonate is not None:
        params["impersonate"] = config.impersonate
    if config.ja3 is not None:
        params["ja3"] = config.ja3
    if config.akamai is not None:
        params["akamai"] = config.akamai
    if config.extra_fp is not None:
        params["extra_fp"] = config.extra_fp

    # Proxy
    if config.proxy is not None:
        if isinstance(config.proxy, str):
            params["proxy"] = config.proxy
        else:
            params["proxies"] = config.proxy
    if config.proxy_auth is not None:
        params["proxy_auth"] = config.proxy_auth

    # Timeout from request or config
    timeout = request.extensions.get("timeout")
    if timeout is not None:
        params["timeout"] = timeout
    else:
        params["timeout"] = config.timeout

    # Network interface
    if config.interface is not None:
        params["interface"] = config.interface

    # HTTP version
    if config.http_version is not None:
        params["http_version"] = config.http_version

    # Client cert
    if config.cert is not None:
        params["cert"] = config.cert

    return params


def _curl_response_to_httpx(
    curl_resp: curl_requests.Response,
    request: httpx.Request,
) -> httpx.Response:
    """Convert a curl_cffi Response to an httpx Response."""
    # Extract headers — curl_cffi returns list of (name, value) tuples
    headers = list(curl_resp.headers.raw)

    # Build httpx extensions
    extensions: Dict[str, Any] = {}
    if hasattr(curl_resp, "http_version"):
        extensions["http_version"] = str(curl_resp.http_version)
    extensions["reason_phrase"] = curl_resp.reason if hasattr(curl_resp, "reason") else ""
    extensions["redirected"] = len(curl_resp.redirect_url or "") > 0

    return httpx.Response(
        status_code=curl_resp.status_code,
        headers=headers,
        content=curl_resp.content,
        request=request,
        extensions=extensions,
    )


# ---------------------------------------------------------------------------
# Synchronous Transport
# ---------------------------------------------------------------------------

class CurlCffiTransport(httpx.BaseTransport):
    """
    Synchronous httpx transport backed by curl_cffi.

    Provides browser-grade TLS fingerprinting, JA3/Akamai impersonation,
    and HTTP/2 pseudo-header ordering for anti-detection HTTP requests.

    Usage::

        import httpx
        from rta.transport import CurlCffiTransport

        transport = CurlCffiTransport(impersonate="chrome131")
        with httpx.Client(transport=transport) as client:
            resp = client.get("https://example.com")
    """

    def __init__(
        self,
        config: Optional[TransportConfig] = None,
        *,
        impersonate: Optional[Union[BrowserType, str]] = None,
        ja3: Optional[str] = None,
        akamai: Optional[str] = None,
        extra_fp: Optional[ExtraFingerprints] = None,
        verify: bool = True,
        proxy: Optional[Union[str, Dict[str, str]]] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        if config is None:
            config = TransportConfig(
                impersonate=impersonate or kwargs.get("_impersonate"),
                ja3=ja3,
                akamai=akamai,
                extra_fp=extra_fp,
                verify=verify,
                proxy=proxy,
                timeout=timeout,
            )
            # Merge any additional kwargs
            for k, v in kwargs.items():
                if hasattr(config, k):
                    setattr(config, k, v)

        self._config = config
        self._session: Optional[curl_requests.Session] = None
        self._session_lock = asyncio.Lock()

    def _get_session(self) -> curl_requests.Session:
        if self._session is None:
            self._session = curl_requests.Session()
        return self._session

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Handle a synchronous HTTP request."""
        params = _build_curl_params(request, self._config)
        session = self._get_session()

        try:
            curl_resp = session.request(**params)
            return _curl_response_to_httpx(curl_resp, request)
        except curl_requests.CurlError as exc:
            raise httpx.ConnectError(str(exc)) from exc

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


# ---------------------------------------------------------------------------
# Asynchronous Transport (primary)
# ---------------------------------------------------------------------------

class CurlCffiAsyncTransport(httpx.AsyncBaseTransport):
    """
    Async httpx transport backed by curl_cffi.

    Provides browser-grade TLS fingerprinting, JA3/Akamai impersonation,
    and HTTP/2 pseudo-header ordering for anti-detection HTTP requests.

    This is the recommended transport for RTA-GUARD's outbound HTTP requests,
    ensuring TLS fingerprints match real browsers and bypass JA3-based WAFs.

    Usage::

        import httpx
        from rta.transport import CurlCffiAsyncTransport

        transport = CurlCffiAsyncTransport(impersonate="chrome131")
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get("https://example.com")

    JA3 Spoofing::

        # Use a specific JA3 string
        transport = CurlCffiAsyncTransport(
            ja3="771,4865-4866-4867-49195-49199-49196-49200-52393-52392-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-18-51-45-43-27-17513,29-23-24,0"
        )

    Browser Impersonation::

        # Chrome 131 on Windows
        transport = CurlCffiAsyncTransport(impersonate="chrome131")

        # Safari 18.0 on macOS
        transport = CurlCffiAsyncTransport(impersonate="safari18_0")

        # Firefox 135
        transport = CurlCffiAsyncTransport(impersonate="firefox135")

    Advanced Fingerprint Control::

        from curl_cffi.requests import ExtraFingerprints
        transport = CurlCffiAsyncTransport(
            impersonate="chrome131",
            extra_fp=ExtraFingerprints(
                tls_permute_extensions=True,
                tls_grease=True,
                tls_signature_algorithms=[0x0403, 0x0804, 0x0401, 0x0503],
            ),
        )
    """

    def __init__(
        self,
        config: Optional[TransportConfig] = None,
        *,
        impersonate: Optional[Union[BrowserType, str]] = None,
        ja3: Optional[str] = None,
        akamai: Optional[str] = None,
        extra_fp: Optional[ExtraFingerprints] = None,
        verify: bool = True,
        proxy: Optional[Union[str, Dict[str, str]]] = None,
        timeout: float = 30.0,
        max_clients: int = 10,
        **kwargs: Any,
    ) -> None:
        if config is None:
            config = TransportConfig(
                impersonate=impersonate,
                ja3=ja3,
                akamai=akamai,
                extra_fp=extra_fp,
                verify=verify,
                proxy=proxy,
                timeout=timeout,
            )
            for k, v in kwargs.items():
                if hasattr(config, k):
                    setattr(config, k, v)

        self._config = config
        self._max_clients = max_clients
        self._session: Optional[curl_requests.AsyncSession] = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> curl_requests.AsyncSession:
        if self._session is None:
            async with self._session_lock:
                if self._session is None:
                    self._session = curl_requests.AsyncSession(
                        max_clients=self._max_clients,
                    )
        return self._session

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """
        Handle an async HTTP request through curl_cffi.

        Converts the httpx.Request to curl_cffi parameters, executes the
        request with the configured fingerprint profile, and converts
        the response back to httpx.Response.
        """
        params = _build_curl_params(request, self._config)
        session = await self._get_session()

        try:
            curl_resp = await session.request(**params)
            return _curl_response_to_httpx(curl_resp, request)
        except curl_requests.CurlError as exc:
            # Map curl errors to httpx exceptions
            error_str = str(exc).lower()
            if "timeout" in error_str:
                raise httpx.TimeoutException(str(exc)) from exc
            elif "connect" in error_str or "couldn't connect" in error_str:
                raise httpx.ConnectError(str(exc)) from exc
            elif "ssl" in error_str or "certificate" in error_str:
                raise httpx.ConnectError(f"SSL error: {exc}") from exc
            else:
                raise httpx.RequestError(str(exc)) from exc

    async def aclose(self) -> None:
        """Close the underlying curl_cffi session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "CurlCffiAsyncTransport":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
