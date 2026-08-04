import json
import os

import httpx
import pytest

from app.core.config import Account
from app.core.models import ErrorKind, WindowType
from app.providers.base import ProviderError
from app.providers.kimi import API_URL, KimiProvider

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "kimi_usages.json")


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_kimi_parse():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == API_URL
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json=load_fixture())

    acc = Account(provider="kimi", name="主力", key="sk-test")
    snap = KimiProvider().fetch(acc, make_client(handler))

    assert snap.provider == "kimi"
    assert snap.account_name == "主力"

    w5 = snap.window(WindowType.FIVE_HOUR)
    assert w5 is not None
    assert w5.used == 32 and w5.limit == 100
    assert w5.percent == pytest.approx(32.0)
    assert w5.reset_at is not None

    w7 = snap.window(WindowType.SEVEN_DAY)
    assert w7 is not None
    assert w7.percent == pytest.approx(12.3456, abs=1e-3)

    # Kimi 无月度窗口
    assert snap.window(WindowType.MONTHLY) is None


def test_kimi_weekly_fallback_from_top_usage():
    data = load_fixture()
    data["limits"] = [l for l in data["limits"] if "DAY" not in l["window"]["timeUnit"]]

    def handler(request):
        return httpx.Response(200, json=data)

    acc = Account(provider="kimi", key="sk-test")
    snap = KimiProvider().fetch(acc, make_client(handler))
    w7 = snap.window(WindowType.SEVEN_DAY)
    assert w7 is not None
    assert w7.used == 32


def test_kimi_real_response_enum_timeunit():
    """真实抓包：timeUnit 为 TIME_UNIT_MINUTE，detail 可能缺 used（只有 remaining）。"""
    data = {
        "usage": {"limit": "100", "remaining": "100", "resetTime": "2026-08-04T08:14:11.715300Z"},
        "limits": [{
            "window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
            "detail": {"limit": "100", "remaining": "100", "resetTime": "2026-07-29T13:14:11.715300Z"},
        }],
    }

    def handler(request):
        return httpx.Response(200, json=data)

    acc = Account(provider="kimi", key="sk-test")
    snap = KimiProvider().fetch(acc, make_client(handler))
    w5 = snap.window(WindowType.FIVE_HOUR)
    assert w5 is not None
    assert w5.percent == pytest.approx(0.0)  # used = 100 - 100
    assert w5.reset_at is not None
    w7 = snap.window(WindowType.SEVEN_DAY)
    assert w7 is not None  # 顶层 usage 兜底
    assert w7.percent == pytest.approx(0.0)


def test_kimi_auth_error():
    def handler(request):
        return httpx.Response(401, json={"error": "invalid key"})

    acc = Account(provider="kimi", key="bad")
    with pytest.raises(ProviderError) as ei:
        KimiProvider().fetch(acc, make_client(handler))
    assert ei.value.kind == ErrorKind.AUTH


def test_kimi_missing_key():
    acc = Account(provider="kimi", key="")
    with pytest.raises(ProviderError) as ei:
        KimiProvider().fetch(acc, make_client(lambda r: httpx.Response(200)))
    assert ei.value.kind == ErrorKind.AUTH


def test_kimi_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    acc = Account(provider="kimi", key="sk-test")
    with pytest.raises(ProviderError) as ei:
        KimiProvider().fetch(acc, make_client(handler))
    assert ei.value.kind == ErrorKind.NETWORK


def test_kimi_window_variants_hour_unit():
    """真实 API 可能返回 5 HOUR 而非 300 MINUTE。"""
    data = {"limits": [
        {"window": {"duration": 5, "timeUnit": "HOUR"},
         "detail": {"limit": "100", "used": "40", "resetTime": "2026-07-29T18:30:00Z"}},
        {"window": {"duration": 1, "timeUnit": "WEEK"},
         "detail": {"limit": "1000", "used": "200"}},
    ]}

    def handler(request):
        return httpx.Response(200, json=data)

    acc = Account(provider="kimi", key="sk-test")
    snap = KimiProvider().fetch(acc, make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(40.0)
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(20.0)


def test_kimi_duration_as_string():
    data = {"limits": [
        {"window": {"duration": "300", "timeUnit": "minute"},
         "detail": {"limit": "100", "used": "10"}},
    ]}

    def handler(request):
        return httpx.Response(200, json=data)

    acc = Account(provider="kimi", key="sk-test")
    snap = KimiProvider().fetch(acc, make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(10.0)
