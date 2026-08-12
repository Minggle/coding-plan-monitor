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
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"id": "probe", "choices": []})
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
# ---------- 月度配额探测（usages 接口不暴露月度池，靠推理 403 判定） ----------

QUOTA_403 = {
    "error": {
        "message": "You've reached your usage limit for this billing cycle. "
                   "Your quota will be refreshed in the next cycle.",
        "type": "access_terminated_error",
    }
}


def _route(handler_usages, chat_response):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return chat_response
        return handler_usages(request)
    return handler


def test_kimi_monthly_exhausted_probe():
    """5h/周窗口未满 + 推理 403 billing cycle → 月度窗口 100%。"""
    handler = _route(lambda r: httpx.Response(200, json=load_fixture()),
                     httpx.Response(403, json=QUOTA_403))
    acc = Account(provider="kimi", key="sk-test")
    snap = KimiProvider().fetch(acc, make_client(handler))
    m = snap.window(WindowType.MONTHLY)
    assert m is not None
    assert m.percent == 100.0
    assert m.reset_at is None


def test_kimi_monthly_healthy_probe_no_window():
    """探测请求成功（200）→ 月度未耗尽，不出现月度窗口。"""
    handler = _route(lambda r: httpx.Response(200, json=load_fixture()),
                     httpx.Response(200, json={"id": "ok", "choices": []}))
    acc = Account(provider="kimi", key="sk-test")
    snap = KimiProvider().fetch(acc, make_client(handler))
    assert snap.window(WindowType.MONTHLY) is None


def test_kimi_probe_skipped_when_window_near_full():
    """5h/周窗口 >=95% 时锁定可由窗口解释，不消耗探测请求。"""
    data = load_fixture()
    for item in data["limits"]:
        item["detail"]["used"] = "96"
        item["detail"]["remaining"] = "4"
    data["usage"]["used"] = "96"
    data["usage"]["remaining"] = "4"
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=data)

    acc = Account(provider="kimi", key="sk-test")
    KimiProvider().fetch(acc, make_client(handler))
    assert not any(p.endswith("/chat/completions") for p in paths)


def test_kimi_probe_throttled():
    """同一账号 6 小时内只探测一次；耗尽结论在后续查询中沿用。"""
    chat_calls = []

    def handler(request):
        if request.url.path.endswith("/chat/completions"):
            chat_calls.append(1)
            return httpx.Response(403, json=QUOTA_403)
        return httpx.Response(200, json=load_fixture())

    acc = Account(provider="kimi", key="sk-test")
    for _ in range(3):
        snap = KimiProvider().fetch(acc, make_client(handler))
        assert snap.window(WindowType.MONTHLY).percent == 100.0
    assert len(chat_calls) == 1
