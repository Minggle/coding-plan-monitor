"""火山引擎 Coding Plan：控制台 Cookie 接口（无官方开放 API）。

POST https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/GetCodingPlanUsage
Header: Cookie + x-csrf-token + x-web-id；Body: {"ProjectName": "default"}
QuotaUsage[].Level: session(5h) / weekly / monthly；Percent 可能 0-1 或 0-100；
ResetTimestamp 秒/毫秒混用；周期切换时可能同时出现新旧两条记录。
"""

from __future__ import annotations

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
)

API_URL = "https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/GetCodingPlanUsage"
REFERER = "https://console.volcengine.com/ark/region:cn-beijing/subscription/coding-plan?projectName=default"

_LEVEL_MAP = {
    "session": WindowType.FIVE_HOUR,
    "5h": WindowType.FIVE_HOUR,
    "hour": WindowType.FIVE_HOUR,
    "weekly": WindowType.SEVEN_DAY,
    "week": WindowType.SEVEN_DAY,
    "monthly": WindowType.MONTHLY,
    "month": WindowType.MONTHLY,
}


def _match_window_type(level: str) -> WindowType | None:
    s = (level or "").lower()
    for key, wt in _LEVEL_MAP.items():
        if key in s:
            return wt
    return None


class VolcanoProvider(Provider):
    name = "volcano"
    last_raw: dict | None = None

    def fetch(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        if not account.cookie:
            raise ProviderError(ErrorKind.AUTH, "未配置控制台 Cookie，请在设置中粘贴 curl 命令")
        headers = {
            "Content-Type": "application/json",
            "Cookie": account.cookie,
            "Referer": REFERER,
        }
        if account.csrf_token:
            headers["x-csrf-token"] = account.csrf_token
        if account.web_id:
            headers["x-web-id"] = account.web_id
        body = {"ProjectName": account.project_name or "default"}

        data = get_json(client, "POST", API_URL, headers=headers, json=body)
        self.last_raw = data

        meta = data.get("ResponseMetadata") or {}
        if meta.get("Error"):
            err = meta["Error"]
            msg = err.get("Message") or str(err)
            code = str(err.get("Code") or "")
            kind = ErrorKind.AUTH if "auth" in code.lower() or "expire" in msg.lower() else ErrorKind.HTTP
            raise ProviderError(kind, f"火山接口返回错误：{msg}")

        quota = (data.get("Result") or {}).get("QuotaUsage") or []
        candidates: dict[WindowType, list[tuple[float | None, UsageWindow]]] = {}
        unmatched: list[tuple[float | None, UsageWindow]] = []
        for item in quota:
            level = str(item.get("Level") or "")
            reset = parse_time_to_epoch(item.get("ResetTimestamp"))
            w = UsageWindow(
                window_type=WindowType.FIVE_HOUR,
                percent=normalize_percent(item.get("Percent")),
                reset_at=reset,
            )
            wt = _match_window_type(level)
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
        if not windows:
            raise ProviderError(ErrorKind.PARSE, "响应中未找到 QuotaUsage 数据")
        return self.snapshot(account, windows)
