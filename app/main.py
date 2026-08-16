"""应用入口：装配配置、缓存、调度器与 UI。"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.core.cache import load_snapshots, save_snapshots
from app.core.config import Config, load_config, save_config
from app.core.models import AccountResult
from app.core.scheduler import RefreshScheduler
from app.ui.panel import UsagePanel
from app.ui.settings import SettingsDialog
from app.ui.strip import StripWidget
from app.ui.tray import TrayController

APP_NAME = "coding-plan-monitor"
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(enabled: bool) -> None:
    """Windows 开机自启（注册表 Run 键）。

    注册 pythonw.exe + launch.pyw 绝对路径：无控制台窗口、不依赖启动时的工作目录。
    """
    if sys.platform != "win32":
        return
    reg = QSettings(RUN_KEY, QSettings.Format.NativeFormat)
    if not enabled:
        reg.remove(APP_NAME)
        return
    if getattr(sys, "frozen", False):
        # 打包后的 exe：直接注册自身路径
        reg.setValue(APP_NAME, f'"{sys.executable}"')
        return
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    launcher = os.path.join(project_root, "launch.pyw")
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    reg.setValue(APP_NAME, f'"{pythonw}" "{launcher}"')


class AppController(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config: Config = load_config()
        self.results: dict[str, AccountResult] = {}
        self._cached = load_snapshots()

        self.scheduler = RefreshScheduler(self.config.settings.poll_interval_sec)
        self.scheduler.resultReady.connect(self._on_result)

        self.tray = TrayController()
        self.panel = UsagePanel()
        self.panel.set_columns(self.config.settings.panel_columns)
        self.strip = StripWidget()

        self._wire_signals()
        self._seed_from_cache()
        self._show_strip()
        self._reload_accounts()

    # ---- 信号装配 ----

    def _wire_signals(self) -> None:
        t = self.tray
        t.showPanelRequested.connect(self.show_panel)
        t.refreshAllRequested.connect(self.scheduler.refresh_all)
        t.settingsRequested.connect(self.open_settings)
        t.quitRequested.connect(self.app.quit)

        p = self.panel
        p.refreshAllRequested.connect(self.scheduler.refresh_all)
        p.refreshAccountRequested.connect(self.scheduler.force_refresh)
        p.settingsRequested.connect(self.open_settings)

        s = self.strip
        s.refreshAllRequested.connect(self.scheduler.refresh_all)
        s.showPanelRequested.connect(self.show_panel)
        s.settingsRequested.connect(self.open_settings)
        s.quitRequested.connect(self.app.quit)
        s.moved.connect(self._on_strip_moved)
        s.lockChanged.connect(self._on_strip_locked)

    # ---- 数据流 ----

    def _seed_from_cache(self) -> None:
        """启动时先用缓存快照填充，避免冷启动空白。"""
        for acc in self.config.accounts:
            snap = self._cached.get(acc.id)
            if snap:
                self.results[acc.id] = AccountResult(
                    account_id=acc.id, provider=acc.provider,
                    account_name=acc.display_name, snapshot=snap, updated_at=snap.fetched_at)
        self._push_results()

    def _on_result(self, result: AccountResult) -> None:
        old = self.results.get(result.account_id)
        if not result.ok and old is not None and old.ok:
            # 失败时保留旧快照，只更新错误状态提示
            old.error_kind = result.error_kind
            old.error_msg = result.error_msg
            old.updated_at = result.updated_at
            self.results[result.account_id] = AccountResult(
                account_id=old.account_id, provider=old.provider, account_name=old.account_name,
                snapshot=old.snapshot, error_kind=result.error_kind,
                error_msg=result.error_msg, updated_at=result.updated_at)
        else:
            self.results[result.account_id] = result
        # 成功的快照持久化
        good = {aid: r.snapshot for aid, r in self.results.items() if r.snapshot is not None}
        save_snapshots(good)
        self._push_results()

    def _push_results(self) -> None:
        # 配置中已删除/禁用的账号不再展示
        visible = {a.id: self.results[a.id] for a in self.config.enabled_accounts() if a.id in self.results}
        self.tray.update_results(visible)
        self.panel.update_results(visible)
        self.strip.update_results(visible)

    # ---- UI 行为 ----

    def show_panel(self) -> None:
        if self.panel.isVisible():
            self.panel.hide()
            return
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        # 高度上限跟随屏幕可用区域（而不是固定 640），内容少时自动收紧
        self.panel.setMaximumHeight(geo.height() - 16)
        self.panel._fit_to_content()
        # 宽度超出屏幕可用区域时压回屏幕内（内部出现横向滚动条兜底）
        if self.panel.width() > geo.width() - 16:
            self.panel.resize(geo.width() - 16, self.panel.height())
        x = max(geo.left(), min(pos.x(), geo.right() - self.panel.width()))
        y = geo.bottom() - self.panel.height() - 8
        self.panel.move(x, max(geo.top(), y))
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def _show_strip(self) -> None:
        """悬浮窄条常驻：恢复持久化的位置与锁定状态。"""
        st = self.config.settings
        if st.strip_x is not None and st.strip_y is not None:
            self.strip.move(st.strip_x, st.strip_y)
        else:
            # 默认放主屏任务栏上方右侧
            geo = QGuiApplication.primaryScreen().availableGeometry()
            self.strip.adjustSize()
            self.strip.move(geo.right() - self.strip.width() - 200, geo.bottom() - self.strip.height() - 4)
        self.strip.set_locked(st.strip_locked)
        self.strip.show()

    def _on_strip_moved(self, x: int, y: int) -> None:
        self.config.settings.strip_x = x
        self.config.settings.strip_y = y
        save_config(self.config)

    def _on_strip_locked(self, locked: bool) -> None:
        self.config.settings.strip_locked = locked
        save_config(self.config)

    def _reload_accounts(self) -> None:
        self.scheduler.set_accounts(self.config.accounts)
        self.scheduler.set_interval(self.config.settings.poll_interval_sec)
        self._push_results()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config)
        dlg.configSaved.connect(self._on_config_saved)
        dlg.exec()

    def _on_config_saved(self) -> None:
        save_config(self.config)
        set_autostart(self.config.settings.autostart)
        self.panel.set_columns(self.config.settings.panel_columns)
        self._reload_accounts()
        self._show_strip()
        self.scheduler.force_refresh()

    def run(self) -> None:
        self.tray.show()
        self.scheduler.start(immediate=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if getattr(sys, "frozen", False):
        # 打包后加载随包图标（开发模式下托盘等使用代码绘制图标）
        from PySide6.QtGui import QIcon
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        icon_path = os.path.join(base, "app.png")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("Coding Plan 用量监控")
    controller = AppController(app)
    controller.run()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
