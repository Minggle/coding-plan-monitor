import json
import os

import httpx
import pytest

from app.core.config import Account
from app.core.models import WindowType
from app.providers.glm import GlmProvider

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "glm_quota_limit.json")


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def test_glm_parse_bigmodel():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "open.bigmodel.cn"
        # GLM 是裸 key，不带 Bearer
        assert request.headers["Authorization"] == "glm-key-1"
        return httpx.Response(200, json=data)

    acc = Account(provider="glm", name="GLM", key="glm-key-1", site="open.bigmodel.cn")
    snap = GlmProvider().fetch(acc, make_client(handler))

    w5 = snap.window(WindowType.FIVE_HOUR)
    assert w5.percent == pytest.approx(40.5)
    assert w5.reset_at == pytest.approx(1753800000000 / 1000)

    w7 = snap.window(WindowType.SEVEN_DAY)
    assert w7.percent == pytest.approx(12.0)

    wm = snap.window(WindowType.MONTHLY)
    assert wm.percent == pytest.approx(12.3)
    assert wm.used == 123 and wm.limit == 1000


def test_glm_site_zai():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.z.ai"
        return httpx.Response(200, json={"level": "pro", "limits": [
            {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 1, "nextResetTime": 1753800000000}
        ]})

    acc = Account(provider="glm", key="k", site="api.z.ai")
    snap = GlmProvider().fetch(acc, make_client(handler))
    w5 = snap.window(WindowType.FIVE_HOUR)
    # GLM 的 percentage 恒为 0-100，1 表示 1%（不能被放大为 100%）
    assert w5.percent == pytest.approx(1.0)


def test_glm_low_usage_percentage_not_inflated():
    """回归：5 小时用量很低时（percentage=1 表示 1%）不能被放大成 100%。"""
    def handler(request):
        return httpx.Response(200, json={
            "code": 200, "msg": "ok", "success": True,
            "data": {"level": "lite", "limits": [
                {"type": "CREDIT_LIMIT", "unit": 3, "number": 5,
                 "usage": 2000, "currentValue": 17, "remaining": 1982,
                 "percentage": 1, "nextResetTime": 1785821557675},
                {"type": "CREDIT_LIMIT", "unit": 6, "number": 1,
                 "usage": 10000, "currentValue": 3646, "remaining": 6353,
                 "percentage": 36, "nextResetTime": 1786062508998},
            ]},
        })

    acc = Account(provider="glm", key="k")
    snap = GlmProvider().fetch(acc, make_client(handler))
    w5 = snap.window(WindowType.FIVE_HOUR)
    assert w5 is not None
    # 精确值 17/2000 = 0.85%，绝不是 100%
    assert w5.percent == pytest.approx(0.85)
    assert w5.used == 17 and w5.limit == 2000
    w7 = snap.window(WindowType.SEVEN_DAY)
    assert w7.percent == pytest.approx(36.46)


def test_glm_unit_number_as_strings():
    """unit/number 可能是字符串数字。"""
    def handler(request):
        return httpx.Response(200, json={"level": "pro", "limits": [
            {"type": "TOKENS_LIMIT", "unit": "3", "number": "5", "percentage": 40.5, "nextResetTime": 1753800000000},
            {"type": "TOKENS_LIMIT", "unit": "6", "number": "1", "percentage": 12.0},
        ]})

    acc = Account(provider="glm", key="k")
    snap = GlmProvider().fetch(acc, make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(40.5)
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(12.0)


def test_glm_unknown_token_limits_positional_fallback():
    """未知的 (unit, number) 组合按出现顺序兜底为 5h/7d。"""
    def handler(request):
        return httpx.Response(200, json={"level": "pro", "limits": [
            {"type": "TOKENS_LIMIT", "unit": 9, "number": 9, "percentage": 33.0},
            {"type": "TOKENS_LIMIT", "unit": 8, "number": 8, "percentage": 11.0},
        ]})

    acc = Account(provider="glm", key="k")
    snap = GlmProvider().fetch(acc, make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(33.0)
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(11.0)


def test_glm_real_wrapped_response():
    """真实抓包：响应外层包 {code, msg, data, success}，lite 档 type 为 CREDIT_LIMIT。"""
    import json
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "glm_quota_limit_wrapped.json"), encoding="utf-8") as f:
        data = json.load(f)

    def handler(request):
        return httpx.Response(200, json=data)

    acc = Account(provider="glm", key="k")
    snap = GlmProvider().fetch(acc, make_client(handler))
    w5 = snap.window(WindowType.FIVE_HOUR)
    assert w5 is not None
    # 优先用 currentValue/usage 精确计算：1737/2000 = 86.85%
    assert w5.percent == pytest.approx(86.85)
    assert w5.used == 1737 and w5.limit == 2000
    assert w5.reset_at == pytest.approx(1785476791399 / 1000)
    w7 = snap.window(WindowType.SEVEN_DAY)
    assert w7 is not None
    assert w7.percent == pytest.approx(17.37)
    assert w7.limit == 10000
