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
def test_settings_volcano_ak_roundtrip(qapp):
    """火山账号编辑：AK/SK 与套餐类型正确回填并保存。"""
    from app.core.config import Account
    from app.ui.settings import AccountEditDialog
    acc = Account(provider="volcano", name="火山", access_key_id="AK1",
                  secret_access_key="SK1", plan_type="agent")
    dlg = AccountEditDialog(acc)
    assert dlg._vol_ak.text() == "AK1"
    assert dlg._vol_sk.text() == "SK1"
    assert dlg._vol_plan.currentData() == "agent"
    dlg._vol_plan.setCurrentIndex(dlg._vol_plan.findData("auto"))
    dlg.accept()
    out = dlg.account
    assert out.access_key_id == "AK1"
    assert out.secret_access_key == "SK1"
    assert out.plan_type == "auto"
def test_panel_columns_fit_content(qapp):
    """回归：多列布局下面板宽度必须容纳卡片内容，否则右列被裁切、底部出现横向滚动条。

    复现：2 列 × 4 账号，卡片内容宽约 500px（重置时间文本决定），
    旧实现固定 300px/列 → 窗口 640px < 内容 1016px。
    """
    from app.ui.panel import UsagePanel
    panel = UsagePanel()
    panel.set_columns(2)
    results = {f"a{i}": make_result(ok=True) for i in range(4)}
    for i, r in enumerate(results.values()):
        r.account_id = f"a{i}"
    panel.update_results(results)
    panel.show()
    qapp.processEvents()
    needed = panel._container.sizeHint().width()
    assert panel.width() >= needed, f"面板宽 {panel.width()} < 内容宽 {needed}"
    panel.hide()
def test_panel_height_grows_with_rows(qapp):
    """回归：面板高度必须随行数增长，直到屏幕高度上限。

    旧实现 adjustSize 拿到的 sizeHint 不含滚动区内容高度：2 行 3 行都只有 334px，
    3 行账号被强制滚动。离屏屏幕 800px，3 行内容 ~594px 应完整放下。
    """
    from app.ui.panel import UsagePanel
    panel = UsagePanel()
    panel.set_columns(2)
    results = {f"a{i}": make_result(ok=True) for i in range(6)}
    for i, r in enumerate(results.values()):
        r.account_id = f"a{i}"
    panel.update_results(results)
    panel.show()
    qapp.processEvents()
    need_h = panel._container.sizeHint().height()
    got_h = panel._scroll.viewport().height()
    panel.hide()
    assert got_h >= need_h, f"视口高 {got_h} < 内容高 {need_h}（3 行被滚动裁切）"


def test_panel_height_respects_cap(qapp):
    """高度上限仍生效：内容超高时压到上限以内，由垂直滚动条兜底。"""
    from app.ui.panel import UsagePanel
    panel = UsagePanel()
    panel.set_columns(1)
    panel.setMaximumHeight(400)
    results = {f"a{i}": make_result(ok=True) for i in range(6)}
    for i, r in enumerate(results.values()):
        r.account_id = f"a{i}"
    panel.update_results(results)
    panel.show()
    qapp.processEvents()
    h = panel.height()
    panel.hide()
    assert h <= 400, f"面板高 {h} 超过上限 400"
def _exhausted_result():
    """月度耗尽的账号快照（Kimi 场景：5h/7d 窗口远未满）。"""
    snap = UsageSnapshot("kimi", "wq", [
        UsageWindow(WindowType.FIVE_HOUR, 3.0, reset_at=9999999999.0),
        UsageWindow(WindowType.SEVEN_DAY, 35.0, reset_at=9999999999.0),
        UsageWindow(WindowType.MONTHLY, 100.0),
    ])
    return AccountResult(account_id="a1", provider="kimi", account_name="wq", snapshot=snap)


def test_snapshot_display_percent_monthly_exhausted(qapp):
    """全局规则：月度耗尽 ⇒ 5h/7d 展示百分比强制 100（真实值保留在窗口数据里）。"""
    snap = _exhausted_result().snapshot
    assert snap.monthly_exhausted
    assert snap.display_percent(WindowType.FIVE_HOUR) == 100.0
    assert snap.display_percent(WindowType.SEVEN_DAY) == 100.0
    assert snap.display_percent(WindowType.MONTHLY) == 100.0
    # 未耗尽时透传
    snap2 = make_result(ok=True).snapshot
    assert not snap2.monthly_exhausted
    assert snap2.display_percent(WindowType.FIVE_HOUR) == 45.0


def test_panel_rings_forced_red_on_monthly_exhausted(qapp):
    """详情面板：月度耗尽时 5h/7d 环显示 100%（红）。"""
    from app.ui.panel import UsagePanel
    panel = UsagePanel()
    panel.update_results({"a1": _exhausted_result()})
    card = panel._cards["a1"]
    assert card._rings[WindowType.FIVE_HOUR]._canvas._percent == 100.0
    assert card._rings[WindowType.SEVEN_DAY]._canvas._percent == 100.0
    assert card._rings[WindowType.MONTHLY]._canvas._percent == 100.0


def test_strip_rings_forced_red_on_monthly_exhausted(qapp):
    """悬浮窄条：月度耗尽时双环同样强制 100%。"""
    from app.ui.strip import MiniRing
    ring = MiniRing()
    ring.set_result(_exhausted_result())
    assert ring._outer == 100.0
    assert ring._inner == 100.0
    assert "月度: 100%" in ring.toolTip()
