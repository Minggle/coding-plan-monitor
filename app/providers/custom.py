"""自定义供应商：用户配置 URL/方法/请求头模板 + 三个窗口的 JSON 路径映射。

- headers 值中的 {KEY} 会替换为账号 key
- paths: {"5h": "data.five_hour", "7d": "...", "monthly": "..."}，点号分隔路径
- 路径指向的值可以是：
  - 数字（视为百分比）
  - 对象 {"percent": x, "used": x, "limit": x, "reset": x}（字段名兼容 percent/percentage、reset/resetTime/reset_at）
"""

from __future__ import annotations

import httpx

from app.core.config import Account
from app.core.models import ErrorKind, UsageSnapshot, UsageWindow, WindowType
from app.providers.base import (
    WINDOW_KEY_MAP,
    Provider,
    ProviderError,
    get_json,
    normalize_percent,
    parse_time_to_epoch,
    pct,
    to_float,
)

_WINDOW_TYPES = (WindowType.FIVE_HOUR, WindowType.SEVEN_DAY, WindowType.MONTHLY)


def _dig(data, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _first_key(d: dict, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _value_to_window(wtype: WindowType, value) -> UsageWindow | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        p = normalize_percent(value)
        if p is None:
            return None
        return UsageWindow(window_type=wtype, percent=p)
    if isinstance(value, dict):
        used = to_float(_first_key(value, "used", "currentValue"))
        limit = to_float(_first_key(value, "limit", "usage", "total"))
        percent = normalize_percent(_first_key(value, "percent", "percentage"))
        if percent is None:
            percent = pct(used, limit)
        reset = parse_time_to_epoch(_first_key(value, "reset", "resetTime", "reset_at", "nextResetTime"))
        if percent is None and used is None:
            return None
        return UsageWindow(window_type=wtype, percent=percent, used=used, limit=limit, reset_at=reset)
    return None


class CustomProvider(Provider):
    name = "custom"
    last_raw: dict | None = None

    def fetch(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        spec = account.custom
        if not spec.url:
            raise ProviderError(ErrorKind.PARSE, "未配置自定义供应商 URL")
        headers = {k: v.replace("{KEY}", account.key) for k, v in spec.headers.items()}
        kwargs: dict = {"headers": headers}
        body = (spec.body or "").replace("{KEY}", account.key)
        if body and spec.method.upper() != "GET":
            kwargs["content"] = body.encode("utf-8")

        data = get_json(client, spec.method.upper(), spec.url, **kwargs)
        self.last_raw = data

        windows = []
        for wt in _WINDOW_TYPES:
            path = spec.paths.get(WINDOW_KEY_MAP[wt])
            if not path:
                continue
            w = _value_to_window(wt, _dig(data, path))
            if w is not None:
                windows.append(w)
        if not windows:
            raise ProviderError(ErrorKind.PARSE, "按配置的路径未解析到任何窗口数据")
        return self.snapshot(account, windows)
