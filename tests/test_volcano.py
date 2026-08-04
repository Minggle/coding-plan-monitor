import json
import os
import time

import httpx
import pytest

from app.core.config import Account
from app.core.models import ErrorKind, WindowType
from app.providers.base import ProviderError
from app.providers.volcano import VolcanoProvider

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "volcano_usage.json")


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def make_account():
    return Account(
        provider="volcano",
        name="火山",
        cookie="sessionid=abc; csrfToken=tok123",
        csrf_token="tok123",
        web_id="wid-1",
    )


def test_volcano_parse():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["Cookie"].startswith("sessionid=abc")
        assert request.headers["x-csrf-token"] == "tok123"
        assert request.headers["x-web-id"] == "wid-1"
        assert json.loads(request.content) == {"ProjectName": "default"}
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_account(), make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(45.0)
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(20.0)
    assert snap.window(WindowType.MONTHLY).percent == pytest.approx(8.0)
    # ResetTimestamp 秒级，不应被再除 1000
    assert snap.window(WindowType.SEVEN_DAY).reset_at == pytest.approx(1754200000)


def test_volcano_percent_fraction_normalized():
    data = {"Result": {"QuotaUsage": [{"Level": "weekly", "Percent": 0.2, "ResetTimestamp": 1754200000}]},
            "ResponseMetadata": {"Error": None}}

    def handler(request):
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_account(), make_client(handler))
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(20.0)


def test_volcano_prefers_future_reset_on_overlap():
    now = time.time()
    data = {"Result": {"QuotaUsage": [
        {"Level": "weekly", "Percent": 99, "ResetTimestamp": now - 3600},       # 旧周期（已过期）
        {"Level": "weekly", "Percent": 5, "ResetTimestamp": now + 86400},       # 新周期
    ]}, "ResponseMetadata": {"Error": None}}

    def handler(request):
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_account(), make_client(handler))
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(5.0)


def test_volcano_expired_cookie():
    def handler(request):
        return httpx.Response(401, text="Unauthorized")

    with pytest.raises(ProviderError) as ei:
        VolcanoProvider().fetch(make_account(), make_client(handler))
    assert ei.value.kind == ErrorKind.AUTH


def test_volcano_no_cookie():
    acc = Account(provider="volcano", cookie="")
    with pytest.raises(ProviderError) as ei:
        VolcanoProvider().fetch(acc, make_client(lambda r: httpx.Response(200)))
    assert ei.value.kind == ErrorKind.AUTH
