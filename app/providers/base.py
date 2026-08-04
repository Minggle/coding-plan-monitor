"""Provider 抽象与公共工具。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from app.core.config import Account
from app.core.models import ErrorKind, UsageSnapshot, UsageWindow, WindowType


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, msg: str):
        super().__init__(msg)
        self.kind = kind
        self.msg = msg


def parse_time_to_epoch(value) -> float | None:
    """兼容 ISO 字符串、epoch 秒、epoch 毫秒，统一返回 epoch 秒。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # 毫秒
            v /= 1000.0
        return v
    s = str(value).strip()
    if not s:
        return None
    # 纯数字字符串
    try:
        return parse_time_to_epoch(float(s))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(s.replace("Z", "+0000"), fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_percent(value) -> float | None:
    """Percent 可能是 0-1 小数或 0-100 数值，统一为 0-100。"""
    v = to_float(value)
    if v is None:
        return None
    if 0 <= v <= 1:
        v *= 100
    return max(0.0, min(100.0, v))


def pct(used: float | None, limit: float | None) -> float | None:
    if used is None or not limit:
        return None
    return max(0.0, min(100.0, used / limit * 100))


class Provider(ABC):
    name: str = ""

    @abstractmethod
    def fetch(self, account: Account, client: httpx.Client) -> UsageSnapshot:
        """成功返回 UsageSnapshot；失败抛 ProviderError。"""

    def snapshot(self, account: Account, windows: list[UsageWindow]) -> UsageSnapshot:
        return UsageSnapshot(provider=self.name, account_name=account.display_name, windows=windows)


def raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code in (401, 403):
        raise ProviderError(ErrorKind.AUTH, f"鉴权失败（HTTP {resp.status_code}），key 无效或凭证已过期")
    if resp.status_code >= 400:
        raise ProviderError(ErrorKind.HTTP, f"HTTP {resp.status_code}: {resp.text[:200]}")


def get_json(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    try:
        resp = client.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        raise ProviderError(ErrorKind.NETWORK, f"网络错误：{e}") from e
    raise_for_status(resp)
    try:
        data = resp.json()
    except ValueError as e:
        raise ProviderError(ErrorKind.PARSE, f"响应不是 JSON：{resp.text[:200]}") from e
    if not isinstance(data, dict):
        raise ProviderError(ErrorKind.PARSE, "响应 JSON 不是对象")
    return data


def default_client(**kwargs) -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=True, **kwargs)


def pick_reset_future(candidates: list[tuple[float | None, UsageWindow]]) -> UsageWindow | None:
    """周期切换瞬间可能出现新旧两条记录：取 reset 在未来且最近的一条，否则取 reset 最大的一条。"""
    valid = [(r, w) for r, w in candidates if r is not None]
    if not valid:
        return candidates[0][1] if candidates else None
    now = time.time()
    future = [(r, w) for r, w in valid if r > now]
    if future:
        return min(future, key=lambda x: x[0])[1]
    return max(valid, key=lambda x: x[0])[1]


WINDOW_KEY_MAP = {
    WindowType.FIVE_HOUR: "5h",
    WindowType.SEVEN_DAY: "7d",
    WindowType.MONTHLY: "monthly",
}
