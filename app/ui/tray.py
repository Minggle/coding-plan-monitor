"""系统托盘：静态图标（右键菜单入口），进度只在窄条/详情面板显示。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.core.models import WINDOW_LABELS, AccountResult, ErrorKind, WindowType
from app.providers import PROVIDER_LABELS
from app.ui.rings import make_app_icon


class TrayController(QObject):
    showPanelRequested = Signal()
    refreshAllRequested = Signal()
    modeSwitchRequested = Signal(str)     # "tray" | "strip"
    settingsRequested = Signal()
    quitRequested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(make_app_icon())
        self.tray.setToolTip("Coding Plan 用量监控")
        self._menu = QMenu()
        self.tray.setContextMenu(self._menu)
        self.tray.activated.connect(self._on_activated)
        self._results: dict[str, AccountResult] = {}
        self._rebuild_menu()

    def show(self) -> None:
        self.tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.showPanelRequested.emit()

    def update_results(self, results: dict[str, AccountResult]) -> None:
        self._results = results
        self._refresh_icon()

    # ---- 图标与 tooltip ----

    def _refresh_icon(self) -> None:
        has_auth_error = any(
            r.error_kind == ErrorKind.AUTH for r in self._results.values()
        )
        self.tray.setIcon(make_app_icon(error_badge=has_auth_error))

        if not self._results:
            self.tray.setToolTip("Coding Plan 用量监控\n尚未配置账号")
            return
        blocks = []
        for r in self._results.values():
            label = PROVIDER_LABELS.get(r.provider, r.provider)
            lines = [f"{r.account_name}（{label}）"]
            if r.has_data:
                for wt in WindowType:
                    w = r.snapshot.window(wt)
                    if w is not None and w.percent is not None:
                        lines.append(f"  {WINDOW_LABELS[wt]}: {w.percent:.0f}%")
            if r.error_kind is not None:
                lines.append(f"  ⚠ {r.error_msg}")
            blocks.append("\n".join(lines))
        self.tray.setToolTip("\n\n".join(blocks))

    # ---- 菜单 ----

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        act = self._menu.addAction("查看详情")
        act.triggered.connect(self.showPanelRequested)
        act = self._menu.addAction("立即刷新")
        act.triggered.connect(self.refreshAllRequested)

        self._menu.addSeparator()
        act = self._menu.addAction("设置")
        act.triggered.connect(self.settingsRequested)
        act = self._menu.addAction("退出")
        act.triggered.connect(self.quitRequested)

    def popup_pos(self):
        return QCursor.pos()
