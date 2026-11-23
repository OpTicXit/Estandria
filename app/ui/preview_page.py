"""Vista previa: el original y el resultado lado a lado, antes de modificar ningún archivo."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from app.formats.docx_preview import CHANGED_BACKGROUND, EXCLUDED_BACKGROUND
from app.ui.widgets import hbox, label, page_header


@dataclass
class PreviewData:
    html_before: str
    width_before: int
    html_after: str
    width_after: int
    changes: list[tuple[int, str, str]] = field(default_factory=list)  # (índice, elemento, reglas)
    section_changes: list[str] = field(default_factory=list)
    excluded: int = 0


def _chip(text: str, color: str):
    chip = label(f"  {text}  ")
    chip.setStyleSheet(f"background:{color}; color:#1b2330; border-radius:6px; padding:2px 6px; font-size:9pt;")
    return chip


class PreviewPage(QWidget):
    backRequested = Signal()
    applyRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 20)
        layout.setSpacing(12)
        layout.addWidget(page_header(
            "Vista previa",
            "Comparación del formato antes y después de aplicar las reglas y excepciones. Ningún archivo se ha modificado."))
        self.summary = label("", "muted")
        layout.addLayout(hbox(_chip("Modificado", CHANGED_BACKGROUND), _chip("Excluido por excepción", EXCLUDED_BACKGROUND),
                              None, self.summary))

        self.before, self.after = QTextBrowser(), QTextBrowser()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        for title, browser in (("Original", self.before), ("Con las reglas seleccionadas", self.after)):
            browser.setObjectName("paper")
            browser.setOpenLinks(False)
            browser.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
            browser.document().setDocumentMargin(26)
            panel = QFrame()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 6, 0)
            panel_layout.addWidget(label(title, "sectionTitle"))
            panel_layout.addWidget(browser, 1)
            splitter.addWidget(panel)
        layout.addWidget(splitter, 1)
        self._syncing = False
        self.before.verticalScrollBar().valueChanged.connect(lambda v: self._sync(self.before, self.after))
        self.after.verticalScrollBar().valueChanged.connect(lambda v: self._sync(self.after, self.before))

        layout.addWidget(label("Elementos modificados (clic para ubicarlos en ambos paneles)", "sectionTitle"))
        self.changes = QListWidget()
        self.changes.setMaximumHeight(150)
        self.changes.itemClicked.connect(self._locate)
        layout.addWidget(self.changes)
        layout.addWidget(label("Aproximación visual: no reproduce la paginación de Word ni dibuja las imágenes. "
                               "El archivo exportado se verifica por separado.", "muted", wrap=True))

        back = QPushButton("←  Volver al análisis")
        back.clicked.connect(self.backRequested)
        apply_button = QPushButton("Aplicar cambios y exportar…")
        apply_button.setProperty("variant", "primary")
        apply_button.clicked.connect(self.applyRequested)
        layout.addLayout(hbox(back, None, apply_button))

    def show_preview(self, data: PreviewData) -> None:
        for browser, html, width in ((self.before, data.html_before, data.width_before),
                                     (self.after, data.html_after, data.width_after)):
            browser.setLineWrapColumnOrWidth(width)
            browser.setHtml(html)
        summary = f"{len(data.changes)} elemento(s) modificados"
        if data.section_changes:
            summary += f" · {len(data.section_changes)} cambio(s) de página"
        if data.excluded:
            summary += f" · {data.excluded} excluido(s)"
        self.summary.setText(summary)
        self.changes.clear()
        for text in data.section_changes:
            self.changes.addItem(QListWidgetItem(f"Página: {text}"))
        for index, element, rules in data.changes:
            item = QListWidgetItem(f"{element}  —  {rules}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(rules)
            self.changes.addItem(item)

    def _sync(self, source: QTextBrowser, target: QTextBrowser) -> None:
        """Desplazamiento proporcional: el resultado suele ser más largo (doble espacio)."""
        if self._syncing:
            return
        self._syncing = True
        bar, other = source.verticalScrollBar(), target.verticalScrollBar()
        ratio = bar.value() / bar.maximum() if bar.maximum() else 0
        other.setValue(round(ratio * other.maximum()))
        self._syncing = False

    def _locate(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        self._syncing = True
        for browser in (self.before, self.after):
            browser.scrollToAnchor(f"e{index}")
        self._syncing = False
