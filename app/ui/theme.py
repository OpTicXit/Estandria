"""Tema visual, iconos y utilidades de estilo."""
from __future__ import annotations

import re

from PySide6 import QtSvg  # noqa: F401  — fuerza a PyInstaller a incluir el soporte SVG de los iconos
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from app.paths import assets_dir

COLORS = {
    "bg": "#0B0F14",
    "surface": "#131922",
    "text": "#E6EDF3",
    "muted": "#8B98A9",
    "accent": "#3B7BF6",
    "success": "#4ED37E",
    "warning": "#E9B949",
    "danger": "#FF7B72",
}


SCALES = (100, 115, 130)
animations_enabled = True  # preferencia «animaciones»; la consultan los componentes animados


def apply_theme(app: QApplication, scale: int = 100) -> None:
    """Aplica el tema. «scale» agranda todos los textos (accesibilidad): 100, 115 o 130 %."""
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, COLORS["bg"]), (QPalette.ColorRole.Base, "#0F141B"),
        (QPalette.ColorRole.AlternateBase, "#111821"), (QPalette.ColorRole.Text, COLORS["text"]),
        (QPalette.ColorRole.WindowText, COLORS["text"]), (QPalette.ColorRole.Button, "#1A222D"),
        (QPalette.ColorRole.ButtonText, COLORS["text"]), (QPalette.ColorRole.Highlight, "#16233A"),
        (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.ToolTipBase, "#1A222D"),
        (QPalette.ColorRole.ToolTipText, COLORS["text"]), (QPalette.ColorRole.PlaceholderText, COLORS["muted"]),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    factor = (scale if scale in SCALES else 100) / 100
    app.setFont(QFont("Segoe UI", round(10 * factor)))
    qss = (assets_dir() / "styles" / "dark_tech.qss").read_text(encoding="utf-8")
    if factor != 1:
        qss = re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * factor:.1f}pt", qss)
    app.setStyleSheet(qss)


def icon(name: str) -> QIcon:
    return QIcon(str(assets_dir() / "icons" / f"{name}.svg"))


def repolish(widget: QWidget) -> None:
    """Reaplica la hoja de estilos tras cambiar una propiedad dinámica."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
