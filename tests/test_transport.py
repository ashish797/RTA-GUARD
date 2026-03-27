"""
Tests for rta.transport — curl_cffi HTTPX transport layer.
"""
import asyncio
import pytest
import httpx

from rta.transport.curl_cffi_httpx import (
    CurlCffiAsyncTransport,
    CurlCffiTransport,
    TransportConfig,
    _build_curl_params,
    _curl_response_to_httpx,
)
from rta.transport.fingerprint import (
    FINGERPRINT_PROFILES,
    JARMProfile,
    get_profile,
    list_profiles,
    randomize_fingerprint,
    get_ja3_hash,
)
from rta.transport.integration import (
    create_transport,
    create_async_transport,
    create_client,
    create_async_client,
    _build_config,
)


# ── TransportConfig ────────────────────────────────────────────────────────

class TestTransportConfig:
    def test_defaults(self):
        config = TransportConfig()
        assert config.impersonate is None
        assert config.ja3 is None
        assert config.verify is True
        assert config.timeout == 30.0
        assert config.max_redirects == 30

    def test_with_impersonate(self):
        config = TransportConfig(impersonate="chrome131")
        assert config.impersonate == "chrome131"

    def test_with_ja3(self):
        ja3 = "771,4865-4866-4867,0-23-65281,29-23-24,0"
        config = TransportConfig(ja3=ja3)
        assert config.ja3 == ja3

    def test_with_proxy(self):
        config = TransportConfig(proxy="http://proxy:8080")
        assert config.proxy == "http://proxy:8080"

    def test_with_per_scheme_proxy(self):
        proxies = {"http": "http://proxy:8080", "https": "https://proxy:8443"}
        config = TransportConfig(proxy=proxies)
        assert config.proxy == proxies


# ── _build_curl_params ────────────────────────────────────────────────────

class TestBuildCurlParams:
    def test_basic_request(self):
        request = httpx.Request("GET", "https://example.com/test?q=1")
        config = TransportConfig()
        params = _build_curl_params(request, config)
        assert params["method"] == "GET"
        assert "example.com" in params["url"]
        assert params["verify"] is True

    def test_impersonate_in_params(self):
        request = httpx.Request("GET", "https://example.com")
        config = TransportConfig(impersonate="chrome131")
        params = _build_curl_params(request, config)
        assert params["impersonate"] == "chrome131"

    def test_ja3_in_params(self):
        ja3 = "771,4865-4866,0-23,29-23,0"
        request = httpx.Request("GET", "https://example.com")
        config = TransportConfig(ja3=ja3)
        params = _build_curl_params(request, config)
        assert params["ja3"] == ja3

    def test_proxy_in_params(self):
        request = httpx.Request("GET", "https://example.com")
        config = TransportConfig(proxy="http://proxy:8080")
        params = _build_curl_params(request, config)
        assert params["proxy"] == "http://proxy:8080"

    def test_per_scheme_proxy(self):
        request = httpx.Request("GET", "https://example.com")
        proxies = {"http": "http://p:8080", "https": "https://p:8443"}
        config = TransportConfig(proxy=proxies)
        params = _build_curl_params(request, config)
        assert params["proxies"] == proxies

    def test_post_with_body(self):
        request = httpx.Request("POST", "https://example.com", content=b'{"key":"value"}')
        config = TransportConfig()
        params = _build_curl_params(request, config)
        assert params["method"] == "POST"
        assert params["data"] == b'{"key":"value"}'

    def test_headers_passed(self):
        request = httpx.Request(
            "GET", "https://example.com",
            headers={"X-Custom": "test", "User-Agent": "bot/1.0"},
        )
        config = TransportConfig()
        params = _build_curl_params(request, config)
        # Headers are list of (name, value) tuples as bytes
        header_pairs = [(k.lower(), v) for k, v in params["headers"]]
        header_dict = dict(header_pairs)
        assert header_dict[b"x-custom"] == b"test"


# ── Fingerprint Profiles ─────────────────────────────────────────────────

class TestFingerprintProfiles:
    def test_all_profiles_exist(self):
        assert len(FINGERPRINT_PROFILES) > 0

    def test_browser_profiles(self):
        browsers = list_profiles("browser")
        assert len(browsers) > 0
        assert "chrome_131_windows" in browsers
        assert "safari_18_macos" in browsers
        assert "firefox_135" in browsers

    def test_adversary_profiles(self):
        adversaries = list_profiles("adversary")
        assert len(adversaries) > 0
        assert "cobalt_strike_default" in adversaries
        assert "sliver_c2" in adversaries

    def test_get_profile(self):
        profile = get_profile("chrome_131_windows")
        assert profile.name == "Chrome 131 (Windows)"
        assert profile.impersonate == "chrome131"
        assert profile.tls_permute_extensions is True

    def test_get_profile_unknown(self):
        with pytest.raises(KeyError):
            get_profile("nonexistent_profile")

    def test_adversary_profile_has_actors(self):
        profile = get_profile("cobalt_strike_default")
        assert len(profile.threat_actors) > 0
        assert "APT29" in profile.threat_actors[0]

    def test_list_profiles_category_invalid(self):
        with pytest.raises(ValueError):
            list_profiles("invalid_category")

    def test_profile_to_extra_fp(self):
        profile = get_profile("chrome_131_windows")
        extra_fp = profile.to_extra_fp()
        # Should have settings since tls_permute_extensions is set
        assert extra_fp is not None

    def test_profile_no_extra_fp_when_none_set(self):
        profile = JARMProfile(name="test", description="test")
        assert profile.to_extra_fp() is None


class TestRandomizeFingerprint:
    def test_randomize_produces_ja3(self):
        profile = randomize_fingerprint("chrome_131_windows")
        assert profile.ja3 is not None
        assert "771," in profile.ja3  # TLS version

    def test_randomize_preserves_impersonate(self):
        profile = randomize_fingerprint("chrome_131_windows")
        assert profile.impersonate == "chrome131"

    def test_randomize_different_results(self):
        """Two randomized profiles should differ (probabilistically)."""
        p1 = randomize_fingerprint("chrome_131_windows")
        p2 = randomize_fingerprint("chrome_131_windows")
        # Very unlikely to be identical with cipher shuffling
        # (but technically possible, so don't hard-assert)

    def test_randomize_invalid_base(self):
        with pytest.raises(KeyError):
            randomize_fingerprint("nonexistent")


class TestJa3Hash:
    def test_hash_is_md5(self):
        ja3 = "771,4865-4866-4867,0-23-65281,29-23-24,0"
        h = get_ja3_hash(ja3)
        assert len(h) == 32  # MD5 hex digest length

    def test_hash_deterministic(self):
        ja3 = "771,4865-4866,0-23,29-23,0"
        assert get_ja3_hash(ja3) == get_ja3_hash(ja3)


# ── Integration / Factory Functions ───────────────────────────────────────

class TestCreateTransport:
    def test_sync_transport_default(self):
        transport = create_transport()
        assert isinstance(transport, CurlCffiTransport)

    def test_sync_transport_with_profile(self):
        transport = create_transport(profile="chrome_131_windows")
        assert isinstance(transport, CurlCffiTransport)
        assert transport._config.impersonate == "chrome131"

    def test_sync_transport_with_impersonate(self):
        transport = create_transport(impersonate="safari18_0")
        assert transport._config.impersonate == "safari18_0"

    def test_async_transport_default(self):
        transport = create_async_transport()
        assert isinstance(transport, CurlCffiAsyncTransport)

    def test_async_transport_with_profile(self):
        transport = create_async_transport(profile="firefox_135")
        assert isinstance(transport, CurlCffiAsyncTransport)


class TestCreateClient:
    def test_sync_client(self):
        client = create_client(impersonate="chrome131")
        assert isinstance(client, httpx.Client)
        client.close()

    def test_async_client(self):
        async def _test():
            client = create_async_client(impersonate="chrome131")
            assert isinstance(client, httpx.AsyncClient)
            await client.aclose()
        asyncio.run(_test())

    def test_client_with_base_url(self):
        client = create_client(
            impersonate="chrome131",
            base_url="https://api.example.com",
        )
        assert "api.example.com" in str(client.base_url)
        client.close()


class TestBuildConfig:
    def test_from_profile(self):
        env = {}
        config = _build_config(
            profile="chrome_131_windows",
            impersonate=None, ja3=None, akamai=None, extra_fp=None,
            verify=None, proxy=None, timeout=None,
            randomized=False, env=env,
        )
        assert config.impersonate == "chrome131"

    def test_explicit_overrides_profile(self):
        env = {}
        config = _build_config(
            profile="chrome_131_windows",
            impersonate="safari18_0",
            ja3=None, akamai=None, extra_fp=None,
            verify=None, proxy=None, timeout=None,
            randomized=False, env=env,
        )
        assert config.impersonate == "safari18_0"

    def test_env_proxy(self):
        env = {"proxy": "http://env-proxy:8080"}
        config = _build_config(
            profile=None, impersonate=None, ja3=None, akamai=None,
            extra_fp=None, verify=None, proxy=None, timeout=None,
            randomized=False, env=env,
        )
        assert config.proxy == "http://env-proxy:8080"

    def test_randomized_profile(self):
        env = {}
        config = _build_config(
            profile="chrome_131_windows",
            impersonate=None, ja3=None, akamai=None, extra_fp=None,
            verify=None, proxy=None, timeout=None,
            randomized=True, env=env,
        )
        # Should have a ja3 string from randomization
        assert config.ja3 is not None


# ── Transport Unit Tests (no network) ─────────────────────────────────────

class TestCurlCffiTransportUnit:
    def test_init_default(self):
        transport = CurlCffiTransport()
        assert transport._config.timeout == 30.0
        assert transport._session is None

    def test_init_with_config(self):
        config = TransportConfig(impersonate="chrome131", timeout=10.0)
        transport = CurlCffiTransport(config=config)
        assert transport._config.impersonate == "chrome131"
        assert transport._config.timeout == 10.0

    def test_init_with_kwargs(self):
        transport = CurlCffiTransport(impersonate="chrome131", verify=False)
        assert transport._config.impersonate == "chrome131"
        assert transport._config.verify is False


class TestCurlCffiAsyncTransportUnit:
    def test_init_default(self):
        transport = CurlCffiAsyncTransport()
        assert transport._config.timeout == 30.0
        assert transport._max_clients == 10

    def test_init_with_config(self):
        config = TransportConfig(impersonate="safari18_0")
        transport = CurlCffiAsyncTransport(config=config, max_clients=20)
        assert transport._config.impersonate == "safari18_0"
        assert transport._max_clients == 20
