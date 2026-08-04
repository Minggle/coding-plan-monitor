import json
import os

import httpx
import pytest

from app.core.config import Account, CustomSpec
from app.core.models import WindowType
from app.providers.custom import CustomProvider

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "custom_usage.json")


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def make_account():
    return Account(
        provider="custom",
        name="自定义",
        key="my-key",
        custom=CustomSpec(
            url="https://example.com/usage",
            headers={"Authorization": "Bearer {KEY}"},
            paths={"5h": "data.five_hour", "7d": "data.week", "monthly": "data.month"},
        ),
    )


def test_custom_parse():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer my-key"
        return httpx.Response(200, json=data)

    snap = CustomProvider().fetch(make_account(), make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(33.3)
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(55.0)
    wm = snap.window(WindowType.MONTHLY)
    assert wm.percent == pytest.approx(10.5)
    assert wm.used == 105 and wm.limit == 1000


def test_custom_missing_path_skipped():
    def handler(request):
        return httpx.Response(200, json={"data": {"week": 42}})

    acc = make_account()
    acc.custom.paths = {"7d": "data.week", "5h": "data.nonexist"}
    snap = CustomProvider().fetch(acc, make_client(handler))
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(42.0)
    assert snap.window(WindowType.FIVE_HOUR) is None
