"""Documento: importación (selección o arrastre), compatibilidad y estructura detectada."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QGridLayout, QHeaderView, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.core.document_analyzer import DocumentStructure, Element, kind_label
from app.core.document_loader import FileInfo
from app.core.exceptions import DocException, ExceptionSet
from app.ui.exception_dialog import ExceptionDialog
from app.ui.widgets import Badge, Banner, DropZone, MetricTile, card, clear_layout, hbox, label, page_header, scroll_page

COLUMNS = ["#", "Pág.", "Tipo de elemento", "Estilo de Word", "Contenido", "Excepción"]


class ImportPage(QWidget):
    fileChosen = Signal(str)
    browseRequested = Signal()
    continueRequested = Signal()
    exceptionsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.exceptions = ExceptionSet()
        self.selection_getter = lambda: None
        layout = scroll_page(self)
        layout.addWidget(page_header("Documento", "Importe un archivo para identificar su formato y analizar su estructura."))

        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self.fileChosen)
        self.drop_zone.clicked.connect(self.browseRequested)
        layout.addWidget(self.drop_zone)

        self.banner = Banner()
        layout.addWidget(self.banner)

        self.info_card, info_layout = card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        self.fields = {}
        for i, (key, caption) in enumerate((("nombre", "Nombre"), ("formato", "Formato detectado"),
                                           ("tamano", "Tamaño"), ("ubicacion", "Ubicación"))):
            grid.addWidget(label(caption, "fieldLabel"), (i // 2) * 2, i % 2)
            value = label("", "fieldValue", wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(value, (i // 2) * 2 + 1, i % 2)
            self.fields[key] = value
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.compat_badge = Badge("")
        self.compat_text = label("", "muted", wrap=True)
        info_layout.addLayout(hbox(label("Archivo", "sectionTitle"), None, self.compat_badge))
        info_layout.addLayout(grid)
        info_layout.addWidget(self.compat_text)
        self.info_card.hide()
        layout.addWidget(self.info_card)

        self.structure_widget = QWidget()
        structure_layout = QVBoxLayout(self.structure_widget)
        structure_layout.setContentsMargins(0, 0, 0, 0)
        structure_layout.setSpacing(14)
        structure_layout.addWidget(label("Estructura detectada", "sectionTitle"))
        self.metrics_grid = QGridLayout()
        self.metrics_grid.setSpacing(12)
        structure_layout.addLayout(self.metrics_grid)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(340)
        header = self.table.horizontalHeader()
        for column in range(len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        structure_layout.addWidget(self.table)

        # ---- excepciones
        exceptions_card, exceptions_layout = card()
        exceptions_layout.addWidget(label("Excepciones", "sectionTitle"))
        self.exceptions_hint = label("", "muted", wrap=True)
        exceptions_layout.addWidget(self.exceptions_hint)
        self.exclude_selected = QPushButton("Excluir selección…")
        self.exclude_section = QPushButton("Excluir sección del encabezado…")
        self.exclude_kind = QPushButton("Excluir todo este tipo…")
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setPrefix("Página ")
        self.exclude_page = QPushButton("Excluir página…")
        self.exclude_selected.clicked.connect(self._add_selected)
        self.exclude_section.clicked.connect(self._add_section)
        self.exclude_kind.clicked.connect(self._add_kind)
        self.exclude_page.clicked.connect(self._add_page)
        exceptions_layout.addLayout(hbox(self.exclude_selected, self.exclude_section, self.exclude_kind, None,
                                         self.page_spin, self.exclude_page))
        self.exception_list = QListWidget()
        self.exception_list.setMinimumHeight(90)
        self.exception_list.setWordWrap(True)
        self.exception_list.itemSelectionChanged.connect(self._update_buttons)
        self.remove_exception = QPushButton("Quitar excepción")
        self.remove_exception.clicked.connect(self._remove)
        exceptions_layout.addWidget(self.exception_list)
        exceptions_layout.addLayout(hbox(None, self.remove_exception))
        structure_layout.addWidget(exceptions_card)

        structure_layout.addWidget(label("Elementos que se conservan sin modificar", "sectionTitle"))
        self.preserved = QListWidget()
        self.preserved.setWordWrap(True)
        self.preserved.setMinimumHeight(120)
        structure_layout.addWidget(self.preserved)

        self.continue_button = QPushButton("Configurar normativa  →")
        self.continue_button.setProperty("variant", "primary")
        self.continue_button.clicked.connect(self.continueRequested)
        structure_layout.addLayout(hbox(None, self.continue_button))
        self.structure_widget.hide()
        layout.addWidget(self.structure_widget)
        layout.addStretch(1)

    def show_error(self, message: str) -> None:
        self.banner.show_message(message, "error")

    def show_file_info(self, info: FileInfo) -> None:
        self.banner.hide()
        self.structure_widget.hide()
        self.fields["nombre"].setText(info.nombre)
        self.fields["formato"].setText(f"{info.formato}  ({info.extension})")
        self.fields["tamano"].setText(info.tamano_legible)
        self.fields["ubicacion"].setText(str(info.carpeta))
        self.compat_badge.setText("Compatible" if info.soportado else "No compatible")
        self.compat_badge.set_variant("success" if info.soportado else "danger")
        self.compat_text.setText(info.mensaje)
        self.info_card.show()

    def set_context(self, exceptions: ExceptionSet, selection_getter) -> None:
        """Excepciones del documento actual y acceso a la selección de reglas vigente."""
        self.exceptions = exceptions
        self.selection_getter = selection_getter

    def show_structure(self, structure: DocumentStructure) -> None:
        self.structure = structure
        clear_layout(self.metrics_grid)
        for i, (caption, value) in enumerate(structure.resumen.items()):
            tile = MetricTile(caption)
            tile.set_value(value, "accent" if value else "")
            self.metrics_grid.addWidget(tile, i // 5, i % 5)

        self.table.setRowCount(len(structure.elements))
        for row, element in enumerate(structure.elements):
            preview = " ".join(element.text.split())
            first, last = element.paginas
            pages = str(first) if first == last else f"{first}–{last}"
            values = (str(element.index), pages, kind_label(element.kind), element.style, preview[:200], "")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setToolTip(preview[:1000])
                self.table.setItem(row, column, item)

        self.page_spin.setMaximum(structure.total_paginas)
        self.exceptions_hint.setText(
            "Seleccione filas de la tabla para que no se modifiquen, con ninguna regla o solo con algunas. Las excepciones "
            f"tienen prioridad sobre las reglas. Las páginas se estiman {structure.paginacion}.")
        self.preserved.clear()
        self.preserved.addItems(structure.conservados)
        self.refresh_exceptions()
        self.structure_widget.show()

    # ------------------------------------------------------------------ excepciones
    def _selected_elements(self) -> list[Element]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return [self.structure.elements[row] for row in rows]

    def _update_buttons(self) -> None:
        selected = self._selected_elements() if hasattr(self, "structure") else []
        self.exclude_selected.setEnabled(bool(selected))
        self.exclude_section.setEnabled(len(selected) == 1 and selected[0].is_heading)
        self.exclude_kind.setEnabled(len(selected) == 1)
        self.remove_exception.setEnabled(bool(self.exception_list.selectedItems()))

    def _create(self, tipo: str, valor, title: str) -> None:
        exception = DocException(tipo, valor)
        affected = self.exceptions.elements_of(exception, self.structure)
        if not affected:
            QMessageBox.information(self, "Nueva excepción", "La excepción no afectaría a ningún elemento.")
            return
        dialog = ExceptionDialog(self, title, affected, list(self.selection_getter().standard.reglas))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.exceptions.add(DocException(tipo, valor, dialog.chosen_rules()))
        self.refresh_exceptions()
        self.exceptionsChanged.emit()

    def _add_selected(self) -> None:
        selected = self._selected_elements()
        title = selected[0].label if len(selected) == 1 else f"{len(selected)} elementos seleccionados"
        self._create("elemento", tuple(e.index for e in selected), f"Excluir: {title}")

    def _add_section(self) -> None:
        heading = self._selected_elements()[0]
        self._create("seccion", heading.index, f"Excluir la sección bajo {heading.label}")

    def _add_kind(self) -> None:
        kind = self._selected_elements()[0].kind
        self._create("tipo", kind, f"Excluir todos los elementos de tipo «{kind_label(kind)}»")

    def _add_page(self) -> None:
        page = self.page_spin.value()
        self._create("pagina", page, f"Excluir la página {page} (estimada {self.structure.paginacion})")

    def _remove(self) -> None:
        for item in self.exception_list.selectedItems():
            self.exceptions.remove(item.data(Qt.ItemDataRole.UserRole))
        self.refresh_exceptions()
        self.exceptionsChanged.emit()

    def refresh_exceptions(self) -> None:
        selection = self.selection_getter()
        self.exception_list.clear()
        marks: dict[int, list[str]] = {}
        for exception in self.exceptions.items:
            affected = self.exceptions.elements_of(exception, self.structure)
            rules = self.exceptions.rules_text(exception, selection)
            item = QListWidgetItem(f"{self.exceptions.describe(exception, self.structure)}  ·  {rules}  ·  "
                                   f"{len(affected)} elemento(s)")
            item.setData(Qt.ItemDataRole.UserRole, exception.id)
            self.exception_list.addItem(item)
            for element in affected:
                marks.setdefault(element.index, []).append(
                    "todas las reglas" if not exception.reglas else f"{len(exception.reglas)} regla(s)")
        if not self.exceptions.items:
            self.exception_list.addItem(QListWidgetItem("Sin excepciones: se aplicarán todas las reglas activas."))
        for row, element in enumerate(self.structure.elements):
            text = "Excluido: " + ", ".join(dict.fromkeys(marks[element.index])) if element.index in marks else ""
            self.table.item(row, 5).setText(text)
        self._update_buttons()
