"""fmt_reset：重置时间必须带日历日信息——"明天 14:38"只显示"14:38"会被误读为今天已过去的时间。"""

import time
from datetime import datetime, timedelta

from app.ui.panel import fmt_reset


def test_unknown_and_expired():
    assert fmt_reset(None) == "重置时间未知"
    assert fmt_reset(time.time() - 60) == "已到期，待刷新"


def test_minutes_within_an_hour():
    assert fmt_reset(time.time() + 32 * 60) == "31 分钟后重置"


def test_same_day_shows_plain_time():
    reset = time.time() + 2 * 3600 + 120
    dt = time.localtime(reset)
    now = time.localtime()
    same_day = (dt.tm_year, dt.tm_yday) == (now.tm_year, now.tm_yday)
    expected = ("" if same_day else "明天 ") + f"{dt.tm_hour:02d}:{dt.tm_min:02d} 重置"
    assert fmt_reset(reset) == expected


def test_tomorrow_is_prefixed():
    """回归：tj 账号 7 天窗口 reset=明天 14:38，显示"14:38 重置"被误读为今天已过期。"""
    tomorrow = datetime.now() + timedelta(days=1)
    reset = tomorrow.replace(hour=14, minute=38, second=0, microsecond=0).timestamp()
    assert fmt_reset(reset) == "明天 14:38 重置"


def test_beyond_tomorrow_shows_date_and_time():
    d = datetime.now() + timedelta(days=3)
    reset = d.replace(hour=9, minute=5, second=0, microsecond=0).timestamp()
    assert fmt_reset(reset) == f"{d.month}/{d.day} 09:05 重置"
def test_window_reset_exhausted():
    """月度耗尽（100% 且无重置时间）显示"已耗尽"而非"重置时间未知"。"""
    from app.ui.panel import fmt_window_reset
    from app.core.models import UsageWindow, WindowType
    w = UsageWindow(WindowType.MONTHLY, percent=100.0, reset_at=None)
    assert "已耗尽" in fmt_window_reset(w)
    # 100% 但有重置时间 → 正常显示重置时间（如 5h 窗口打满）
    w2 = UsageWindow(WindowType.FIVE_HOUR, percent=100.0, reset_at=time.time() + 1800)
    assert "已耗尽" not in fmt_window_reset(w2)
    # 未满无重置时间 → 原样
    w3 = UsageWindow(WindowType.SEVEN_DAY, percent=50.0, reset_at=None)
    assert fmt_window_reset(w3) == "重置时间未知"
