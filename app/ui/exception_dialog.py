"""Diálogo para crear una excepción: de todas las reglas o solo de algunas."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QMessageBox, QRadioButton, QVBoxLayout,
)

from app.core.document_analyzer import Element
from app.core.rule_engine import Rule
from app.formats.docx_operations import OPERATIONS, SECCION
from app.ui.widgets import label


class ExceptionDialog(QDialog):
    def __init__(self, parent, title: str, affected: list[Element], rules: list[Rule]):
        super().__init__(parent)
        self.setWindowTitle("Nueva excepción")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)
        layout.addWidget(label(title, "sectionTitle", wrap=True))
        preview = ", ".join(f"#{e.index}" for e in affected[:12]) + ("…" if len(affected) > 12 else "")
        layout.addWidget(label(f"Afecta a {len(affected)} elemento(s): {preview}", "muted", wrap=True))

        kinds = {e.kind for e in affected}
        applicable = [r for r in rules if OPERATIONS[r.tipo].nivel != SECCION and kinds & set(r.alcance)]
        self.all_rules = QRadioButton("No modificarlos con ninguna regla")
        self.some_rules = QRadioButton("Conservar solo algunos formatos: no aplicarles estas reglas")
        group = QButtonGroup(self)
        group.addButton(self.all_rules)
        group.addButton(self.some_rules)
        self.all_rules.setChecked(True)
        layout.addWidget(self.all_rules)
        layout.addWidget(self.some_rules)

        self.rule_list = QListWidget()
        self.rule_list.setMinimumHeight(200)
        for rule in applicable:
            item = QListWidgetItem(f"{rule.nombre}  ·  {rule.clasificacion}")
            item.setData(Qt.ItemDataRole.UserRole, rule.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.rule_list.addItem(item)
        self.rule_list.setEnabled(False)
        self.some_rules.toggled.connect(self.rule_list.setEnabled)
        if not applicable:
            self.some_rules.setEnabled(False)
            layout.addWidget(label("Ninguna regla de la normativa actúa sobre estos elementos.", "muted"))
        layout.addWidget(self.rule_list)
        layout.addWidget(label("Las reglas de página (papel, márgenes, número de página) se aplican por sección y no "
                               "admiten excepciones por elemento.", "muted", wrap=True))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crear excepción")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("variant", "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen_rules(self) -> tuple[str, ...]:
        """Reglas elegidas; vacío significa todas."""
        if self.all_rules.isChecked():
            return ()
        return tuple(self.rule_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.rule_list.count())
                     if self.rule_list.item(i).checkState() == Qt.CheckState.Checked)

    def _accept(self) -> None:
        if self.some_rules.isChecked() and not self.chosen_rules():
            QMessageBox.information(self, "Nueva excepción", "Marque al menos una regla o elija «No modificarlos con ninguna regla».")
            return
        self.accept()
