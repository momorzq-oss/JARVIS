"""Original state-driven synthetic-intelligence visualization."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from gui import styles


class AICoreWidget(QWidget):
    """Procedural armored sentinel driven by real assistant state."""

    ACTIVE_ANIMATION_STATES = {
        "wake_detected", "recording", "processing", "transcribing",
        "planning", "executing", "speaking", "waiting_confirmation",
        "recovery",
    }
    ACTIVE_INTERVAL_MS = 33
    PASSIVE_INTERVAL_MS = 500
    REDUCED_MOTION_INTERVAL_MS = 1000

    STATE_COLORS = {
        "idle": styles.CYAN_DIM,
        "ready": styles.CYAN,
        "loading": styles.AMBER,
        "listening_wake": styles.CYAN,
        "wake_detected": styles.CYAN_GLOW,
        "recording": styles.CYAN_GLOW,
        "processing": styles.AMBER,
        "transcribing": styles.AMBER,
        "planning": styles.AMBER,
        "executing": styles.CYAN_GLOW,
        "waiting_confirmation": styles.AMBER,
        "speaking": styles.BLUE_WHITE,
        "error": styles.DANGER,
        "failure": styles.DANGER,
        "failed": styles.DANGER,
        "recovery": styles.AMBER,
        "cancelled": styles.TEXT_DIM,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiCore")
        self.setMinimumSize(320, 290)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._state = "idle"
        self._detail = "Waiting for command"
        self._level = 0.0
        self._phase = 0.0
        self._angle = 0.0
        self._reduce_motion = False
        self._action_nodes = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)

    def set_state(self, state, detail=""):
        self._state = str(state or "idle").lower()
        if detail:
            self._detail = str(detail)
        active = self._state in self.ACTIVE_ANIMATION_STATES
        interval = self.ACTIVE_INTERVAL_MS if active else self.PASSIVE_INTERVAL_MS
        self._timer.setInterval(self.REDUCED_MOTION_INTERVAL_MS if self._reduce_motion else interval)
        self.update()

    def set_reduce_motion(self, enabled):
        self._reduce_motion = bool(enabled)
        self.set_state(self._state)

    def set_level(self, value):
        try:
            self._level = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._level = 0.0
        self.update()

    def trigger_pulse(self):
        self._phase += math.pi / 2
        self.update()

    def set_action_nodes(self, nodes):
        self._action_nodes = [str(node)[:28] for node in (nodes or []) if str(node).strip()][-5:]
        self.update()

    def _tick(self):
        speed = 0.0 if self._reduce_motion else 1.0
        active = self._state in self.ACTIVE_ANIMATION_STATES
        self._phase += (0.12 if active else 0.035) * speed
        self._angle = (self._angle + (1.8 if active else 0.35) * speed) % 360
        if self._state not in {"recording", "listening_wake", "speaking"}:
            self._level *= 0.84
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(styles.BG_DEEP))
        width, height = self.width(), self.height()
        center_x = width / 2
        core_y = height * 0.59
        radius = min(width * 0.275, height * 0.235)
        color = QColor(self.STATE_COLORS.get(self._state, styles.CYAN))

        self._draw_grid(painter, color)
        self._draw_holographic_field(painter, center_x, core_y, radius, color)
        self._draw_armored_torso(painter, center_x, core_y, radius, color)
        self._draw_energy_paths(painter, center_x, core_y, radius, color)
        self._draw_sentinel_head(painter, center_x, height * 0.205, color)
        self._draw_orbital_core(painter, center_x, core_y, radius, color)
        self._draw_action_graph(painter, color)
        self._draw_labels(painter, color)
        painter.end()

    def _draw_grid(self, painter, color):
        grid = QColor(color)
        grid.setAlpha(24)
        painter.setPen(QPen(grid, 1))
        spacing = max(28, self.width() // 18)
        for x in range(0, self.width(), spacing):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), spacing):
            painter.drawLine(0, y, self.width(), y)

    def _draw_holographic_field(self, painter, cx, cy, radius, color):
        painter.setBrush(Qt.NoBrush)
        for index, factor in enumerate((1.42, 1.72, 2.02)):
            field_color = QColor(color)
            field_color.setAlpha(42 - index * 10)
            painter.setPen(QPen(field_color, 1))
            rect = QRectF(
                cx - radius * factor,
                cy - radius * factor * 1.18,
                radius * factor * 2,
                radius * factor * 2.36,
            )
            start = self._angle * (1 if index % 2 else -1)
            for segment in range(4):
                painter.drawArc(
                    rect,
                    int((start + segment * 90 + 12) * 16),
                    int((48 - index * 4) * 16),
                )
        scan = QColor(color)
        scan.setAlpha(28)
        painter.setPen(QPen(scan, 1))
        half_span = min(self.width() * 0.42, radius * 2.12)
        for offset in (-0.92, -0.48, 0.48, 0.92):
            x = cx + half_span * offset
            painter.drawLine(
                QPointF(x, self.height() * 0.27),
                QPointF(cx + half_span * offset * 0.64, self.height() * 0.77),
            )

    def _draw_sentinel_head(self, painter, cx, cy, color):
        scale = min(self.width(), self.height()) / 650.0
        head_w, head_h = 158 * scale, 192 * scale
        neck_top = cy + head_h * 0.42
        neck = QPainterPath()
        neck.moveTo(cx - head_w * 0.23, neck_top)
        neck.lineTo(cx - head_w * 0.35, neck_top + head_h * 0.34)
        neck.lineTo(cx + head_w * 0.35, neck_top + head_h * 0.34)
        neck.lineTo(cx + head_w * 0.23, neck_top)
        neck.closeSubpath()
        neck_fill = QLinearGradient(cx, neck_top, cx, neck_top + head_h * 0.34)
        neck_fill.setColorAt(0, QColor(5, 22, 31, 245))
        neck_fill.setColorAt(1, QColor(1, 8, 13, 250))
        neck_edge = QColor(color)
        neck_edge.setAlpha(92)
        painter.setPen(QPen(neck_edge, max(1.0, scale)))
        painter.setBrush(QBrush(neck_fill))
        painter.drawPath(neck)

        path = QPainterPath()
        path.moveTo(cx, cy - head_h * 0.62)
        path.lineTo(cx - head_w * 0.36, cy - head_h * 0.52)
        path.lineTo(cx - head_w * 0.55, cy - head_h * 0.24)
        path.lineTo(cx - head_w * 0.52, cy + head_h * 0.14)
        path.lineTo(cx - head_w * 0.34, cy + head_h * 0.42)
        path.lineTo(cx - head_w * 0.13, cy + head_h * 0.55)
        path.lineTo(cx + head_w * 0.13, cy + head_h * 0.55)
        path.lineTo(cx + head_w * 0.34, cy + head_h * 0.42)
        path.lineTo(cx + head_w * 0.52, cy + head_h * 0.14)
        path.lineTo(cx + head_w * 0.55, cy - head_h * 0.24)
        path.lineTo(cx + head_w * 0.36, cy - head_h * 0.52)
        path.closeSubpath()
        fill = QLinearGradient(cx, cy - head_h, cx, cy + head_h)
        fill.setColorAt(0, QColor(10, 34, 45, 244))
        fill.setColorAt(0.48, QColor(4, 19, 28, 248))
        fill.setColorAt(1, QColor(1, 7, 12, 252))
        outline = QColor(color)
        outline.setAlpha(215)
        painter.setPen(QPen(outline, max(1.2, 1.8 * scale)))
        painter.setBrush(QBrush(fill))
        painter.drawPath(path)

        panel_edge = QColor(color)
        panel_edge.setAlpha(90)
        painter.setPen(QPen(panel_edge, max(0.8, scale)))
        painter.setBrush(Qt.NoBrush)
        crown = QPolygonF([
            QPointF(cx, cy - head_h * 0.58),
            QPointF(cx - head_w * 0.25, cy - head_h * 0.45),
            QPointF(cx - head_w * 0.13, cy - head_h * 0.10),
            QPointF(cx, cy - head_h * 0.01),
            QPointF(cx + head_w * 0.13, cy - head_h * 0.10),
            QPointF(cx + head_w * 0.25, cy - head_h * 0.45),
        ])
        painter.drawPolygon(crown)
        painter.drawLine(
            QPointF(cx, cy - head_h * 0.58),
            QPointF(cx, cy + head_h * 0.48),
        )
        for direction in (-1, 1):
            cheek = QPolygonF([
                QPointF(cx + direction * head_w * 0.13, cy - head_h * 0.03),
                QPointF(cx + direction * head_w * 0.47, cy - head_h * 0.16),
                QPointF(cx + direction * head_w * 0.38, cy + head_h * 0.29),
                QPointF(cx + direction * head_w * 0.13, cy + head_h * 0.46),
            ])
            painter.drawPolygon(cheek)
            jaw = QPolygonF([
                QPointF(cx + direction * head_w * 0.13, cy + head_h * 0.24),
                QPointF(cx + direction * head_w * 0.34, cy + head_h * 0.40),
                QPointF(cx + direction * head_w * 0.13, cy + head_h * 0.53),
                QPointF(cx, cy + head_h * 0.50),
            ])
            painter.drawPolygon(jaw)

        eye_alpha = 245 if self._state not in {"idle", "cancelled"} else 190
        for direction in (-1, 1):
            eye_x = cx + direction * head_w * 0.27
            eye_y = cy - head_h * 0.02
            glow = QRadialGradient(eye_x, eye_y, head_w * 0.24)
            eye_color = QColor(color)
            eye_color.setAlpha(eye_alpha)
            fade = QColor(color)
            fade.setAlpha(0)
            glow.setColorAt(0, QColor(235, 255, 255, eye_alpha))
            glow.setColorAt(0.32, eye_color)
            glow.setColorAt(1, fade)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(
                QRectF(
                    eye_x - head_w * 0.22,
                    eye_y - head_h * 0.11,
                    head_w * 0.44,
                    head_h * 0.22,
                )
            )
            eye_pen = QPen(eye_color, max(2.0, 4.2 * scale), Qt.SolidLine, Qt.RoundCap)
            painter.setPen(eye_pen)
            painter.drawLine(
                QPointF(cx + direction * head_w * 0.43, eye_y - head_h * 0.025),
                QPointF(cx + direction * head_w * 0.11, eye_y + head_h * 0.035),
            )

    def _draw_armored_torso(self, painter, cx, core_y, radius, color):
        shoulder_y = self.height() * 0.345
        waist_y = self.height() * 0.785
        shoulder_span = min(self.width() * 0.48, radius * 2.35)
        waist_span = min(self.width() * 0.29, radius * 1.25)
        silhouette = QPainterPath()
        silhouette.moveTo(cx - radius * 0.34, shoulder_y - radius * 0.34)
        silhouette.cubicTo(
            cx - shoulder_span * 0.54,
            shoulder_y - radius * 0.20,
            cx - shoulder_span * 0.90,
            shoulder_y + radius * 0.12,
            cx - shoulder_span,
            shoulder_y + radius * 0.44,
        )
        silhouette.lineTo(cx - waist_span, waist_y)
        silhouette.lineTo(cx + waist_span, waist_y)
        silhouette.lineTo(cx + shoulder_span, shoulder_y + radius * 0.44)
        silhouette.cubicTo(
            cx + shoulder_span * 0.90,
            shoulder_y + radius * 0.12,
            cx + shoulder_span * 0.54,
            shoulder_y - radius * 0.20,
            cx + radius * 0.34,
            shoulder_y - radius * 0.34,
        )
        silhouette.closeSubpath()
        body_fill = QLinearGradient(cx, shoulder_y, cx, waist_y)
        body_fill.setColorAt(0, QColor(6, 26, 36, 242))
        body_fill.setColorAt(0.55, QColor(2, 14, 22, 248))
        body_fill.setColorAt(1, QColor(1, 7, 12, 252))
        body_edge = QColor(color)
        body_edge.setAlpha(112)
        painter.setPen(QPen(body_edge, 1.2))
        painter.setBrush(QBrush(body_fill))
        painter.drawPath(silhouette)

        panel_fill = QColor(4, 25, 35, 224)
        panel_edge = QColor(color)
        panel_edge.setAlpha(96)
        for direction in (-1, 1):
            shoulder = [
                (0.28, -0.34),
                (0.63, -0.25),
                (0.96, 0.12),
                (0.78, 0.43),
                (0.42, 0.26),
            ]
            clavicle = [
                (0.12, -0.18),
                (0.47, -0.14),
                (0.67, 0.08),
                (0.32, 0.23),
                (0.08, 0.08),
            ]
            chest = [
                (0.11, 0.10),
                (0.40, 0.24),
                (0.46, 0.59),
                (0.23, 0.78),
                (0.08, 0.52),
            ]
            ribs = [
                (0.43, 0.48),
                (0.70, 0.55),
                (0.57, 0.93),
                (0.28, 1.02),
                (0.20, 0.76),
            ]
            for points in (shoulder, clavicle, chest, ribs):
                polygon = QPolygonF([
                    QPointF(
                        cx + direction * shoulder_span * x,
                        shoulder_y + radius * y,
                    )
                    for x, y in points
                ])
                painter.setPen(QPen(panel_edge, 1))
                painter.setBrush(QBrush(panel_fill))
                painter.drawPolygon(polygon)

        sternum = QPolygonF([
            QPointF(cx, shoulder_y - radius * 0.13),
            QPointF(cx - radius * 0.17, shoulder_y + radius * 0.08),
            QPointF(cx - radius * 0.11, core_y + radius * 0.80),
            QPointF(cx, core_y + radius * 1.04),
            QPointF(cx + radius * 0.11, core_y + radius * 0.80),
            QPointF(cx + radius * 0.17, shoulder_y + radius * 0.08),
        ])
        center_fill = QColor(color)
        center_fill.setAlpha(18)
        center_edge = QColor(color)
        center_edge.setAlpha(112)
        painter.setPen(QPen(center_edge, 1.1))
        painter.setBrush(QBrush(center_fill))
        painter.drawPolygon(sternum)

        seam = QColor(color)
        seam.setAlpha(54)
        painter.setPen(QPen(seam, 1))
        for direction in (-1, 1):
            painter.drawLine(
                QPointF(cx + direction * radius * 0.24, core_y + radius * 0.78),
                QPointF(cx + direction * waist_span * 0.72, waist_y),
            )
            painter.drawLine(
                QPointF(cx + direction * radius * 0.48, core_y + radius * 0.10),
                QPointF(cx + direction * shoulder_span * 0.85, shoulder_y + radius * 0.30),
            )

    def _draw_energy_paths(self, painter, cx, core_y, radius, color):
        active = self._state not in {"idle", "ready", "cancelled"}
        path_color = QColor(color)
        path_color.setAlpha(155 if active else 72)
        painter.setPen(QPen(path_color, 1.3 if active else 1.0))
        targets = (
            QPointF(cx, self.height() * 0.28),
            QPointF(cx - radius * 1.72, self.height() * 0.40),
            QPointF(cx + radius * 1.72, self.height() * 0.40),
            QPointF(cx - radius * 1.36, self.height() * 0.73),
            QPointF(cx + radius * 1.36, self.height() * 0.73),
        )
        origin = QPointF(cx, core_y)
        travel = (math.sin(self._phase) + 1.0) / 2.0
        for index, target in enumerate(targets):
            painter.drawLine(origin, target)
            if active and not self._reduce_motion:
                phase = (travel + index * 0.17) % 1.0
                point = QPointF(
                    origin.x() + (target.x() - origin.x()) * phase,
                    origin.y() + (target.y() - origin.y()) * phase,
                )
                dot = QColor(color)
                dot.setAlpha(230)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(dot))
                painter.drawEllipse(point, 2.6, 2.6)

    def _draw_orbital_core(self, painter, cx, cy, radius, color):
        pulse = 1.0 + (0.025 + self._level * 0.10) * math.sin(self._phase)
        glow_radius = radius * 0.54 * pulse
        gradient = QRadialGradient(cx, cy, glow_radius)
        hot = QColor(color)
        hot.setAlpha(220)
        transparent = QColor(color)
        transparent.setAlpha(0)
        gradient.setColorAt(0, QColor(235, 255, 255, 245))
        gradient.setColorAt(0.18, hot)
        gradient.setColorAt(1, transparent)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QRectF(cx - glow_radius, cy - glow_radius, glow_radius * 2, glow_radius * 2))
        painter.setBrush(Qt.NoBrush)
        for index, factor in enumerate((0.46, 0.63, 0.80, 0.98)):
            ring_color = QColor(color)
            ring_color.setAlpha(210 - index * 35)
            painter.setPen(QPen(ring_color, 2 if index < 2 else 1))
            rect = QRectF(cx - radius * factor, cy - radius * factor,
                          radius * factor * 2, radius * factor * 2)
            offset = self._angle * (-1 if index % 2 else 1)
            span = 80 + index * 18
            for segment in range(3):
                painter.drawArc(rect, int((offset + segment * 120) * 16), int(span * 16))
        spoke_color = QColor(color)
        spoke_color.setAlpha(120)
        painter.setPen(QPen(spoke_color, 1))
        for index in range(16):
            angle = math.tau * index / 16 + math.radians(self._angle * 0.16)
            inner = radius * 0.25
            outer = radius * 0.43
            painter.drawLine(
                QPointF(cx + math.cos(angle) * inner, cy + math.sin(angle) * inner),
                QPointF(cx + math.cos(angle) * outer, cy + math.sin(angle) * outer),
            )
        waveform = QColor(color)
        waveform.setAlpha(200)
        painter.setPen(QPen(waveform, 1.5))
        bars = 56
        for index in range(bars):
            angle = index / bars * math.tau
            base = radius * 0.67
            amplitude = self._level * radius * 0.16 * abs(math.sin(self._phase * 2 + index * 0.45))
            start = QPointF(cx + math.cos(angle) * base, cy + math.sin(angle) * base)
            end = QPointF(cx + math.cos(angle) * (base + 4 + amplitude),
                          cy + math.sin(angle) * (base + 4 + amplitude))
            painter.drawLine(start, end)

    def _draw_action_graph(self, painter, color):
        if not self._action_nodes:
            return
        node_color = QColor(color)
        node_color.setAlpha(150)
        painter.setPen(QPen(node_color, 1))
        usable = self.width() * 0.76
        start_x = (self.width() - usable) / 2
        y = self.height() * 0.965
        step = usable / max(1, len(self._action_nodes) - 1)
        font = QFont("Consolas", 7)
        painter.setFont(font)
        for index, label in enumerate(self._action_nodes):
            x = start_x + index * step
            if index:
                painter.drawLine(QPointF(x - step, y), QPointF(x, y))
            painter.setBrush(QBrush(QColor(styles.BG_PANEL_SOLID)))
            painter.drawEllipse(QPointF(x, y), 4, 4)
            painter.drawText(QRectF(x - 42, y + 7, 84, 25), Qt.AlignHCenter | Qt.AlignTop, label)

    def _draw_labels(self, painter, color):
        painter.setPen(QColor(color))
        state_font = QFont("Consolas", 12, QFont.Bold)
        state_font.setLetterSpacing(QFont.PercentageSpacing, 125)
        painter.setFont(state_font)
        state = self._state.replace("_", " ").upper()
        painter.drawText(QRectF(0, self.height() * 0.845, self.width(), 28), Qt.AlignCenter, state)
        detail_font = QFont("Segoe UI", 8)
        painter.setFont(detail_font)
        detail_color = QColor(styles.TEXT_DIM)
        painter.setPen(detail_color)
        detail = self._detail if self._detail else "Waiting"
        painter.drawText(QRectF(self.width() * 0.12, self.height() * 0.895,
                                self.width() * 0.76, 32),
                         Qt.AlignHCenter | Qt.TextWordWrap, detail[:120])
