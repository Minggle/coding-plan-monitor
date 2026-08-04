"""统一数据模型：所有 provider 输出 UsageSnapshot，UI 只认这个结构。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class WindowType(str, Enum):
    FIVE_HOUR = "5h"
    SEVEN_DAY = "7d"
    MONTHLY = "monthly"


WINDOW_ORDER = [WindowType.FIVE_HOUR, WindowType.SEVEN_DAY, WindowType.MONTHLY]

WINDOW_LABELS = {
    WindowType.FIVE_HOUR: "5 小时",
    WindowType.SEVEN_DAY: "7 天",
    WindowType.MONTHLY: "月度",
}


@dataclass
class UsageWindow:
    """单个时间窗口的用量。percent 为 0-100；used/limit 单位因厂商而异（可为 None）。"""

    window_type: WindowType
    percent: float | None = None
    used: float | None = None
    limit: float | None = None
    reset_at: float | None = None  # epoch 秒


@dataclass
class UsageSnapshot:
    """一次查询的完整结果。"""

    provider: str
    account_name: str
    windows: list[UsageWindow] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)

    def window(self, wtype: WindowType) -> UsageWindow | None:
        for w in self.windows:
            if w.window_type == wtype:
                return w
        return None

    @property
    def max_percent(self) -> float:
        """所有窗口中最接近限额的百分比，用于托盘默认展示。"""
        vals = [w.percent for w in self.windows if w.percent is not None]
        return max(vals) if vals else 0.0


class ErrorKind(str, Enum):
    NETWORK = "network"        # 网络/超时
    AUTH = "auth"              # 401/403：key 无效或 Cookie 过期
    PARSE = "parse"            # 响应结构不符
    HTTP = "http"              # 其他 HTTP 错误


@dataclass
class AccountResult:
    """一个账号的一次查询结果：成功带 snapshot，失败带 error。"""

    account_id: str
    provider: str
    account_name: str
    snapshot: UsageSnapshot | None = None
    error_kind: ErrorKind | None = None
    error_msg: str = ""
    updated_at: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.snapshot is not None and self.error_kind is None

    @property
    def has_data(self) -> bool:
        """有可展示的快照（可能是失败时保留的旧数据）。"""
        return self.snapshot is not None
