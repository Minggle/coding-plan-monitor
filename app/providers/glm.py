"""智谱 GLM Coding Plan：GET {site}/api/monitor/usage/quota/limit，裸 key（无 Bearer）。

- TOKENS_LIMIT (unit=3, number=5) → 5 小时窗口
- TOKENS_LIMIT (unit=6, number=1) → 每周窗口
- TIME_LIMIT → MCP 工具月度额度
"""

from __future__ import annotations

import httpx

from app.core.config import Account
from app.core.models import ErrorKind, UsageSnapshot, UsageWindow, WindowType
from app.providers.base import (
    Provider,
    ProviderError,
    get_json,
    pct,
    parse_time_to_epoch,
    to_float,
)

SITES = ("open.bigmodel.cn", "api.z.ai")
API_PATH = "/api/monitor/usage/quota/limit"


def _percent(item: dict) -> float | None:
    """GLM 的 percentage 字段恒为 0-100 整数百分比，不能套用 0-1 小数缩放
    （否则 percentage=1 会被误判成 100%）。优先用 currentValue/usage 精确计算，
    缺失时回退到 percentage 字段，仅做 0-100 裁剪。"""
    used = to_float(item.get("currentValue"))
    limit = to_float(item.get("usage"))
    p = pct(used, limit)
    if p is not None:
        return p
    raw = to_float(item.get("percentage"))
    if raw is None:
        return None
    return max(0.0, min(100.0, raw))


class GlmProvider(Provider):
    name = "glm"
    last_raw: dict | None = None

    def fetch(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        if not account.key:
            raise ProviderError(ErrorKind.AUTH, "未配置 API Key")
        site = account.site if account.site in SITES else SITES[0]
        url = f"https://{site}{API_PATH}"
        headers = {
            "Authorization": account.key,  # GLM 不带 Bearer 前缀
            "Accept-Language": "zh-CN,zh",
            "Content-Type": "application/json",
        }
        data = get_json(client, "GET", url, headers=headers)
        self.last_raw = data

        # 真实响应外层包了一层 {code, msg, data, success}
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        limits = payload.get("limits") or []
        five_hour: UsageWindow | None = None
        seven_day: UsageWindow | None = None
        monthly: UsageWindow | None = None
        unmatched_token_limits: list[UsageWindow] = []

        for item in limits:
            itype = item.get("type")
            # TOKENS_LIMIT（pro 档）与 CREDIT_LIMIT（lite 档）都是配额窗口
            if itype in ("TOKENS_LIMIT", "CREDIT_LIMIT"):
                # unit/number 可能是字符串数字，统一转换后比较
                unit, number = to_float(item.get("unit")), to_float(item.get("number"))
                w = UsageWindow(
                    window_type=WindowType.FIVE_HOUR,
                    percent=_percent(item),
                    used=to_float(item.get("currentValue")),
                    limit=to_float(item.get("usage")),
                    reset_at=parse_time_to_epoch(item.get("nextResetTime")),
                )
                if unit == 3 and number == 5:
                    five_hour = w
                elif unit == 6 and number == 1:
                    w.window_type = WindowType.SEVEN_DAY
                    seven_day = w
                else:
                    unmatched_token_limits.append(w)
            elif itype == "TIME_LIMIT":
                monthly = UsageWindow(
                    window_type=WindowType.MONTHLY,
                    percent=_percent(item),
                    used=to_float(item.get("currentValue")),
                    limit=to_float(item.get("usage")),
                    reset_at=parse_time_to_epoch(item.get("nextResetTime")),
                )

        # 未识别的 TOKENS_LIMIT 按出现顺序兜底：第一个→5h，第二个→7d
        for w in unmatched_token_limits:
            if five_hour is None:
                w.window_type = WindowType.FIVE_HOUR
                five_hour = w
            elif seven_day is None:
                w.window_type = WindowType.SEVEN_DAY
                seven_day = w

        windows = [w for w in (five_hour, seven_day, monthly) if w is not None]
        if not windows:
            raise ProviderError(ErrorKind.PARSE, "响应中未找到配额数据")
        return self.snapshot(account, windows)
