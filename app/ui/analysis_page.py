"""Análisis: qué reglas ya se cumplen, cuáles requieren cambios y qué se conserva."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QListWidget, QPushButton, QWidget

from app.core.document_analyzer import DocumentStructure
from app.core.document_validator import ValidationReport
from app.ui.report_views import fill_compliance_tree, make_tree
from app.ui.widgets import Banner, MetricTile, hbox, label, page_header, scroll_page


class AnalysisPage(QWidget):
    backRequested = Signal()
    applyRequested = Signal()
    previewRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        layout = scroll_page(self)
        layout.addWidget(page_header(
            "Análisis de cumplimiento",
            "Resultado de comparar cada elemento del documento con las reglas activas. Todavía no se ha modificado nada."))

        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles = {}
        for i, (key, caption) in enumerate((("evaluadas", "Reglas activas evaluadas"), ("cumple", "Ya se cumplen"),
                                           ("requiere", "Requieren cambios"), ("indeterminado", "Sin determinar"),
                                           ("elementos", "Elementos a corregir"), ("revisar", "Para revisar a mano"))):
            self.tiles[key] = MetricTile(caption)
            grid.addWidget(self.tiles[key], 0, i)
        layout.addLayout(grid)

        self.warnings = Banner()
        layout.addWidget(self.warnings)

        layout.addWidget(label("Reglas y elementos afectados", "sectionTitle"))
        self.tree = make_tree(["Regla / elemento", "Estado", "Valor actual", "Valor esperado"], 380)
        layout.addWidget(self.tree)

        layout.addWidget(label("Reglas desactivadas (no se aplicarán)", "sectionTitle"))
        self.inactive = QListWidget()
        self.inactive.setMinimumHeight(80)
        layout.addWidget(self.inactive)

        layout.addWidget(label("Elementos que se conservan sin analizar ni modificar", "sectionTitle"))
        self.preserved = QListWidget()
        self.preserved.setWordWrap(True)
        self.preserved.setMinimumHeight(110)
        layout.addWidget(self.preserved)

        back = QPushButton("←  Ajustar reglas")
        back.clicked.connect(self.backRequested)
        self.apply_button = QPushButton("Aplicar cambios y exportar…")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.clicked.connect(self.applyRequested)
        preview = QPushButton("Vista previa")
        preview.clicked.connect(self.previewRequested)
        layout.addLayout(hbox(back, None, label("Se creará un archivo nuevo; el original no se modifica.", "muted"),
                              preview, self.apply_button))
        layout.addStretch(1)

    def show_report(self, report: ValidationReport, structure: DocumentStructure, warnings: list[tuple[str, str]]) -> None:
        self.tiles["evaluadas"].set_value(len(report.reglas), "accent")
        self.tiles["cumple"].set_value(report.count("cumple"), "success")
        self.tiles["requiere"].set_value(report.count("requiere_cambios"), "warning" if report.count("requiere_cambios") else "success")
        self.tiles["indeterminado"].set_value(report.count("indeterminado"))
        self.tiles["elementos"].set_value(report.elementos_a_modificar, "warning" if report.elementos_a_modificar else "success")
        self.tiles["revisar"].set_value(report.elementos_a_revisar, "accent" if report.elementos_a_revisar else "success")
        if warnings:
            severe = any(level == "advertencia" for level, _ in warnings)
            self.warnings.show_message("Personalización y excepciones respecto a la normativa:\n" + "\n".join(f"• {t}" for _, t in warnings),
                                       "warning" if severe else "info")
        else:
            self.warnings.hide()
        fill_compliance_tree(self.tree, report)
        self.inactive.clear()
        self.inactive.addItems([f"{r.nombre}  ·  {r.clasificacion}" for r in report.inactivas] or ["Ninguna"])
        self.preserved.clear()
        self.preserved.addItems(structure.conservados)
