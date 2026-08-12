"""详情面板：每个账号一张卡片，5h/7d/月度三个进度环 + 重置时间 + 刷新按钮。"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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
    """按日历日区分重置时间：今天只显示时刻，明天加前缀，更远显示月/日+时刻。

    仅按"24 小时内"显示 HH:MM 会把明天的时刻误读成今天已过去的时间。
    """
    if not reset_at:
        return "重置时间未知"
    now = time.time()
    if reset_at < now:
        return "已到期，待刷新"
    delta = reset_at - now
    if delta < 3600:
        return f"{int(delta // 60)} 分钟后重置"
    dt = datetime.fromtimestamp(reset_at)
    hm = dt.strftime("%H:%M")
    days = (dt.date() - datetime.fromtimestamp(now).date()).days
    if days == 0:
        return f"{hm} 重置"
    if days == 1:
        return f"明天 {hm} 重置"
    return f"{dt.month}/{dt.day} {hm} 重置"


def fmt_window_reset(w: UsageWindow) -> str:
    """单个窗口的重置文案；用量 100% 且无重置时间 = 本计费周期已耗尽。"""
    if w.percent is not None and w.percent >= 100 and not w.reset_at:
        return "已耗尽（下个计费周期恢复）"
    return fmt_reset(w.reset_at)


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
            exhausted = snap.monthly_exhausted
            for wt in WINDOW_ORDER:
                w = snap.window(wt)
                if w is not None and exhausted and wt != WindowType.MONTHLY:
                    # 月度耗尽 = 账号整体被锁，5h/7d 环强制标红 100%（仅展示层覆盖）
                    w = replace(w, percent=snap.display_percent(wt))
                self._rings[wt].set_window(w)
            resets = "　".join(
                f"{WINDOW_LABELS[wt]}: {fmt_window_reset(snap.window(wt) or UsageWindow(wt))}"
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
        self._columns = 2
        self._col_width = 300  # 随卡片实际内容增长（只增不减，避免刷新时窗口抖动）
        self._update_min_width()
        self._drag_start = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        self._top_layout = top
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
        self._cards_layout = QGridLayout(self._container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setHorizontalSpacing(8)
        self._cards_layout.setVerticalSpacing(8)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self._cards: dict[str, AccountCard] = {}
        self._empty_label = QLabel("还没有配置账号，点击「设置」添加 API Key")
        self._empty_label.setStyleSheet("color: #999; padding: 30px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout_cards()
        self.setMaximumHeight(640)

    def update_results(self, results: dict[str, AccountResult]) -> None:
        self._empty_label.setVisible(not results)
        structure_changed = False
        # 移除已消失的账号
        for account_id in list(self._cards):
            if account_id not in results:
                self._cards.pop(account_id).deleteLater()
                structure_changed = True
        for account_id, result in results.items():
            card = self._cards.get(account_id)
            if card is None:
                card = AccountCard()
                card.refreshRequested.connect(self.refreshAccountRequested)
                self._cards[account_id] = card
                structure_changed = True
            card.set_result(result)
        if structure_changed:
            self._layout_cards()
        self._update_min_width()
        self._fit_to_content()

    def _fit_to_content(self) -> None:
        """把窗口调整到内容尺寸。

        adjustSize 对含滚动区的窗口高度不可靠（实测 sizeHint 正确但结果偏小），
        直接按 sizeHint resize：宽取内容宽与最小宽较大者，高不超过 maximumHeight。
        """
        hint = self.sizeHint()
        self.resize(max(hint.width(), self.minimumWidth()),
                    min(hint.height(), self.maximumHeight()))

    def set_columns(self, columns: int) -> None:
        """设置详情面板的卡片列数，并重排版面。"""
        columns = max(1, int(columns))
        if columns == self._columns:
            return
        self._columns = columns
        self._update_min_width()
        self._layout_cards()
        self._fit_to_content()

    def _update_min_width(self) -> None:
        # 列宽取卡片实际内容宽度（重置时间文本可能很长），只增不减避免抖动
        cards = getattr(self, "_cards", None)  # 构造期间尚无 _cards
        if cards:
            self._col_width = max(self._col_width,
                                  max(c.sizeHint().width() for c in cards.values()))
        # + 外边距与垂直滚动条预留
        self.setMinimumWidth(self._columns * self._col_width + 40)

    def _layout_cards(self) -> None:
        """按当前列数把卡片重新排入网格。"""
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        if not self._cards:
            self._cards_layout.addWidget(self._empty_label, 0, 0, 1, self._columns)
            return
        ordered = list(self._cards.values())
        for i, card in enumerate(ordered):
            row, col = divmod(i, self._columns)
            self._cards_layout.addWidget(card, row, col)

    def sizeHint(self) -> QSize:
        """尺寸跟随内容：顶部栏 + 卡片网格 + 外边距；高度上限由 maximumHeight 约束。"""
        top = getattr(self, "_top_layout", None)
        container = getattr(self, "_container", None)
        if top is None or container is None:
            return super().sizeHint()
        m = self.layout().contentsMargins()
        content = container.sizeHint()
        w = m.left() + content.width() + m.right()
        h = m.top() + top.sizeHint().height() + self.layout().spacing() + content.height() + m.bottom() + 2
        return QSize(w, h)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_to_content()

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
