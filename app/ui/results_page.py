"""Resultados: cambios aplicados, omitidos, avisos, integridad y cumplimiento del archivo exportado."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QGridLayout, QListWidget, QListWidgetItem, QPushButton, QTreeWidgetItem, QWidget

from app.core.document_processor import ProcessResult
from app.ui.report_views import MAX_CHILDREN, fill_compliance_tree, make_tree
from app.ui.theme import COLORS
from app.ui.widgets import Banner, MetricTile, hbox, label, page_header, scroll_page


class ResultsPage(QWidget):
    openFileRequested = Signal()
    openFolderRequested = Signal()
    newDocumentRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        layout = scroll_page(self)
        layout.addWidget(page_header("Resultados", "Lo que se aplicó, lo que se omitió y la verificación del archivo exportado."))

        self.banner = Banner()
        layout.addWidget(self.banner)
        open_file = QPushButton("Abrir documento")
        open_file.setProperty("variant", "primary")
        open_file.clicked.connect(self.openFileRequested)
        open_folder = QPushButton("Mostrar en carpeta")
        open_folder.clicked.connect(self.openFolderRequested)
        new_doc = QPushButton("Procesar otro documento")
        new_doc.clicked.connect(self.newDocumentRequested)
        layout.addLayout(hbox(open_file, open_folder, None, new_doc))

        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles = {}
        for i, (key, caption) in enumerate((("cambios", "Cambios aplicados"), ("ya", "Elementos que ya cumplían"),
                                           ("revisiones", "Para revisar a mano"), ("omitidos", "Reglas omitidas"),
                                           ("advertencias", "Advertencias"), ("errores", "Errores"))):
            self.tiles[key] = MetricTile(caption)
            grid.addWidget(self.tiles[key], 0, i)
        layout.addLayout(grid)

        layout.addWidget(label("Verificación de integridad (original frente a exportado)", "sectionTitle"))
        self.integrity = make_tree(["Comprobación", "Original", "Exportado", "Estado"], 200)
        layout.addWidget(self.integrity)

        layout.addWidget(label("Cumplimiento de las reglas seleccionadas en el archivo exportado", "sectionTitle"))
        self.compliance = make_tree(["Regla / elemento", "Estado", "Valor actual", "Valor esperado"], 300)
        layout.addWidget(self.compliance)

        layout.addWidget(label("Cambios aplicados", "sectionTitle"))
        self.changes = make_tree(["Regla / elemento", "Antes", "Después"], 300)
        layout.addWidget(self.changes)

        layout.addWidget(label("Errores, advertencias, puntos para revisar y omitidos", "sectionTitle"))
        self.messages = QListWidget()
        self.messages.setWordWrap(True)
        self.messages.setMinimumHeight(160)
        layout.addWidget(self.messages)
        layout.addStretch(1)

    def show_result(self, result: ProcessResult) -> None:
        if result.errores:
            self.banner.show_message(f"Se exportó «{result.destino}», pero algunas reglas presentaron errores. Revíselos abajo.", "warning")
        else:
            self.banner.show_message(f"Documento exportado y verificado:\n{result.destino}", "success")
        self.tiles["cambios"].set_value(len(result.cambios), "accent")
        self.tiles["ya"].set_value(result.ya_cumplian, "success")
        self.tiles["revisiones"].set_value(len(result.revisiones), "accent" if result.revisiones else "success")
        self.tiles["omitidos"].set_value(len(result.omitidos))
        self.tiles["advertencias"].set_value(len(result.advertencias), "warning" if result.advertencias else "")
        self.tiles["errores"].set_value(len(result.errores), "danger" if result.errores else "success")

        self.integrity.clear()
        for check in result.integridad:
            item = QTreeWidgetItem([check.nombre, str(check.antes), str(check.despues), "Idéntico" if check.ok else "Diferente"])
            item.setForeground(3, QBrush(QColor(COLORS["success"] if check.ok else COLORS["danger"])))
            self.integrity.addTopLevelItem(item)

        if result.cumplimiento is not None:
            fill_compliance_tree(self.compliance, result.cumplimiento)

        self.changes.clear()
        grouped: dict[str, list] = {}
        for change in result.cambios:
            grouped.setdefault(change.regla, []).append(change)
        for rule_name, changes in grouped.items():
            parent = QTreeWidgetItem([f"{rule_name}  ({len(changes)})", "", ""])
            for change in changes[:MAX_CHILDREN]:
                child = QTreeWidgetItem([change.elemento, change.antes, change.despues])
                for column in range(3):
                    child.setToolTip(column, child.text(column))
                parent.addChild(child)
            if len(changes) > MAX_CHILDREN:
                parent.addChild(QTreeWidgetItem([f"… y {len(changes) - MAX_CHILDREN} más", "", ""]))
            self.changes.addTopLevelItem(parent)

        self.messages.clear()
        for prefix, color, entries in (("Error", COLORS["danger"], result.errores),
                                       ("Advertencia", COLORS["warning"], result.advertencias),
                                       ("Revisar", "#C3A8FF", result.revisiones),
                                       ("Omitido", COLORS["muted"], result.omitidos)):
            for entry in entries:
                item = QListWidgetItem(f"{prefix}: {entry}")
                item.setForeground(QBrush(QColor(color)))
                self.messages.addItem(item)
        if not self.messages.count():
            self.messages.addItem("Sin omisiones, advertencias ni errores.")
