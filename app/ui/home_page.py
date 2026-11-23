"""Inicio: acceso a la importación, documentos recientes y normativas disponibles."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from app.core.rule_engine import Standard
from app.ui.theme import icon
from app.ui.widgets import card, label, scroll_page


class HomePage(QWidget):
    importRequested = Signal()
    recentRequested = Signal(str)
    standardRequested = Signal(str)
    profileRequested = Signal(int)
    settingsRequested = Signal()

    def __init__(self, standards: list[Standard], parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        layout = scroll_page(self)

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(32, 30, 32, 30)
        hero_layout.setSpacing(10)
        hero_layout.addWidget(label("Formato normativo automático,\nbajo su control.", "heroTitle"))
        hero_layout.addWidget(label(
            "Importe un documento de Word, elija una normativa, decida regla por regla qué aplicar "
            "y exporte una copia verificada. Todo ocurre en su equipo: sin conexión y sin enviar archivos.",
            "pageSubtitle", wrap=True))
        button = QPushButton("  Importar documento")
        button.setProperty("variant", "primary")
        button.setIcon(icon("upload_white"))
        button.setIconSize(QSize(18, 18))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(42)
        button.clicked.connect(self.importRequested)
        row = QHBoxLayout()
        row.addWidget(button)
        row.addSpacing(14)
        row.addWidget(label("El original nunca se modifica · se guarda un respaldo automático", "muted"))
        row.addStretch(1)
        settings_button = QPushButton("  Configuración")
        settings_button.setIcon(icon("gear"))
        settings_button.setIconSize(QSize(16, 16))
        settings_button.clicked.connect(self.settingsRequested)
        row.addWidget(settings_button)
        hero_layout.addSpacing(6)
        hero_layout.addLayout(row)
        layout.addWidget(hero)

        columns = QHBoxLayout()
        columns.setSpacing(16)

        recent_card, recent_layout = card()
        recent_layout.addWidget(label("Documentos recientes", "sectionTitle"))
        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(220)
        self.recent_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent_list.itemClicked.connect(self._open_recent)
        self.recent_empty = label("Todavía no ha importado documentos.", "muted")
        recent_layout.addWidget(self.recent_list)
        recent_layout.addWidget(self.recent_empty)
        recent_layout.addStretch(1)
        columns.addWidget(recent_card, 3)

        standards_card, standards_layout = card()
        standards_layout.addWidget(label("Normativas disponibles", "sectionTitle"))
        for standard in standards:
            item = QPushButton(f"{standard.nombre}\n{len(standard.reglas)} reglas configurables · {standard.edicion}")
            item.setObjectName("standardCard")
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            item.clicked.connect(lambda _=False, sid=standard.id: self.standardRequested.emit(sid))
            standards_layout.addWidget(item)
        if not standards:
            standards_layout.addWidget(label("No se encontraron catálogos de normativas.", "muted"))
        standards_layout.addWidget(label(
            "ICONTEC, IEEE, Vancouver, MLA, Chicago y el formato personalizado se agregarán como catálogos "
            "nuevos en fases posteriores.", "muted", wrap=True))
        standards_layout.addWidget(label("Perfiles", "sectionTitle"))
        self.profile_list = QListWidget()
        self.profile_list.setMinimumHeight(110)
        self.profile_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_list.itemClicked.connect(
            lambda item: item.data(Qt.ItemDataRole.UserRole) and self.profileRequested.emit(item.data(Qt.ItemDataRole.UserRole)))
        standards_layout.addWidget(self.profile_list)
        standards_layout.addStretch(1)
        columns.addWidget(standards_card, 2)

        layout.addLayout(columns)
        layout.addStretch(1)

    def set_profiles(self, profiles, standard_names: dict[str, str]) -> None:
        self.profile_list.clear()
        for profile in profiles:
            item = QListWidgetItem(f"{profile.nombre}  ·  {standard_names.get(profile.normativa, profile.normativa)}")
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.profile_list.addItem(item)
        if not profiles:
            self.profile_list.addItem(QListWidgetItem("Sin perfiles guardados. Créelos desde Normativa o Configuración."))

    def set_recent(self, paths: list[str]) -> None:
        self.recent_list.clear()
        for path in paths:
            item = QListWidgetItem(icon("file"), f"{Path(path).name}\n{Path(path).parent}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setSizeHint(QSize(0, 48))
            self.recent_list.addItem(item)
        self.recent_list.setVisible(bool(paths))
        self.recent_empty.setVisible(not paths)

    def _open_recent(self, item: QListWidgetItem) -> None:
        self.recentRequested.emit(item.data(Qt.ItemDataRole.UserRole))
