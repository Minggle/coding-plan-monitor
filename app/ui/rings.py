"""圆圈进度环绘制工具：托盘图标、详情面板、悬浮窄条共用。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

COLOR_OK = QColor("#4caf50")       # 绿
COLOR_WARN = QColor("#ff9800")     # 黄
COLOR_DANGER = QColor("#f44336")   # 红
COLOR_ERROR = QColor("#9e9e9e")    # 灰（查询失败/过期）
COLOR_TRACK = QColor("#3a3a3a")
COLOR_TEXT = QColor("#e8e8e8")


def percent_color(percent: float | None) -> QColor:
    if percent is None:
        return COLOR_ERROR
    if percent < 60:
        return COLOR_OK
    if percent < 85:
        return COLOR_WARN
    return COLOR_DANGER


def draw_ring(
    painter: QPainter,
    rect: QRectF,
    percent: float | None,
    *,
    track_color: QColor = COLOR_TRACK,
    color: QColor | None = None,
    pen_width: float = 4.0,
    center_text: str | None = None,
    text_color: QColor = COLOR_TEXT,
    font: QFont | None = None,
) -> None:
    """在 rect 内画一个进度环。percent=None 画灰圈（数据不可用）。"""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = color or percent_color(percent)

    pen = QPen(track_color, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect)

    if percent is not None:
        pen.setColor(color)
        painter.setPen(pen)
        # 从 12 点方向顺时针
        span = int(-percent / 100.0 * 360 * 16)
        painter.drawArc(rect, 90 * 16, span)

    if center_text is not None:
        painter.setPen(text_color)
        f = font or painter.font()
        painter.setFont(f)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, center_text)


def make_app_icon(size: int = 32, *, error_badge: bool = False) -> QIcon:
    """静态应用图标（托盘用，不带进度）。error_badge=True 时右下角画橙色警告点。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 圆形底 + 字母 C
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#3569d4"))
    painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setPixelSize(int(size * 0.55))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "C")
    if error_badge:
        r = size / 4.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(COLOR_WARN)
        painter.drawEllipse(QRectF(size - r - 1, size - r - 1, r, r))
    painter.end()
    return QIcon(pixmap)


def make_ring_icon(percent: float | None, size: int = 32, *, error_badge: bool = False) -> QIcon:
    """生成托盘用单进度环图标。error_badge=True 时右下角画橙色警告点。"""
    return make_double_ring_icon(percent, None, size, error_badge=error_badge)


def make_double_ring_icon(
    percent_outer: float | None,
    percent_inner: float | None,
    size: int = 32,
    *,
    error_badge: bool = False,
) -> QIcon:
    """双环图标：外环 percent_outer（5h），内环 percent_inner（7d）。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)

    pen_w = max(2.2, size / 11)
    gap = max(1.2, size / 22)
    margin = pen_w / 2 + 1

    outer_rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    draw_ring(painter, outer_rect, percent_outer, pen_width=pen_w)

    inset = pen_w + gap
    inner_rect = QRectF(margin + inset, margin + inset,
                        size - 2 * margin - 2 * inset, size - 2 * margin - 2 * inset)
    if inner_rect.width() > pen_w:
        draw_ring(painter, inner_rect, percent_inner, pen_width=pen_w)

    if error_badge:
        r = size / 4.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(COLOR_WARN)
        painter.drawEllipse(QRectF(size - r - 1, size - r - 1, r, r))
    painter.end()
    return QIcon(pixmap)


class RingWidgetMixin:
    """给面板/窄条里的环形控件复用的绘制逻辑（percent + 中心文字）。"""

    def _paint_ring(self, painter: QPainter, w: int, h: int, percent: float | None,
                    center_text: str, pen_width: float) -> None:
        side = min(w, h)
        margin = pen_width / 2 + 1
        rect = QRectF((w - side) / 2 + margin, (h - side) / 2 + margin,
                      side - 2 * margin, side - 2 * margin)
        draw_ring(painter, rect, percent, pen_width=pen_width, center_text=center_text)
