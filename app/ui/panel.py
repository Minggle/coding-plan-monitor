"""详情面板：每个账号一张卡片，5h/7d/月度三个进度环 + 重置时间 + 刷新按钮。"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.models import AccountResult, UsageWindow, WINDOW_LABELS, WINDOW_ORDER, WindowType
from app.providers import PROVIDER_LABELS
from app.ui.rings import draw_ring


def fmt_reset(reset_at: float | None) -> str:
    if not reset_at:
        return "重置时间未知"
    dt = time.localtime(reset_at)
    now = time.time()
    if reset_at < now:
        return "已到期，待刷新"
    delta = reset_at - now
    if delta < 3600:
        return f"{int(delta // 60)} 分钟后重置"
    if delta < 86400:
        return f"{dt.tm_hour:02d}:{dt.tm_min:02d} 重置"
    return f"{dt.tm_mon}/{dt.tm_mday} 重置"


def fmt_ago(ts: float) -> str:
    delta = max(0, time.time() - ts)
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    return f"{int(delta // 3600)} 小时前"


class RingView(QWidget):
    """单个进度环：环形 + 中心百分比 + 下方标题。"""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._percent: float | None = None
        self._center = "--"
        self.setMinimumSize(84, 108)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._canvas = _RingCanvas(self)
        self._label = QLabel(title)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self._canvas, 1)
        layout.addWidget(self._label)

    def set_window(self, w: UsageWindow | None) -> None:
        if w is None or w.percent is None:
            self._canvas.set_data(None, "N/A")
        else:
            self._canvas.set_data(w.percent, f"{w.percent:.0f}%")


class _RingCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._percent: float | None = None
        self._center = "--"

    def set_data(self, percent: float | None, center: str) -> None:
        self._percent = percent
        self._center = center
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        side = min(self.width(), self.height())
        pen = 6.0
        from PySide6.QtCore import QRectF
        rect = QRectF((self.width() - side) / 2 + pen, (self.height() - side) / 2 + pen,
                      side - 2 * pen, side - 2 * pen)
        draw_ring(painter, rect, self._percent, pen_width=pen, center_text=self._center)
        painter.end()


class AccountCard(QFrame):
    refreshRequested = Signal(str)  # account_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "AccountCard { background: #2b2b2b; border-radius: 8px; }"
            "QLabel { color: #e8e8e8; }"
        )
        self._account_id = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)

        header = QHBoxLayout()
        self._title = QLabel("账号")
        self._title.setStyleSheet("font-weight: bold; font-size: 14px;")
        self._status = QLabel("")
        self._status.setStyleSheet("color: #999; font-size: 12px;")
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setFixedWidth(56)
        self._refresh_btn.clicked.connect(lambda: self.refreshRequested.emit(self._account_id))
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._status)
        header.addWidget(self._refresh_btn)
        root.addLayout(header)

        rings = QHBoxLayout()
        self._rings: dict[WindowType, RingView] = {}
        for wt in WINDOW_ORDER:
            rv = RingView(WINDOW_LABELS[wt])
            self._rings[wt] = rv
            rings.addWidget(rv)
        root.addLayout(rings)

        self._reset = QLabel("")
        self._reset.setStyleSheet("color: #999; font-size: 12px;")
        root.addWidget(self._reset)

    def set_result(self, result: AccountResult) -> None:
        self._account_id = result.account_id
        provider_label = PROVIDER_LABELS.get(result.provider, result.provider)
        self._title.setText(f"{result.account_name} · {provider_label}")
        if result.has_data:
            snap = result.snapshot
            for wt in WINDOW_ORDER:
                self._rings[wt].set_window(snap.window(wt))
            resets = "　".join(
                f"{WINDOW_LABELS[wt]}: {fmt_reset((snap.window(wt) or UsageWindow(wt)).reset_at)}"
                for wt in WINDOW_ORDER
                if snap.window(wt) is not None
            )
            self._reset.setText(resets)
            if result.error_kind is not None:
                # 有旧数据但最新一次刷新失败
                self._status.setText(f"刷新失败（显示 {fmt_ago(result.snapshot.fetched_at)} 数据）")
                self._status.setStyleSheet("color: #ff9800; font-size: 12px;")
                self._reset.setText(result.error_msg + ("　" + resets if resets else ""))
            else:
                self._status.setText(f"更新于 {fmt_ago(result.updated_at)}")
                self._status.setStyleSheet("color: #999; font-size: 12px;")
        else:
            for rv in self._rings.values():
                rv.set_window(None)
            self._reset.setText(result.error_msg)
            self._status.setText("查询失败")
            self._status.setStyleSheet("color: #f44336; font-size: 12px;")


class UsagePanel(QWidget):
    """托盘弹出的详情面板（无边框，可拖拽，失焦自动隐藏）。"""

    refreshAllRequested = Signal()
    refreshAccountRequested = Signal(str)
    settingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet("UsagePanel { background: #222; }")
        self.setMinimumWidth(400)
        self._drag_start = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        title = QLabel("Coding Plan 用量")
        title.setStyleSheet("color: #e8e8e8; font-weight: bold; font-size: 15px;")
        refresh_all = QPushButton("全部刷新")
        refresh_all.clicked.connect(self.refreshAllRequested)
        settings_btn = QPushButton("设置")
        settings_btn.clicked.connect(self.settingsRequested)
        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(32)
        close_btn.setToolTip("关闭")
        close_btn.clicked.connect(self.hide)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(refresh_all)
        top.addWidget(settings_btn)
        top.addWidget(close_btn)
        root.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: #222; border: none; }"
            "QScrollArea > QWidget > QWidget { background: #222; }"
        )
        self._container = QWidget()
        self._container.setStyleSheet("background: #222;")
        self._cards_layout = QVBoxLayout(self._container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self._cards: dict[str, AccountCard] = {}
        self._empty_label = QLabel("还没有配置账号，点击「设置」添加 API Key")
        self._empty_label.setStyleSheet("color: #999; padding: 30px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cards_layout.insertWidget(0, self._empty_label)
        self.setMaximumHeight(640)

    def update_results(self, results: dict[str, AccountResult]) -> None:
        self._empty_label.setVisible(not results)
        # 移除已消失的账号
        for account_id in list(self._cards):
            if account_id not in results:
                self._cards.pop(account_id).deleteLater()
        for account_id, result in results.items():
            card = self._cards.get(account_id)
            if card is None:
                card = AccountCard()
                card.refreshRequested.connect(self.refreshAccountRequested)
                self._cards[account_id] = card
                self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            card.set_result(result)
        self.adjustSize()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.adjustSize()

    # ---- 拖拽移动 ----

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._drag_start is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_start)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        self._drag_start = None
        super().mouseReleaseEvent(e)

    # ---- 失焦自动隐藏 ----

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.WindowDeactivate:
            self.hide()
        return super().event(e)
