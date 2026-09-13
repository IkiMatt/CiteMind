"""
drop_overlay.py — Full-window drop zone overlay for drag-and-drop import.

Shows a translucent overlay with animated icon when files are dragged over.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPainter, QFont


class DropOverlayWidget(QWidget):
    """
    Full-window semi-transparent overlay shown during drag-and-drop.

    Usage:
        overlay = DropOverlayWidget(parent=main_window)
        overlay.show_overlay()
        overlay.hide_overlay()
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setVisible(False)

        self._opacity = 0.0
        self._anim: QPropertyAnimation | None = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(60, 60, 60, 60)

        # Drop icon
        self._icon_label = QLabel("📥")
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 64px; background: transparent;")
        layout.addWidget(self._icon_label)

        # Title
        self._title = QLabel("Drop files here")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #a78bfa; "
            "background: transparent; margin-top: 12px;"
        )
        layout.addWidget(self._title)

        # Subtitle
        self._subtitle = QLabel("PDF · BibTeX · RIS · DOI · URL")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setStyleSheet(
            "font-size: 13px; color: #8888a8; background: transparent; margin-top: 4px;"
        )
        layout.addWidget(self._subtitle)

    def paintEvent(self, event):
        """Draw semi-transparent background with dashed border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Background
        bg = QColor(124, 58, 237, int(30 * self._opacity))  # violet with opacity
        painter.fillRect(self.rect(), bg)

        # Dashed border
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPen
        pen = QPen(QColor(124, 58, 237, int(180 * self._opacity)))
        pen.setWidth(3)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        rect = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        painter.drawRoundedRect(rect, 16, 16)

        painter.end()

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, val: float):
        self._opacity = val
        opacity_int = int(val * 255)
        self._icon_label.setStyleSheet(
            f"font-size: 64px; background: transparent; color: rgba(167, 139, 250, {opacity_int});"
        )
        self._title.setStyleSheet(
            f"font-size: 22px; font-weight: 700; background: transparent; "
            f"color: rgba(167, 139, 250, {opacity_int}); margin-top: 12px;"
        )
        self._subtitle.setStyleSheet(
            f"font-size: 13px; background: transparent; "
            f"color: rgba(136, 136, 168, {opacity_int}); margin-top: 4px;"
        )
        self.update()

    overlayOpacity = Property(float, _get_opacity, _set_opacity)

    def show_overlay(self):
        """Fade in the overlay."""
        self.setGeometry(self.parent().rect() if self.parent() else self.rect())
        self.setVisible(True)
        self.raise_()

        if self._anim:
            self._anim.stop()

        self._anim = QPropertyAnimation(self, b"overlayOpacity")
        self._anim.setDuration(200)
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def hide_overlay(self):
        """Fade out and hide the overlay."""
        if self._anim:
            self._anim.stop()

        self._anim = QPropertyAnimation(self, b"overlayOpacity")
        self._anim.setDuration(150)
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InCubic)
        self._anim.finished.connect(lambda: self.setVisible(False))
        self._anim.start()

    def resizeEvent(self, event):
        """Keep overlay sized to parent."""
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().resizeEvent(event)
