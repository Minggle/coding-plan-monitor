"""火山引擎 provider 测试：Cookie 控制台路径（仅 Coding Plan）+ AK/SK 官方 OpenAPI 路径（Coding/Agent 双套餐）。"""

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
AFP_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "volcano_afp_usage.json")


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def make_account():
    # 锁定 Coding 控制台路径，避免 auto 先试 Agent 接口
    return Account(
        provider="volcano",
        name="火山",
        cookie="sessionid=abc; csrfToken=tok123",
        csrf_token="tok123",
        web_id="wid-1",
        plan_type="coding",
    )


def make_ak_account(plan_type="auto"):
    return Account(
        provider="volcano",
        name="火山AK",
        access_key_id="AKTESTEXAMPLE",
        secret_access_key="SKTESTEXAMPLE",
        plan_type=plan_type,
    )


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def action_of(request: httpx.Request) -> str:
    return request.url.params.get("Action", "")


# ---------- 旧路径：控制台 Cookie（仅 Coding Plan） ----------

def test_volcano_parse():
    data = load(FIXTURE)

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


def test_volcano_reset_minus_one_means_unknown():
    data = {"Result": {"QuotaUsage": [{"Level": "monthly", "Percent": 80, "ResetTimestamp": -1}]},
            "ResponseMetadata": {"Error": None}}

    def handler(request):
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_account(), make_client(handler))
    assert snap.window(WindowType.MONTHLY).reset_at is None


def test_volcano_expired_cookie():
    def handler(request):
        return httpx.Response(401, text="Unauthorized")

    with pytest.raises(ProviderError) as ei:
        VolcanoProvider().fetch(make_account(), make_client(handler))
    assert ei.value.kind == ErrorKind.AUTH


def test_volcano_no_credentials():
    acc = Account(provider="volcano")
    with pytest.raises(ProviderError) as ei:
        VolcanoProvider().fetch(acc, make_client(lambda r: httpx.Response(200)))
    assert ei.value.kind == ErrorKind.AUTH


# ---------- 新路径：AK/SK 官方 OpenAPI ----------

def test_openapi_coding_plan():
    data = load(FIXTURE)

    def handler(request: httpx.Request) -> httpx.Response:
        assert action_of(request) == "GetCodingPlanUsage"
        assert request.url.host == "open.volcengineapi.com"
        auth = request.headers["Authorization"]
        assert auth.startswith("HMAC-SHA256 Credential=AKTESTEXAMPLE/")
        assert "/cn-beijing/ark/request" in auth
        assert request.headers["X-Content-Sha256"]
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_ak_account("coding"), make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(45.0)
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(20.0)


def test_openapi_agent_plan():
    data = load(AFP_FIXTURE)

    def handler(request: httpx.Request) -> httpx.Response:
        assert action_of(request) == "GetAFPUsage"
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_ak_account("agent"), make_client(handler))
    five = snap.window(WindowType.FIVE_HOUR)
    seven = snap.window(WindowType.SEVEN_DAY)
    assert five.percent == pytest.approx(30.0)
    assert five.used == pytest.approx(30.0) and five.limit == pytest.approx(100.0)
    assert seven.percent == pytest.approx(50.0)
    assert seven.reset_at == pytest.approx(1754200000)
    # AFPMonthly Quota=0 → 未订阅该窗口，不展示
    assert snap.window(WindowType.MONTHLY) is None


def test_openapi_agent_percent_clamped():
    data = {"Result": {"PlanType": "AFP",
                       "AFPFiveHour": {"Quota": "100", "Used": "150", "ResetTime": 1753800000}},
            "ResponseMetadata": {"Error": None}}

    def handler(request):
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_ak_account("agent"), make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(100.0)


def test_auto_detect_prefers_agent_plan():
    """auto：GetAFPUsage 有有效窗口（Quota>0）时直接采用，不再请求 Coding 接口。"""
    afp = load(AFP_FIXTURE)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(action_of(request))
        return httpx.Response(200, json=afp)

    snap = VolcanoProvider().fetch(make_ak_account("auto"), make_client(handler))
    assert calls == ["GetAFPUsage"]
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(50.0)


def test_auto_detect_falls_back_to_coding():
    """auto：GetAFPUsage 无有效窗口（未订阅 Agent Plan）→ 回退 GetCodingPlanUsage。"""
    empty_afp = {"Result": {"PlanType": "CodingPlan"}, "ResponseMetadata": {"Error": None}}
    coding = load(FIXTURE)

    def handler(request: httpx.Request) -> httpx.Response:
        if action_of(request) == "GetAFPUsage":
            return httpx.Response(200, json=empty_afp)
        return httpx.Response(200, json=coding)

    snap = VolcanoProvider().fetch(make_ak_account("auto"), make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(45.0)


def test_agent_plan_not_subscribed_raises_parse():
    empty_afp = {"Result": {}, "ResponseMetadata": {"Error": None}}

    def handler(request):
        return httpx.Response(200, json=empty_afp)

    with pytest.raises(ProviderError) as ei:
        VolcanoProvider().fetch(make_ak_account("agent"), make_client(handler))
    assert ei.value.kind == ErrorKind.PARSE


def test_openapi_invalid_ak_is_auth_error():
    err = {"ResponseMetadata": {"Error": {"Code": "InvalidAccessKeyId", "Message": "invalid ak"}}}

    def handler(request):
        return httpx.Response(200, json=err)

    with pytest.raises(ProviderError) as ei:
        VolcanoProvider().fetch(make_ak_account("coding"), make_client(handler))
    assert ei.value.kind == ErrorKind.AUTH

# ---------- 控制台 Cookie 路径：Agent Plan ----------

def make_cookie_agent_account(plan_type="agent"):
    return Account(
        provider="volcano",
        name="火山Agent",
        cookie="sessionid=abc; csrfToken=tok123",
        csrf_token="tok123",
        web_id="wid-1",
        plan_type=plan_type,
    )


def test_console_agent_plan():
    """Cookie 路径 + agent 套餐：调 GetAgentPlanAFPUsage，空 body，Referer 为 agent-plan 页。"""
    data = load(AFP_FIXTURE)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/GetAgentPlanAFPUsage")
        assert json.loads(request.content) == {}
        assert "agent-plan" in request.headers["Referer"]
        return httpx.Response(200, json=data)

    snap = VolcanoProvider().fetch(make_cookie_agent_account("agent"), make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(30.0)
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(50.0)
    assert snap.window(WindowType.MONTHLY) is None


def test_console_auto_detect_prefers_agent():
    """Cookie 路径 + auto：Agent 有有效窗口时不请求 Coding 接口。"""
    afp = load(AFP_FIXTURE)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(200, json=afp)

    snap = VolcanoProvider().fetch(make_cookie_agent_account("auto"), make_client(handler))
    assert calls == ["GetAgentPlanAFPUsage"]
    assert snap.window(WindowType.SEVEN_DAY).percent == pytest.approx(50.0)


def test_console_auto_falls_back_to_coding():
    """Cookie 路径 + auto：Agent 无有效窗口 → 回退 GetCodingPlanUsage。"""
    empty_afp = {"Result": {"PlanType": "CodingPlan"}, "ResponseMetadata": {"Error": None}}
    coding = load(FIXTURE)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/GetAgentPlanAFPUsage"):
            return httpx.Response(200, json=empty_afp)
        return httpx.Response(200, json=coding)

    snap = VolcanoProvider().fetch(make_cookie_agent_account("auto"), make_client(handler))
    assert snap.window(WindowType.FIVE_HOUR).percent == pytest.approx(45.0)
    assert snap.window(WindowType.MONTHLY).percent == pytest.approx(8.0)


def test_console_agent_not_subscribed_raises_parse():
    empty_afp = {"Result": {}, "ResponseMetadata": {"Error": None}}

    def handler(request):
        return httpx.Response(200, json=empty_afp)

    with pytest.raises(ProviderError) as ei:
        VolcanoProvider().fetch(make_cookie_agent_account("agent"), make_client(handler))
    assert ei.value.kind == ErrorKind.PARSE
