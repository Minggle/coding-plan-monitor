"""悬浮窄条：无边框置顶小长条，吸附任务栏，迷你进度环横排，可拖拽/锁定。

任务栏也是置顶窗口，点击任务栏会盖住窄条，因此用定时器周期性 raise
（只调 Z-order，不抢焦点），保证窄条始终浮在任务栏之上。
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QWidget

from app.core.models import WINDOW_LABELS, AccountResult, WindowType
from app.ui.rings import COLOR_TEXT, draw_ring


def _remaining_minutes(reset_at: float) -> int:
    """距离重置的剩余分钟数，向上取整（剩 30 秒也显示 1，不显示 0）。"""
    return max(0, math.ceil((reset_at - time.time()) / 60))


class MiniRing(QWidget):
    """窄条里的双环控件：外环 5 小时，内环 7 天，tooltip 显示全部。"""

    SIZE = 44

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE + 14)
        self._outer: float | None = None  # 5h
        self._inner: float | None = None  # 7d
        self._name = ""
        self._center = "--"
        self._reset_at: float | None = None  # 5h 窗口重置时间，tick 时重算剩余分钟

    def tick(self) -> None:
        """重算中心剩余分钟数（不必等下一次网络刷新）。"""
        if self._reset_at:
            self._center = str(_remaining_minutes(self._reset_at))
            self.update()

    def set_result(self, result: AccountResult) -> None:
        self._name = result.account_name
        if result.has_data:
            snap = result.snapshot
            w5 = snap.window(WindowType.FIVE_HOUR)
            w7 = snap.window(WindowType.SEVEN_DAY)
            # 月度耗尽时双环强制 100%（账号整体被锁）
            self._outer = snap.display_percent(WindowType.FIVE_HOUR)
            self._inner = snap.display_percent(WindowType.SEVEN_DAY)
            # 中心数字：5h 窗口距离重置的剩余分钟数
            self._reset_at = w5.reset_at if w5 is not None else None
            remain_min = _remaining_minutes(self._reset_at) if self._reset_at else None
            self._center = str(remain_min) if remain_min is not None else "--"
            lines = [result.account_name, "外环=5小时 内环=7天 中心=5h剩余分钟"]
            for wt in WindowType:
                pct = snap.display_percent(wt)
                if pct is not None:
                    lines.append(f"{WINDOW_LABELS[wt]}: {pct:.0f}%")
            if result.error_kind is not None:
                lines.append(f"⚠ {result.error_msg}")
            self.setToolTip("\n".join(lines))
        else:
            self._outer = None
            self._inner = None
            self._reset_at = None
            self._center = "!"
            self.setToolTip(f"{result.account_name}\n{result.error_msg}")
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        pen = 4.0
        gap = 1.6
        margin = pen / 2 + 1
        outer_rect = QRectF((self.width() - self.SIZE) / 2 + margin, margin,
                            self.SIZE - 2 * margin, self.SIZE - 2 * margin)
        draw_ring(painter, outer_rect, self._outer, pen_width=pen)
        inset = pen + gap
        inner_rect = QRectF(outer_rect.x() + inset, outer_rect.y() + inset,
                            outer_rect.width() - 2 * inset, outer_rect.height() - 2 * inset)
        center_font = painter.font()
        # 三位数（如 300 分钟）缩小字号避免溢出内环
        center_font.setPixelSize(11 if len(self._center) <= 2 else 8)
        center_font.setBold(True)
        draw_ring(painter, inner_rect, self._inner, pen_width=pen,
                  center_text=self._center, font=center_font)
        painter.setPen(COLOR_TEXT)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        name = self._name[:6]
        painter.drawText(QRectF(0, self.SIZE, self.width(), 14),
                         Qt.AlignmentFlag.AlignCenter, name)
        painter.end()


class StripWidget(QWidget):
    """悬浮窄条主窗口。"""

    refreshAllRequested = Signal()
    showPanelRequested = Signal()
    settingsRequested = Signal()
    quitRequested = Signal()
    lockChanged = Signal(bool)
    moved = Signal(int, int)  # 新位置，供配置持久化

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet("StripWidget { background: #222; border: 1px solid #444; border-radius: 8px; }")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(8)
        self._rings: dict[str, MiniRing] = {}
        self._empty = QLabel("无账号")
        self._empty.setStyleSheet("color: #999;")
        self._layout.addWidget(self._empty)
        self._drag_start: QPoint | None = None
        self.locked = False
        self._menu_open = False
        # 周期性浮到最顶层，防止被任务栏/其他置顶窗口盖住
        self._raise_timer = QTimer(self)
        self._raise_timer.setInterval(1500)
        self._raise_timer.timeout.connect(self._keep_on_top)
        self._raise_timer.start()
        # 每 30 秒重算各环中心的剩余分钟数
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(30_000)
        self._tick_timer.timeout.connect(self._tick_rings)
        self._tick_timer.start()

    def _tick_rings(self) -> None:
        for ring in self._rings.values():
            ring.tick()

    def _keep_on_top(self) -> None:
        # 有模态对话框（如设置）或弹出菜单时不能 raise，否则会把它们盖到窄条后面
        from PySide6.QtWidgets import QApplication
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return
        if self.isVisible() and self._drag_start is None and not self._menu_open:
            self.raise_()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.raise_()

    def set_locked(self, locked: bool) -> None:
        if locked != self.locked:
            self.locked = locked
            self.lockChanged.emit(locked)

    def update_results(self, results: dict[str, AccountResult]) -> None:
        self._empty.setVisible(not results)
        for account_id in list(self._rings):
            if account_id not in results:
                ring = self._rings.pop(account_id)
                self._layout.removeWidget(ring)
                ring.deleteLater()
        for account_id, result in results.items():
            ring = self._rings.get(account_id)
            if ring is None:
                ring = MiniRing()
                self._rings[account_id] = ring
                self._layout.addWidget(ring)
            ring.set_result(result)
        self.adjustSize()

    # ---- 拖拽 ----

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and not self.locked:
            self._drag_start = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_start is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_start)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._drag_start is not None:
            self._drag_start = None
            self.moved.emit(self.x(), self.y())
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        self.showPanelRequested.emit()
        super().mouseDoubleClickEvent(e)

    # ---- 右键菜单 ----

    def contextMenuEvent(self, e) -> None:
        menu = QMenu(self)
        # 注意：addAction(text, signal) 在 PySide6 中会静默失效，必须用 lambda 包装 emit
        menu.addAction("查看详情", lambda: self.showPanelRequested.emit())
        menu.addAction("立即刷新", lambda: self.refreshAllRequested.emit())
        lock_action = menu.addAction("锁定位置")
        lock_action.setCheckable(True)
        lock_action.setChecked(self.locked)
        lock_action.toggled.connect(self.set_locked)
        menu.addSeparator()
        menu.addAction("设置", lambda: self.settingsRequested.emit())
        menu.addAction("退出", lambda: self.quitRequested.emit())
        self._menu_open = True
        try:
            menu.exec(e.globalPos())
        finally:
            self._menu_open = False
