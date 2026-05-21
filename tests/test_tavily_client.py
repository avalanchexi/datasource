import asyncio

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


def test_tavily_client_disables_trust_env_by_default(monkeypatch):
    created_clients = []

    def fake_async_client(**kwargs):
        client = FakeAsyncClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", fake_async_client)

    async def run_client():
        async with AsyncTavilyClient(api_key="k"):
            pass

    asyncio.run(run_client())

    assert created_clients[0].kwargs["trust_env"] is False


def test_tavily_client_allows_explicit_trust_env(monkeypatch):
    created_clients = []

    def fake_async_client(**kwargs):
        client = FakeAsyncClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(tavily_client.httpx, "Timeout", FakeTimeout)
    monkeypatch.setattr(tavily_client.httpx, "AsyncClient", fake_async_client)

    async def run_client():
        async with AsyncTavilyClient(api_key="k", trust_env=True):
            pass

    asyncio.run(run_client())

    assert created_clients[0].kwargs["trust_env"] is True
