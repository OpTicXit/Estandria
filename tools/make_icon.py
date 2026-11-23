"""Genera assets/icons/app.ico a partir de logo.svg (se ejecuta solo si cambia el logotipo)."""
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

icons = Path(__file__).resolve().parent.parent / "assets" / "icons"
app = QGuiApplication(sys.argv)
image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
QSvgRenderer(str(icons / "logo.svg")).render(painter)
painter.end()
if not image.save(str(icons / "app.ico")):
    sys.exit("No se pudo escribir app.ico")
print(icons / "app.ico")
