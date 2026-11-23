"""Diálogo de nombre y descripción de un perfil."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout

from app.database.profile_repository import MAX_NAME
from app.ui.widgets import label


class ProfileDialog(QDialog):
    def __init__(self, parent, title: str, nombre: str = "", descripcion: str = "", hint: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(8)
        layout.addWidget(label(title, "sectionTitle"))
        if hint:
            layout.addWidget(label(hint, "muted", wrap=True))
        layout.addWidget(label("Nombre", "fieldLabel"))
        self.name = QLineEdit(nombre)
        self.name.setMaxLength(MAX_NAME)
        self.name.setPlaceholderText("Por ejemplo: APA 7 Profesor")
        layout.addWidget(self.name)
        layout.addWidget(label("Descripción (opcional)", "fieldLabel"))
        self.description = QPlainTextEdit(descripcion)
        self.description.setFixedHeight(80)
        layout.addWidget(self.description)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("variant", "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.name.text().strip(), self.description.toPlainText().strip()

    def _accept(self) -> None:
        if not self.values()[0]:
            QMessageBox.information(self, self.windowTitle(), "Escriba un nombre para el perfil.")
            return
        self.accept()
