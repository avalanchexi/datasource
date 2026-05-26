import asyncio

import pytest

from datasource.adapters import tavily_client
from datasource.adapters.tavily_client import AsyncTavilyClient


class FakeTimeout:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAsyncClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def aclose(self):
        return None


async def _open_client(client: AsyncTavilyClient) -> None:
    async with client:
        pass


def test_tavily_client_disables_trust_env_by_default(monkeypatch):
    created_clients = []

    def fake_async_client(**kwargs):
        client = FakeAsyncClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", fake_async_client)

    asyncio.run(_open_client(AsyncTavilyClient(api_key="k")))

    assert created_clients[0].kwargs["trust_env"] is False


def test_tavily_client_allows_explicit_trust_env(monkeypatch):
    created_clients = []

    def fake_async_client(**kwargs):
        client = FakeAsyncClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", fake_async_client)

    asyncio.run(_open_client(AsyncTavilyClient(api_key="k", trust_env=True)))

    assert created_clients[0].kwargs["trust_env"] is True


def test_tavily_client_uses_modern_proxy_kw_when_proxies_kw_is_unavailable(
    monkeypatch,
):
    created_clients = []

    class ProxyOnlyAsyncClient:
        def __init__(self, timeout=None, verify=True, trust_env=True, proxy=None):
            self.kwargs = {
                "timeout": timeout,
                "verify": verify,
                "trust_env": trust_env,
                "proxy": proxy,
            }
            created_clients.append(self)

        async def aclose(self):
            return None

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", ProxyOnlyAsyncClient)

    asyncio.run(
        _open_client(
            AsyncTavilyClient(
                api_key="k",
                proxies={"https://": "http://proxy.local:8080"},
            )
        )
    )

    assert created_clients[0].kwargs["proxy"] == "http://proxy.local:8080"
    assert "proxies" not in created_clients[0].kwargs


def test_tavily_client_uses_legacy_proxies_kw_when_supported(monkeypatch):
    created_clients = []

    class ProxiesAsyncClient:
        def __init__(
            self,
            timeout=None,
            verify=True,
            trust_env=True,
            proxies=None,
        ):
            self.kwargs = {
                "timeout": timeout,
                "verify": verify,
                "trust_env": trust_env,
                "proxies": proxies,
            }
            created_clients.append(self)

        async def aclose(self):
            return None

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", ProxiesAsyncClient)

    proxies = {"https://": "http://proxy.local:8080"}
    asyncio.run(_open_client(AsyncTavilyClient(api_key="k", proxies=proxies)))

    assert created_clients[0].kwargs["proxies"] == proxies


def test_tavily_client_uses_mounts_for_modern_multi_scheme_proxies(monkeypatch):
    created_clients = []
    created_transports = []

    class ModernAsyncClient:
        def __init__(
            self,
            timeout=None,
            verify=True,
            trust_env=True,
            proxy=None,
            mounts=None,
        ):
            self.kwargs = {
                "timeout": timeout,
                "verify": verify,
                "trust_env": trust_env,
                "proxy": proxy,
                "mounts": mounts,
            }
            created_clients.append(self)

        async def aclose(self):
            return None

    class FakeAsyncHTTPTransport:
        def __init__(self, proxy=None, verify=True, trust_env=True):
            self.kwargs = {
                "proxy": proxy,
                "verify": verify,
                "trust_env": trust_env,
            }
            created_transports.append(self)

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", ModernAsyncClient)
    monkeypatch.setattr(
        tavily_client.httpx,
        "AsyncHTTPTransport",
        FakeAsyncHTTPTransport,
    )

    asyncio.run(
        _open_client(
            AsyncTavilyClient(
                api_key="k",
                proxies={
                    "http://": "http://http-proxy.local:8080",
                    "https://": "http://https-proxy.local:8080",
                },
            )
        )
    )

    kwargs = created_clients[0].kwargs
    assert kwargs["proxy"] is None
    assert set(kwargs["mounts"]) == {"http://", "https://"}
    assert (
        kwargs["mounts"]["http://"].kwargs["proxy"]
        == "http://http-proxy.local:8080"
    )
    assert (
        kwargs["mounts"]["https://"].kwargs["proxy"]
        == "http://https-proxy.local:8080"
    )
    assert [t.kwargs["trust_env"] for t in created_transports] == [False, False]


def test_tavily_client_omits_proxy_kwargs_without_explicit_proxy(monkeypatch):
    created_clients = []

    def fake_async_client(**kwargs):
        client = FakeAsyncClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", fake_async_client)

    asyncio.run(_open_client(AsyncTavilyClient(api_key="k")))

    kwargs = created_clients[0].kwargs
    assert kwargs["trust_env"] is False
    assert "proxies" not in kwargs
    assert "proxy" not in kwargs


def test_tavily_client_does_not_swallow_unexpected_async_client_typeerror(
    monkeypatch,
):
    calls = []

    def broken_async_client(**kwargs):
        calls.append(kwargs)
        raise TypeError("internal construction bug")

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", broken_async_client)

    with pytest.raises(TypeError, match="internal construction bug"):
        asyncio.run(_open_client(AsyncTavilyClient(api_key="k")))

    assert len(calls) == 1
