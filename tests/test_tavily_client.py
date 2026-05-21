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
