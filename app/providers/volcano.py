"""火山引擎：Coding Plan 与 Agent Plan 两种套餐，检查方式不同。

官方 OpenAPI（https://open.volcengineapi.com，AK/SK + V4 签名）：
- Coding Plan：GetCodingPlanUsage → Result.QuotaUsage[{Level, Percent, ResetTimestamp}]
  Level 取值 session(5h)/weekly/monthly；Percent 可能 0-1 或 0-100；ResetTimestamp 秒/毫秒，-1 表示无重置
- Agent Plan：GetAFPUsage → Result.AFPFiveHour/AFPWeekly/AFPMonthly[{Quota, Used, ResetTime}]
  绝对额度需换算百分比；Quota<=0 视为未订阅该窗口
plan_type=auto 时先试 Agent 接口（无有效窗口视为未订阅），再回退 Coding 接口。

控制台 Cookie 路径（粘贴 curl，Coding / Agent 均可，自动检测逻辑同上）：
POST console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/<Action>，
Coding 用 GetCodingPlanUsage（Body {"ProjectName": ...}），
Agent 用 GetAgentPlanAFPUsage（空 body，与控制台前端一致），
Header 带 Cookie + x-csrf-token + x-web-id。
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.core.config import Account
from app.core.models import ErrorKind, UsageSnapshot, UsageWindow, WindowType
from app.providers.base import (
    Provider,
    ProviderError,
    get_json,
    normalize_percent,
    parse_time_to_epoch,
    pick_reset_future,
    to_float,
)
from app.providers.volcano_sign import build_canonical_query, signed_headers_v4

OPENAPI_HOST = "open.volcengineapi.com"
REGION = "cn-beijing"
SERVICE = "ark"
VERSION = "2024-01-01"

CONSOLE_API_BASE = "https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01"
CONSOLE_REFERER = {
    "coding": "https://console.volcengine.com/ark/region:cn-beijing/subscription/coding-plan?projectName=default",
    "agent": "https://console.volcengine.com/ark/region:cn-beijing/subscription/agent-plan",
}

ACTION_CODING = "GetCodingPlanUsage"
ACTION_AGENT = "GetAFPUsage"
# 控制台前端对 Agent Plan 用另一个 Action 名（响应结构与 GetAFPUsage 一致）
CONSOLE_ACTION_AGENT = "GetAgentPlanAFPUsage"

_LEVEL_MAP = {
    "session": WindowType.FIVE_HOUR,
    "5h": WindowType.FIVE_HOUR,
    "hour": WindowType.FIVE_HOUR,
    "weekly": WindowType.SEVEN_DAY,
    "week": WindowType.SEVEN_DAY,
    "monthly": WindowType.MONTHLY,
    "month": WindowType.MONTHLY,
}

# Agent Plan 响应字段 → 窗口
_AFP_FIELDS = [
    ("AFPFiveHour", WindowType.FIVE_HOUR),
    ("AFPWeekly", WindowType.SEVEN_DAY),
    ("AFPMonthly", WindowType.MONTHLY),
]

_AUTH_CODE_HINTS = ("auth", "accesskey", "signature", "token", "expire")


def _match_window_type(level: str) -> WindowType | None:
    s = (level or "").lower()
    for key, wt in _LEVEL_MAP.items():
        if key in s:
            return wt
    return None


def _reset_or_none(value) -> float | None:
    """ResetTimestamp/ResetTime：秒或毫秒或 ISO 字符串；<=0（如 -1）表示无重置。"""
    reset = parse_time_to_epoch(value)
    if reset is not None and reset <= 0:
        return None
    return reset


def _parse_coding_windows(data: dict) -> list[UsageWindow]:
    """GetCodingPlanUsage 响应 → 窗口列表；周期切换瞬间的新旧记录取未来最近的一条。"""
    quota = (data.get("Result") or {}).get("QuotaUsage") or []
    candidates: dict[WindowType, list[tuple[float | None, UsageWindow]]] = {}
    unmatched: list[tuple[float | None, UsageWindow]] = []
    for item in quota:
        reset = _reset_or_none(item.get("ResetTimestamp"))
        w = UsageWindow(
            window_type=WindowType.FIVE_HOUR,
            percent=normalize_percent(item.get("Percent")),
            reset_at=reset,
        )
        wt = _match_window_type(str(item.get("Level") or ""))
        if wt is None:
            unmatched.append((reset, w))
        else:
            w.window_type = wt
            candidates.setdefault(wt, []).append((reset, w))

    # 未识别 Level 按顺序兜底：5h → 7d → monthly
    for reset, w in unmatched:
        for wt in (WindowType.FIVE_HOUR, WindowType.SEVEN_DAY, WindowType.MONTHLY):
            if wt not in candidates:
                w.window_type = wt
                candidates[wt] = [(reset, w)]
                break

    windows = []
    for wt in (WindowType.FIVE_HOUR, WindowType.SEVEN_DAY, WindowType.MONTHLY):
        if wt in candidates:
            picked = pick_reset_future(candidates[wt])
            if picked:
                windows.append(picked)
    return windows


def _parse_afp_windows(data: dict) -> list[UsageWindow]:
    """GetAFPUsage 响应 → 窗口列表；Quota<=0 的窗口视为未订阅，跳过。"""
    result = data.get("Result") or {}
    windows = []
    for field, wt in _AFP_FIELDS:
        w = result.get(field)
        if not isinstance(w, dict):
            continue
        quota = to_float(w.get("Quota"))
        if not quota or quota <= 0:
            continue
        used = to_float(w.get("Used")) or 0.0
        windows.append(UsageWindow(
            window_type=wt,
            percent=max(0.0, min(100.0, used / quota * 100)),
            used=used,
            limit=quota,
            reset_at=_reset_or_none(w.get("ResetTime")),
        ))
    return windows


class VolcanoProvider(Provider):
    name = "volcano"
    last_raw: dict | None = None

    def fetch(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        if account.access_key_id and account.secret_access_key:
            return self._fetch_openapi(account, client)
        if account.cookie:
            return self._fetch_console(account, client)
        raise ProviderError(
            ErrorKind.AUTH,
            "未配置火山凭证：请在设置中填写 AccessKey，或粘贴控制台 curl 命令",
        )

    # ---- 官方 OpenAPI（Coding / Agent 双套餐） ----

    def _fetch_openapi(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        plan = (account.plan_type or "auto").lower()
        windows: list[UsageWindow] | None = None
        if plan in ("auto", "agent"):
            try:
                windows = _parse_afp_windows(self._call_openapi(client, ACTION_AGENT, account))
            except ProviderError:
                if plan == "agent":
                    raise
                # auto 模式下 Agent 接口失败继续尝试 Coding 接口
            if not windows:
                if plan == "agent":
                    raise ProviderError(ErrorKind.PARSE, "GetAFPUsage 未返回有效窗口（可能未订阅 Agent Plan）")
                windows = None
        if windows is None:
            windows = _parse_coding_windows(self._call_openapi(client, ACTION_CODING, account))
        if not windows:
            raise ProviderError(ErrorKind.PARSE, "响应中未找到用量窗口数据")
        return self.snapshot(account, windows)

    def _call_openapi(self, client: httpx.Client, action: str, account: Account) -> dict:
        query = build_canonical_query(action, REGION, VERSION)
        body = ""
        headers = signed_headers_v4(
            ak=account.access_key_id,
            sk=account.secret_access_key,
            region=REGION,
            service=SERVICE,
            host=OPENAPI_HOST,
            query=query,
            body=body,
            now=datetime.now(timezone.utc),
        )
        url = f"https://{OPENAPI_HOST}/?{query}"
        data = get_json(client, "POST", url, headers=headers, content=body)
        self.last_raw = data
        meta = data.get("ResponseMetadata") or {}
        err = meta.get("Error")
        if err:
            code = str(err.get("Code") or "")
            msg = err.get("Message") or str(err)
            kind = (ErrorKind.AUTH if any(h in code.lower() or h in msg.lower() for h in _AUTH_CODE_HINTS)
                    else ErrorKind.HTTP)
            raise ProviderError(kind, f"火山接口返回错误：{code}: {msg}")
        return data

    # ---- 控制台 Cookie 路径（Coding / Agent 均可） ----

    def _fetch_console(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        plan = (account.plan_type or "auto").lower()
        windows: list[UsageWindow] | None = None
        if plan in ("auto", "agent"):
            try:
                windows = _parse_afp_windows(self._call_console(client, account, CONSOLE_ACTION_AGENT, "agent", {}))
            except ProviderError:
                if plan == "agent":
                    raise
            if not windows:
                if plan == "agent":
                    raise ProviderError(ErrorKind.PARSE, "GetAgentPlanAFPUsage 未返回有效窗口（可能未订阅 Agent Plan）")
                windows = None
        if windows is None:
            body = {"ProjectName": account.project_name or "default"}
            windows = _parse_coding_windows(self._call_console(client, account, ACTION_CODING, "coding", body))
        if not windows:
            raise ProviderError(ErrorKind.PARSE, "响应中未找到用量窗口数据")
        return self.snapshot(account, windows)

    def _call_console(self, client: httpx.Client, account: Account, action: str,
                      plan: str, body: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Cookie": account.cookie,
            "Referer": CONSOLE_REFERER[plan],
        }
        if account.csrf_token:
            headers["x-csrf-token"] = account.csrf_token
        if account.web_id:
            headers["x-web-id"] = account.web_id

        data = get_json(client, "POST", f"{CONSOLE_API_BASE}/{action}", headers=headers, json=body)
        self.last_raw = data

        meta = data.get("ResponseMetadata") or {}
        if meta.get("Error"):
            err = meta["Error"]
            msg = err.get("Message") or str(err)
            code = str(err.get("Code") or "")
            kind = (ErrorKind.AUTH if any(h in code.lower() or h in msg.lower() for h in _AUTH_CODE_HINTS)
                    else ErrorKind.HTTP)
            raise ProviderError(kind, f"火山接口返回错误：{msg}")
        return data
