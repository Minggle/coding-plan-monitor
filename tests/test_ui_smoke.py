"""UI 烟雾测试：离屏模式下构造各窗口、喂数据、验证不崩。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.core.models import AccountResult, ErrorKind, UsageSnapshot, UsageWindow, WindowType


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_result(ok=True, stale=False):
    snap = UsageSnapshot(
        provider="kimi",
        account_name="主力",
        windows=[
            UsageWindow(window_type=WindowType.FIVE_HOUR, percent=45.0, reset_at=9999999999.0),
            UsageWindow(window_type=WindowType.SEVEN_DAY, percent=20.0, reset_at=9999999999.0),
        ],
    )
    return AccountResult(
        account_id="a1",
        provider="kimi",
        account_name="主力",
        snapshot=snap if (ok or stale) else None,
        error_kind=ErrorKind.NETWORK if stale else (None if ok else ErrorKind.AUTH),
        error_msg="网络错误" if (stale or not ok) else "",
    )


def test_ring_icon(qapp):
    from app.ui.rings import make_app_icon, make_double_ring_icon, make_ring_icon, percent_color
    icon = make_ring_icon(45.0)
    assert not icon.isNull()
    icon_none = make_ring_icon(None, error_badge=True)
    assert not icon_none.isNull()
    double_icon = make_double_ring_icon(45.0, 20.0)
    assert not double_icon.isNull()
    app_icon = make_app_icon(error_badge=True)
    assert not app_icon.isNull()
    from PySide6.QtGui import QColor
    assert percent_color(30) == QColor("#4caf50")
    assert percent_color(70) == QColor("#ff9800")
    assert percent_color(95) == QColor("#f44336")
    assert percent_color(None) == QColor("#9e9e9e")


def test_panel_update(qapp):
    from app.ui.panel import UsagePanel
    panel = UsagePanel()
    panel.update_results({"a1": make_result(ok=True)})
    panel.update_results({"a1": make_result(stale=True)})
    panel.update_results({"a1": make_result(ok=False)})
    panel.update_results({})  # 清空
    assert "a1" not in panel._cards


def test_strip_update(qapp):
    from app.ui.strip import StripWidget
    strip = StripWidget()
    strip.update_results({"a1": make_result(ok=True)})
    strip.update_results({"a1": make_result(ok=False)})
    strip.set_locked(True)
    assert strip.locked


def test_settings_dialog(qapp):
    from app.core.config import Account, Config
    from app.ui.settings import AccountEditDialog, SettingsDialog
    cfg = Config(accounts=[Account(provider="kimi", name="K", key="sk-1")])
    dlg = SettingsDialog(cfg)
    assert dlg._list.count() == 1
    edit = AccountEditDialog(cfg.accounts[0])
    assert edit._kimi_key.text() == "sk-1"


def test_scheduler_offscreen(qapp):
    from app.core.config import Account
    from app.core.scheduler import RefreshScheduler
    sch = RefreshScheduler(interval_sec=300)
    sch.set_accounts([Account(provider="kimi", key="x")])
    assert len(sch._accounts) == 1
    sch.set_interval(10)  # 下限 30s
    assert sch._timer.interval() == 30000


def test_strip_menu_actions_emit_signals(qapp):
    """回归：addAction(text, signal) 会静默失效，菜单项必须能真正发出信号。"""
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtCore import QPoint, QEvent
    from app.ui.strip import StripWidget

    strip = StripWidget()
    fired = []
    strip.settingsRequested.connect(lambda: fired.append("settings"))
    strip.showPanelRequested.connect(lambda: fired.append("panel"))
    strip.refreshAllRequested.connect(lambda: fired.append("refresh"))
    strip.quitRequested.connect(lambda: fired.append("quit"))

    # 直接复现菜单构建逻辑：触发 contextMenuEvent 抓不到 menu（局部变量），
    # 改为逐个检查——用 monkeypatch 替换 QMenu.exec 捕获菜单
    import app.ui.strip as strip_mod
    captured = {}

    class FakeMenu(strip_mod.QMenu):
        def exec(self, pos):
            captured['menu'] = self
            return None

    orig = strip_mod.QMenu
    strip_mod.QMenu = FakeMenu
    try:
        ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5))
        strip.contextMenuEvent(ev)
    finally:
        strip_mod.QMenu = orig

    menu = captured['menu']
    texts = {a.text(): a for a in menu.actions()}
    texts["设置"].trigger()
    texts["查看详情"].trigger()
    texts["立即刷新"].trigger()
    texts["退出"].trigger()
    assert fired == ["settings", "panel", "refresh", "quit"]


def test_strip_lock_emits_signal(qapp):
    """回归：锁定状态切换必须发出 lockChanged 信号以便持久化。"""
    from app.ui.strip import StripWidget
    strip = StripWidget()
    fired = []
    strip.lockChanged.connect(fired.append)
    strip.set_locked(True)
    strip.set_locked(True)   # 重复设置不重复发信号
    strip.set_locked(False)
    assert fired == [True, False]


def test_strip_center_shows_remaining_minutes(qapp):
    """中心数字 = 5h 窗口剩余分钟数，tick 会随时间递减。"""
    import time
    from app.ui.strip import MiniRing
    ring = MiniRing()
    reset = time.time() + 125 * 60
    result = AccountResult(
        account_id="a1", provider="kimi", account_name="K",
        snapshot=UsageSnapshot("kimi", "K", [
            UsageWindow(WindowType.FIVE_HOUR, 45.0, reset_at=reset),
            UsageWindow(WindowType.SEVEN_DAY, 20.0, reset_at=reset),
        ]),
    )
    ring.set_result(result)
    assert ring._center == "125"
    # 模拟 1 分钟后 tick
    ring._reset_at = time.time() + 124 * 60
    ring.tick()
    assert ring._center == "124"
    # 无 reset_at → "--"
    result.snapshot.windows[0].reset_at = None
    ring.set_result(result)
    assert ring._center == "--"
