"""Componentes visuales reutilizables."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Property, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.ui import theme
from app.ui.theme import icon, repolish


class ToggleSwitch(QAbstractButton):
    """Interruptor animado, accesible con teclado (Espacio)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(42, 24)
        self._position = 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _get_position(self) -> float:
        return self._position

    def _set_position(self, value: float) -> None:
        self._position = value
        self.update()

    position = Property(float, _get_position, _set_position)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (API de Qt)
        super().setChecked(checked)
        if self._animation.state() != QPropertyAnimation.State.Running:
            self._set_position(1.0 if checked else 0.0)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        if not theme.animations_enabled:
            self._set_position(1.0 if checked else 0.0)
            return
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(42, 24)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off, on = QColor("#2A3441"), QColor("#3B7BF6")
        p = self._position
        track = QColor(
            int(off.red() + (on.red() - off.red()) * p),
            int(off.green() + (on.green() - off.green()) * p),
            int(off.blue() + (on.blue() - off.blue()) * p),
        )
        if not self.isEnabled():
            track.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#8DB8FF"), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        diameter = rect.height() - 6
        x = rect.left() + 3 + p * (rect.width() - diameter - 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF" if self.isEnabled() else "#6B7684"))
        painter.drawEllipse(QRectF(x, rect.top() + 3, diameter, diameter))


class NoWheelComboBox(QComboBox):
    """No cambia de valor al desplazar la página con la rueda del ratón."""

    def wheelEvent(self, event):  # noqa: N802
        event.ignore() if not self.hasFocus() else super().wheelEvent(event)


class NoWheelSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):  # noqa: N802
        event.ignore() if not self.hasFocus() else super().wheelEvent(event)


class Badge(QLabel):
    def __init__(self, text: str, variant: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        self.setProperty("variant", variant)
        repolish(self)


class Banner(QLabel):
    """Aviso en línea (información, advertencia, error o éxito)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hide()

    def show_message(self, text: str, variant: str = "info") -> None:
        self.setText(text)
        self.setProperty("variant", variant)
        repolish(self)
        self.setVisible(bool(text))


class MetricTile(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        caption.setWordWrap(True)
        layout.addWidget(self.value)
        layout.addWidget(caption)

    def set_value(self, value, variant: str = "") -> None:
        self.value.setText(str(value))
        self.value.setProperty("variant", variant)
        repolish(self.value)


class DropZone(QFrame):
    """Zona para soltar un archivo o hacer clic y elegirlo."""

    fileDropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Seleccionar o soltar un documento")
        self.setMinimumHeight(170)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(icon("upload").pixmap(QSize(40, 40)))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Arrastre aquí su documento")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("o haga clic para seleccionarlo  ·  DOCX (también identifica DOC, ODT y RTF)")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for widget in (glyph, title, hint):
            layout.addWidget(widget)

    def _set_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        repolish(self)

    def dragEnterEvent(self, event):  # noqa: N802
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()
            self._set_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_active(False)

    def dropEvent(self, event):  # noqa: N802
        self._set_active(False)
        self.fileDropped.emit(event.mimeData().urls()[0].toLocalFile())

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


def card(parent=None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    return frame, layout


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    return line


def label(text: str, object_name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


def page_header(title: str, subtitle: str) -> QWidget:
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(label(title, "pageTitle"))
    layout.addWidget(label(subtitle, "pageSubtitle", wrap=True))
    return header


def scroll_page(parent: QWidget) -> QVBoxLayout:
    """Convierte la página en desplazable y devuelve el layout de su contenido."""
    outer = QVBoxLayout(parent)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    content = QWidget()
    content.setObjectName("scrollContent")
    layout = QVBoxLayout(content)
    layout.setContentsMargins(36, 28, 36, 28)
    layout.setSpacing(16)
    scroll.setWidget(content)
    outer.addWidget(scroll)
    return layout


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()  # deleteLater actúa después: sin ocultarlo, se vería duplicado un instante
            item.widget().deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def hbox(*widgets, spacing: int = 10, stretch_end: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            row.addStretch(1)
        else:
            row.addWidget(widget)
    if stretch_end:
        row.addStretch(1)
    return row
