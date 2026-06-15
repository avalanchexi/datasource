from datasource.engines.stage2 import cli as stage2_cli
from scripts import stage2_unified_enhancer as stage2


def test_validate_proxies_uses_https_proxy_for_tavily_https_probe(monkeypatch):
    calls = []

    class Response:
        status_code = 200

    class FakeHttpx:
        @staticmethod
        def get(url, timeout=None, proxy=None):
            calls.append({"url": url, "timeout": timeout, "proxy": proxy})
            if proxy != "http://https-proxy.local:8080":
                raise AssertionError("wrong proxy used for HTTPS probe")
            return Response()

    proxies = {
        "http://": "http://http-proxy.local:8080",
        "https://": "http://https-proxy.local:8080",
    }

    monkeypatch.setattr(stage2_cli, "httpx", FakeHttpx)

    assert stage2._validate_proxies(proxies) == proxies
    assert calls == [
        {
            "url": "https://api.tavily.com",
            "timeout": 3,
            "proxy": "http://https-proxy.local:8080",
        }
    ]
