"""Kimi Coding Plan：GET https://api.kimi.com/coding/v1/usages，Bearer key。

limits[] 中 window=300MINUTE 为 5 小时窗口，7DAY 为每周窗口；顶层 usage 为周汇总。
字段值是字符串数字。
"""

from __future__ import annotations

import time

import httpx

from app.core.config import Account
from app.core.models import ErrorKind, UsageSnapshot, UsageWindow, WindowType
from app.providers.base import (
    Provider,
    ProviderError,
    get_json,
    parse_time_to_epoch,
    pct,
    to_float,
)

API_URL = "https://api.kimi.com/coding/v1/usages"
FALLBACK_URL = "https://api.kimi.com/coding/v1/usage"
CHAT_URL = "https://api.kimi.com/coding/v1/chat/completions"

# 月度探测：每账号每 6 小时最多一次（探测会真实消耗 1 次请求额度）
MONTHLY_PROBE_INTERVAL_SEC = 6 * 3600
# account_id → (探测时间, 是否月度耗尽)
_probe_cache: dict[str, tuple[float, bool]] = {}


def _detail_to_window(wtype: WindowType, detail: dict) -> UsageWindow:
    used = to_float(detail.get("used"))
    limit = to_float(detail.get("limit"))
    remaining = to_float(detail.get("remaining"))
    if used is None and limit is not None and remaining is not None:
        used = limit - remaining
    reset = None
    for k in ("resetTime", "reset_at", "reset_time", "reset_in"):
        if detail.get(k) is not None:
            reset = parse_time_to_epoch(detail[k])
            if reset is not None:
                break
    return UsageWindow(window_type=wtype, percent=pct(used, limit), used=used, limit=limit, reset_at=reset)


class KimiProvider(Provider):
    name = "kimi"
    last_raw: dict | None = None  # 最近一次原始响应，用于诊断

    def fetch(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        if not account.key:
            raise ProviderError(ErrorKind.AUTH, "未配置 API Key")
        headers = {"Authorization": f"Bearer {account.key}"}
        try:
            data = get_json(client, "GET", API_URL, headers=headers)
        except ProviderError as e:
            if e.kind == ErrorKind.HTTP:
                data = get_json(client, "GET", FALLBACK_URL, headers=headers)
            else:
                raise
        self.last_raw = data

        limits = data.get("limits") or []
        five_hour: UsageWindow | None = None
        seven_day: UsageWindow | None = None
        unmatched: list[UsageWindow] = []
        for item in limits:
            window = item.get("window") or {}
            detail = item.get("detail") or item
            duration = to_float(window.get("duration"))
            # 真实 API 返回枚举风格 "TIME_UNIT_MINUTE"，去掉前缀统一比较
            unit = str(window.get("timeUnit") or "").upper().replace("TIME_UNIT_", "")
            if (duration == 300 and unit.startswith("MINUTE")) or (duration == 5 and unit.startswith("HOUR")):
                five_hour = _detail_to_window(WindowType.FIVE_HOUR, detail)
            elif (duration == 7 and unit.startswith("DAY")) or (duration == 1 and unit.startswith("WEEK")):
                seven_day = _detail_to_window(WindowType.SEVEN_DAY, detail)
            else:
                # 未识别的窗口：按窗口时长推断
                minutes = _window_minutes(duration, unit)
                if minutes is not None:
                    if minutes <= 360 and five_hour is None:
                        five_hour = _detail_to_window(WindowType.FIVE_HOUR, detail)
                    elif minutes >= 6 * 24 * 60 and seven_day is None:
                        seven_day = _detail_to_window(WindowType.SEVEN_DAY, detail)
                    else:
                        unmatched.append(_detail_to_window(WindowType.FIVE_HOUR, detail))

        # 顶层 usage 作为周窗口兜底
        if seven_day is None and isinstance(data.get("usage"), dict):
            seven_day = _detail_to_window(WindowType.SEVEN_DAY, data["usage"])

        windows = [w for w in (five_hour, seven_day) if w is not None]
        if not windows:
            raise ProviderError(ErrorKind.PARSE, "响应中未找到用量窗口数据")
        if self._probe_monthly_exhausted(account, client, windows):
            windows.append(UsageWindow(window_type=WindowType.MONTHLY, percent=100.0))
        return self.snapshot(account, windows)

    def _probe_monthly_exhausted(self, account: Account, client: httpx.Client,
                                 windows: list[UsageWindow]) -> bool:
        """月度配额耗尽探测。

        usages 接口完全不暴露月度池；月度耗尽时推理请求返回
        403 "usage limit for this billing cycle"。但 5h/周窗口耗尽可能报同样的错，
        因此仅当 5h 和周窗口都远未满（<95%，留竞态余量）时才发探测——
        只有这种情况下的 403 才能判定为月度耗尽。
        探测会消耗 1 次请求额度，结论（含"健康"）缓存 6 小时。
        """
        cached = _probe_cache.get(account.id)
        fresh = cached and time.time() - cached[0] < MONTHLY_PROBE_INTERVAL_SEC
        present = [w for w in windows if w.percent is not None]
        if fresh or not present or any(w.percent >= 95.0 for w in present):
            return cached[1] if cached else False
        try:
            resp = client.post(
                CHAT_URL,
                headers={"Authorization": f"Bearer {account.key}"},
                json={"model": "kimi-for-coding",
                      "messages": [{"role": "user", "content": "."}],
                      "max_tokens": 1},
            )
        except httpx.HTTPError:
            return cached[1] if cached else False
        text = resp.text
        if resp.status_code == 403 and (("usage limit" in text and "billing cycle" in text)
                                        or "access_terminated_error" in text):
            verdict = True
        elif resp.status_code < 500:
            verdict = False
        else:
            return cached[1] if cached else False  # 5xx 不确定，沿用缓存
        _probe_cache[account.id] = (time.time(), verdict)
        return verdict


def _window_minutes(duration: float | None, unit: str) -> float | None:
    if duration is None:
        return None
    if unit.startswith("MINUTE"):
        return duration
    if unit.startswith("HOUR"):
        return duration * 60
    if unit.startswith("DAY"):
        return duration * 1440
    if unit.startswith("WEEK"):
        return duration * 10080
    return None
