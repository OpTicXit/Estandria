"""Configuración: perfiles, carpetas, copias de seguridad, exportación, apariencia e idioma."""
from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QWidget,
)

from app.core.document_loader import list_backups, prune_backups
from app.database.profile_repository import ProfileError, ProfileRepository
from app.database.settings_repository import SettingsRepository
from app.i18n import IDIOMAS, language_name
from app.paths import backups_dir
from app.ui.profile_dialog import ProfileDialog
from app.ui.theme import SCALES
from app.ui.widgets import Banner, NoWheelComboBox, card, hbox, label, page_header, scroll_page

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*]')


class SettingsPage(QWidget):
    profileLoadRequested = Signal(int)
    profileCreateRequested = Signal()  # guardar la configuración actual como perfil nuevo
    profilesChanged = Signal()
    appearanceChanged = Signal()
    languageChanged = Signal()

    def __init__(self, profiles: ProfileRepository, settings: SettingsRepository, standards, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.profiles, self.settings = profiles, settings
        self.standard_names = {s.id: s.nombre for s in standards}
        self.current_copy_getter = lambda: None  # la copia del documento abierto nunca se borra
        layout = scroll_page(self)
        layout.addWidget(page_header("Configuración", "Todo se guarda en este equipo, en una base de datos local."))
        self.banner = Banner()
        layout.addWidget(self.banner)

        # ---- perfiles
        profiles_card, pl = card()
        pl.addWidget(label("Perfiles", "sectionTitle"))
        pl.addWidget(label("Un perfil guarda la normativa, qué reglas están activas y sus valores. Las excepciones "
                           "pertenecen a cada documento y no se guardan en el perfil.", "muted", wrap=True))
        self.profile_list = QListWidget()
        self.profile_list.setMinimumHeight(170)
        self.profile_list.itemSelectionChanged.connect(self._update_buttons)
        self.profile_list.itemDoubleClicked.connect(lambda _: self._load())
        pl.addWidget(self.profile_list)
        self.new_button = QPushButton("Nuevo desde la configuración actual…")
        self.load_button = QPushButton("Cargar")
        self.load_button.setProperty("variant", "primary")
        self.duplicate_button = QPushButton("Duplicar")
        self.edit_button = QPushButton("Editar…")
        self.delete_button = QPushButton("Eliminar")
        self.startup_button = QPushButton("Usar al iniciar")
        self.startup_button.setCheckable(True)
        self.new_button.clicked.connect(self.profileCreateRequested)
        self.load_button.clicked.connect(self._load)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.edit_button.clicked.connect(self._edit)
        self.delete_button.clicked.connect(self._delete)
        self.startup_button.clicked.connect(self._toggle_startup)
        pl.addLayout(hbox(self.new_button, None, self.load_button, self.duplicate_button, self.edit_button,
                          self.startup_button, self.delete_button))
        layout.addWidget(profiles_card)

        # ---- archivos y copias de seguridad
        files_card, fl = card()
        fl.addWidget(label("Archivos y copias de seguridad", "sectionTitle"))
        self.export_folder = QLineEdit()
        self.export_folder.setReadOnly(True)
        choose_export = QPushButton("Elegir…")
        choose_export.clicked.connect(lambda: self._choose_folder("carpeta_exportacion"))
        reset_export = QPushButton("Usar la del original")
        reset_export.clicked.connect(lambda: self._set("carpeta_exportacion", ""))
        fl.addWidget(label("Carpeta de exportación predeterminada", "fieldLabel"))
        fl.addLayout(hbox(self.export_folder, choose_export, reset_export))
        self.backup_folder = QLineEdit()
        self.backup_folder.setReadOnly(True)
        choose_backup = QPushButton("Elegir…")
        choose_backup.clicked.connect(lambda: self._choose_folder("carpeta_respaldos"))
        reset_backup = QPushButton("Predeterminada")
        reset_backup.clicked.connect(lambda: self._set("carpeta_respaldos", ""))
        open_backup = QPushButton("Abrir carpeta")
        open_backup.clicked.connect(lambda: os.startfile(str(self.backup_path())))  # noqa: S606
        fl.addWidget(label("Carpeta de copias de seguridad (copia de cada documento importado)", "fieldLabel"))
        fl.addLayout(hbox(self.backup_folder, choose_backup, reset_backup, open_backup))
        self.keep = QSpinBox()
        self.keep.setRange(0, 9999)
        self.keep.setSpecialValueText("Todas")
        self.keep.setSuffix(" copias")
        self.keep.valueChanged.connect(lambda v: self._set("conservar_respaldos", int(v), refresh=False))
        self.backup_stats = label("", "muted")
        prune = QPushButton("Aplicar el límite ahora")
        prune.clicked.connect(self._prune_now)
        fl.addLayout(hbox(label("Conservar", "fieldLabel"), self.keep, self.backup_stats, None, prune))
        fl.addWidget(label("Con un límite, al importar se eliminan las copias más antiguas creadas por Estandria en esa "
                           "carpeta. Nunca se borran otros archivos ni la copia del documento abierto.", "muted", wrap=True))
        layout.addWidget(files_card)

        # ---- exportación
        export_card, el = card()
        el.addWidget(label("Exportación", "sectionTitle"))
        self.suffix = QLineEdit()
        self.suffix.setMaxLength(40)
        self.suffix.editingFinished.connect(self._save_suffix)
        el.addLayout(hbox(label("Sufijo del archivo exportado", "fieldLabel"), self.suffix,
                          label("«{normativa}» se reemplaza por la normativa (p. ej. trabajo_APA7.docx)", "muted"), None))
        self.open_after = QCheckBox("Abrir el documento al terminar de exportar")
        self.open_after.toggled.connect(lambda v: self._set("abrir_al_exportar", bool(v), refresh=False))
        el.addWidget(self.open_after)
        layout.addWidget(export_card)

        # ---- apariencia e idioma
        look_card, ll = card()
        ll.addWidget(label("Apariencia e idioma", "sectionTitle"))
        self.scale = NoWheelComboBox()
        for value in SCALES:
            self.scale.addItem(f"{value} %", value)
        self.scale.currentIndexChanged.connect(self._save_scale)
        ll.addLayout(hbox(label("Tamaño de la interfaz", "fieldLabel"), self.scale, None))
        self.animations = QCheckBox("Animaciones de la interfaz")
        self.animations.toggled.connect(self._save_animations)
        ll.addWidget(self.animations)
        self.language = NoWheelComboBox()
        for code in IDIOMAS:
            self.language.addItem(language_name(code), code)
        self.language.currentIndexChanged.connect(self._save_language)
        ll.addLayout(hbox(label("Idioma de la limpieza de estilo", "fieldLabel"), self.language, None))
        ll.addWidget(label("Tema: Dark Tech. El resto de la interfaz está en español; la limpieza de estilo admite "
                           "español de Latinoamérica, de España e inglés.", "muted", wrap=True))
        layout.addWidget(look_card)
        layout.addStretch(1)

    # ------------------------------------------------------------------ estado
    def backup_path(self) -> Path:
        custom = self.settings.get("carpeta_respaldos")
        return Path(custom) if custom else backups_dir()

    def refresh(self) -> None:
        startup = self.settings.get("perfil_inicial")
        selected = self._selected_id()
        self.profile_list.clear()
        for profile in self.profiles.list():
            star = "  ★ al iniciar" if profile.id == startup else ""
            text = f"{profile.nombre}  ·  {self.standard_names.get(profile.normativa, profile.normativa)}{star}"
            if profile.descripcion:
                text += f"\n{profile.descripcion}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            item.setToolTip(f"Modificado: {profile.modificado.replace('T', ' ')}")
            self.profile_list.addItem(item)
            if profile.id == selected:
                item.setSelected(True)
        if not self.profile_list.count():
            self.profile_list.addItem(QListWidgetItem("Todavía no hay perfiles. Configure las reglas en Normativa y guárdelas aquí."))
        self.export_folder.setText(self.settings.get("carpeta_exportacion") or "La misma carpeta del documento original")
        self.backup_folder.setText(str(self.backup_path()))
        self.keep.blockSignals(True)
        self.keep.setValue(self.settings.get("conservar_respaldos"))
        self.keep.blockSignals(False)
        backups = list_backups(self.backup_path())
        size = sum(p.stat().st_size for p in backups) / (1024 * 1024)
        self.backup_stats.setText(f"Ahora hay {len(backups)} copia(s), {size:.1f} MB")
        self.suffix.setText(self.settings.get("sufijo_exportacion"))
        for checkbox, key in ((self.open_after, "abrir_al_exportar"), (self.animations, "animaciones")):
            checkbox.blockSignals(True)
            checkbox.setChecked(self.settings.get(key))
            checkbox.blockSignals(False)
        for combo, key in ((self.scale, "escala_interfaz"), (self.language, "idioma")):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(self.settings.get(key))))
            combo.blockSignals(False)
        self._update_buttons()

    def _selected_id(self) -> int | None:
        items = self.profile_list.selectedItems() if hasattr(self, "profile_list") else []
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _update_buttons(self) -> None:
        profile_id = self._selected_id()
        for button in (self.load_button, self.duplicate_button, self.edit_button, self.delete_button, self.startup_button):
            button.setEnabled(profile_id is not None)
        self.startup_button.setChecked(profile_id is not None and profile_id == self.settings.get("perfil_inicial"))

    def _set(self, key: str, value, refresh: bool = True) -> None:
        self.settings.set(key, value)
        self.banner.show_message("Preferencia guardada.", "success")
        if refresh:
            self.refresh()

    # ------------------------------------------------------------------ perfiles
    def _load(self) -> None:
        if self._selected_id() is not None:
            self.profileLoadRequested.emit(self._selected_id())

    def _duplicate(self) -> None:
        copy = self.profiles.duplicate(self._selected_id())
        self.banner.show_message(f"Se creó «{copy.nombre}».", "success")
        self.profilesChanged.emit()

    def _edit(self) -> None:
        profile = self.profiles.get(self._selected_id())
        dialog = ProfileDialog(self, "Editar perfil", profile.nombre, profile.descripcion)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                nombre, descripcion = dialog.values()
                self.profiles.update(profile.id, nombre=nombre, descripcion=descripcion)
            except ProfileError as exc:
                QMessageBox.warning(self, "Editar perfil", str(exc))
                continue
            self.banner.show_message("Perfil actualizado.", "success")
            self.profilesChanged.emit()
            return

    def _delete(self) -> None:
        profile = self.profiles.get(self._selected_id())
        answer = QMessageBox.question(self, "Eliminar perfil",
                                      f"¿Eliminar el perfil «{profile.nombre}»? Esta acción no se puede deshacer.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.profiles.delete(profile.id)
        if self.settings.get("perfil_inicial") == profile.id:
            self.settings.set("perfil_inicial", None)
        self.banner.show_message(f"Se eliminó «{profile.nombre}».", "success")
        self.profilesChanged.emit()

    def _toggle_startup(self, checked: bool) -> None:
        self.settings.set("perfil_inicial", self._selected_id() if checked else None)
        self.banner.show_message("El perfil se cargará al iniciar." if checked else "Al iniciar se usarán los valores de la normativa.",
                                 "success")
        self.refresh()

    # ------------------------------------------------------------------ archivos
    def _choose_folder(self, key: str) -> None:
        start = self.settings.get(key) or str(Path.home() / "Documents")
        folder = QFileDialog.getExistingDirectory(self, "Elegir carpeta", start)
        if not folder:
            return
        if not os.access(folder, os.W_OK):
            self.banner.show_message(f"No se puede escribir en «{folder}». Elija otra carpeta.", "error")
            return
        self._set(key, folder)

    def _prune_now(self) -> None:
        keep = self.settings.get("conservar_respaldos")
        if keep <= 0:
            self.banner.show_message("No hay límite configurado: se conservan todas las copias.", "info")
            return
        extra = max(0, len(list_backups(self.backup_path())) - keep)
        if not extra:
            self.banner.show_message("No hay copias que superen el límite.", "info")
            return
        answer = QMessageBox.question(self, "Copias de seguridad",
                                      f"Se eliminarán {extra} copia(s) antigua(s) de documentos importados en "
                                      f"«{self.backup_path()}». No se puede deshacer. ¿Continuar?")
        if answer == QMessageBox.StandardButton.Yes:
            current = self.current_copy_getter()
            removed = prune_backups(self.backup_path(), keep, protect=(current,) if current else ())
            self.banner.show_message(f"Se eliminaron {removed} copia(s).", "success")
            self.refresh()

    def _save_suffix(self) -> None:
        value = self.suffix.text().strip()
        if _INVALID_FILENAME.search(value.replace("{normativa}", "")):
            self.banner.show_message('El sufijo no puede contener < > : " / \\ | ? *', "error")
            self.suffix.setText(self.settings.get("sufijo_exportacion"))
            return
        if value != self.settings.get("sufijo_exportacion"):
            self._set("sufijo_exportacion", value, refresh=False)

    # ------------------------------------------------------------------ apariencia
    def _save_scale(self) -> None:
        self._set("escala_interfaz", int(self.scale.currentData()), refresh=False)
        self.appearanceChanged.emit()

    def _save_language(self) -> None:
        self._set("idioma", self.language.currentData(), refresh=False)
        self.languageChanged.emit()

    def _save_animations(self, enabled: bool) -> None:
        self._set("animaciones", bool(enabled), refresh=False)
        self.appearanceChanged.emit()
