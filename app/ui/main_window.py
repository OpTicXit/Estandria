"""Ventana principal: navegación lateral y orquestación del flujo importar → reglas → análisis → resultados."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app import APP_NAME, APP_VERSION
from app.core.document_analyzer import analyze_document, known_scopes
from app.core.document_loader import FileInfo, LoadError, create_working_copy, inspect_file, prune_backups
from app.core.document_processor import apply_selection, process_document
from app.core.document_validator import validate
from app.core.exceptions import ExceptionSet
from app.core.rule_engine import RuleSelection, discover_standards
from app.database.database import Database
from app.database.profile_repository import ProfileError, ProfileRepository
from app.database.settings_repository import SettingsRepository
from app.formats.docx_handler import open_docx
from app.formats.docx_operations import OPERATIONS
from app.formats.docx_preview import render_html
from app.i18n import set_language, t
from app.paths import standards_dir, user_data_dir
from app.style import ReviewText, analyze, apply_findings, detect_language
from app.ui import theme
from app.ui.style_page import StylePage, finding_key
from app.ui.analysis_page import AnalysisPage
from app.ui.home_page import HomePage
from app.ui.import_page import ImportPage
from app.ui.preview_page import PreviewData, PreviewPage
from app.ui.profile_dialog import ProfileDialog
from app.ui.results_page import ResultsPage
from app.ui.settings_page import SettingsPage
from app.ui.standards_page import StandardsPage
from app.ui.tasks import TaskRunner
from app.ui.theme import apply_theme, icon
from app.ui.widgets import label

MAX_RECENT = 8
NAVIGATION = (
    ("inicio", "Inicio", "home"),
    ("documento", "Documento", "file"),
    ("estilo", "Estilo", "pen"),
    ("normativa", "Normativa", "sliders"),
    ("analisis", "Análisis", "scan"),
    ("vista", "Vista previa", "eye"),
    ("resultados", "Resultados", "check"),
    ("configuracion", "Configuración", "gear"),
)
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*]')


def _load_job(info: FileInfo, folder: Path | None, keep: int):
    copy = create_working_copy(info, folder, keep)
    return info, copy, analyze_document(open_docx(copy))


def _style_job(copy: Path):
    review = ReviewText(analyze_document(open_docx(copy)))
    language = detect_language(review)
    return language, review.text, analyze(review) if language == "es" else []


def _accept_style_job(copy: Path, folder: Path, keep: int, findings: list):
    """Aplica los hallazgos aceptados en una NUEVA copia de trabajo; la anterior y el original no cambian."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    new_copy = folder / f"{stamp}_{copy.name.split('_', 1)[-1]}"
    doc = open_docx(copy)
    applied = apply_findings(ReviewText(analyze_document(doc)), findings)
    try:
        doc.save(str(new_copy))
        structure = analyze_document(open_docx(new_copy))  # verifica que la copia nueva se abre
    except Exception:
        new_copy.unlink(missing_ok=True)
        raise
    prune_backups(folder, keep, protect=(new_copy,))
    return (new_copy, structure, len(applied), *_style_job(new_copy))


def _comparable(data: dict) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _validate_job(copy: Path, selection: RuleSelection, exceptions: ExceptionSet):
    doc = open_docx(copy)
    return validate(doc, analyze_document(doc), selection, exceptions)


def _preview_job(copy: Path, selection: RuleSelection, exceptions: ExceptionSet) -> PreviewData:
    """Aplica las reglas a una copia en memoria y genera ambas vistas; no escribe en disco."""
    before = open_docx(copy)
    before_structure = analyze_document(before)
    after = open_docx(copy)
    result = apply_selection(after, selection, exceptions)
    changed = {c.indice for c in result.cambios if c.indice is not None}
    excluded = set()
    for rule in selection.active_rules():
        excluded |= exceptions.excluded(before_structure, rule.id)
    html_before, width_before = render_html(before, before_structure)
    html_after, width_after = render_html(after, analyze_document(after), changed, excluded - changed)
    labels = {e.index: e.label for e in before_structure.elements}
    rules_by_element: dict[int, list[str]] = {}
    for change in result.cambios:
        if change.indice is not None:
            rules_by_element.setdefault(change.indice, []).append(change.regla)
    changes = [(index, labels[index], ", ".join(dict.fromkeys(rules))) for index, rules in sorted(rules_by_element.items())]
    sections = [f"{c.elemento} · {c.regla}: {c.antes} → {c.despues}" for c in result.cambios if c.indice is None]
    return PreviewData(html_before, width_before, html_after, width_after, changes, sections, len(excluded))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Automatizador inteligente de documentos")
        self.setWindowIcon(icon("logo"))
        self.resize(1320, 860)
        self.setMinimumSize(1060, 680)

        self.standards, catalog_errors = discover_standards(standards_dir(), OPERATIONS, known_scopes())
        self.selections = {s.id: RuleSelection(s) for s in self.standards}
        self.standard = self.standards[0] if self.standards else None
        self.file_info: FileInfo | None = None
        self.working_copy: Path | None = None
        self.structure = None
        self.report = None
        self.result = None
        self.exceptions = ExceptionSet()  # propias del documento abierto; se vacían al importar otro
        self.active_profiles: dict[str, int | None] = {s.id: None for s in self.standards}
        startup_notes = self._open_database()
        self.runner = TaskRunner(self)
        self.runner.busyChanged.connect(self._on_busy)
        theme.animations_enabled = self.settings.get("animaciones")
        set_language(self.settings.get("idioma"))
        self.style_rejected: set[tuple] = set()  # hallazgos de estilo rechazados en esta sesión

        self._build_ui()
        self.home_page.set_recent(self._recent())
        if self.standard:
            self.standards_page.set_selection(self.selections[self.standard.id])
        startup = self.settings.get("perfil_inicial")
        if startup is not None and self.profiles.get(startup):
            self.load_profile(startup, quiet=True)
        self._refresh_profiles()
        self._update_navigation()
        self._go("inicio", animate=False)
        notes = startup_notes + catalog_errors
        if notes:
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, APP_NAME, "\n\n".join(notes)))

    def _open_database(self) -> list[str]:
        """Abre la base local; si no es posible, sigue funcionando en memoria y lo avisa."""
        try:
            self.db = Database(user_data_dir() / "estandria.db")
        except Exception as exc:  # permisos, disco lleno, versión más reciente…
            self.db = Database(":memory:")
            notes = [f"No se pudo abrir la base de datos local ({exc}). Los perfiles y preferencias de esta sesión "
                     "no se guardarán."]
        else:
            notes = []
            if self.db.recovered_from:
                notes.append(f"La base de datos local estaba dañada. Se apartó como «{self.db.recovered_from.name}» "
                             "y se creó una nueva; los perfiles anteriores no se pudieron recuperar.")
        self.profiles = ProfileRepository(self.db)
        self.settings = SettingsRepository(self.db)
        return notes

    # ------------------------------------------------------------------ construcción
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(224)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(14, 20, 14, 16)
        side.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon("logo").pixmap(QSize(30, 30)))
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(label(APP_NAME, "brand"))
        brand_text.addWidget(label("Automatizador de documentos", "brandTag"))
        brand.addLayout(brand_text)
        brand.addStretch(1)
        side.addLayout(brand)
        side.addSpacing(22)

        self.nav_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, text, icon_name in NAVIGATION:
            button = QPushButton(f"  {text}")
            button.setObjectName("navButton")
            button.setIcon(icon(icon_name))
            button.setIconSize(QSize(18, 18))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == "vista":  # la vista previa se regenera siempre con la configuración actual
                button.clicked.connect(self.show_preview)
            else:
                button.clicked.connect(lambda _=False, k=key: self._go(k))
            group.addButton(button)
            side.addWidget(button)
            self.nav_buttons[key] = button
        side.addStretch(1)
        side.addWidget(label(f"Versión {APP_VERSION}\n100 % local · sin conexión", "sidebarFooter"))
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.home_page = HomePage(self.standards)
        self.import_page = ImportPage()
        self.standards_page = StandardsPage(self.standards)
        self.analysis_page = AnalysisPage()
        self.preview_page = PreviewPage()
        self.results_page = ResultsPage()
        self.settings_page = SettingsPage(self.profiles, self.settings, self.standards)
        self.settings_page.current_copy_getter = lambda: self.working_copy
        self.style_page = StylePage()
        self.pages = {"inicio": self.home_page, "documento": self.import_page, "estilo": self.style_page,
                      "normativa": self.standards_page,
                      "analisis": self.analysis_page, "vista": self.preview_page, "resultados": self.results_page,
                      "configuracion": self.settings_page}
        self.import_page.set_context(self.exceptions, lambda: self.selections[self.standard.id])
        for page in self.pages.values():
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self._veil = QWidget(self.stack)
        self._veil.setStyleSheet("background: #0B0F14;")
        self._veil.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._veil.hide()
        veil_effect = QGraphicsOpacityEffect(self._veil)
        self._veil.setGraphicsEffect(veil_effect)
        self._veil_animation = QPropertyAnimation(veil_effect, b"opacity", self)
        self._veil_animation.setDuration(200)
        self._veil_animation.setStartValue(1.0)
        self._veil_animation.setEndValue(0.0)
        self._veil_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._veil_animation.finished.connect(self._veil.hide)

        self.status_label = QLabel("Listo")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

        self.home_page.importRequested.connect(self.browse_document)
        self.home_page.recentRequested.connect(self.import_document)
        self.home_page.standardRequested.connect(self._open_standard)
        self.import_page.browseRequested.connect(self.browse_document)
        self.import_page.fileChosen.connect(self.import_document)
        self.import_page.continueRequested.connect(lambda: self._go("normativa"))
        self.import_page.exceptionsChanged.connect(self._exceptions_changed)
        self.standards_page.standardChanged.connect(self._select_standard)
        self.standards_page.analyzeRequested.connect(self.run_analysis)
        self.analysis_page.backRequested.connect(lambda: self._go("normativa"))
        self.analysis_page.applyRequested.connect(self.export_document)
        self.analysis_page.previewRequested.connect(self.show_preview)
        self.preview_page.backRequested.connect(self._back_from_preview)
        self.preview_page.applyRequested.connect(self.export_document)
        self.results_page.openFileRequested.connect(self._open_result)
        self.results_page.openFolderRequested.connect(self._show_result_in_folder)
        self.results_page.newDocumentRequested.connect(self.browse_document)
        self.home_page.profileRequested.connect(self._open_profile)
        self.home_page.settingsRequested.connect(lambda: self._go("configuracion"))
        self.standards_page.profileSelected.connect(self._profile_chosen)
        self.standards_page.saveProfileRequested.connect(self.save_profile)
        self.standards_page.saveAsProfileRequested.connect(self.save_profile_as)
        self.standards_page.selectionEdited.connect(self._update_dirty)
        self.settings_page.profileLoadRequested.connect(self._open_profile)
        self.settings_page.profileCreateRequested.connect(self.save_profile_as)
        self.settings_page.profilesChanged.connect(self._refresh_profiles)
        self.settings_page.appearanceChanged.connect(self._apply_appearance)
        self.settings_page.languageChanged.connect(self._apply_language)
        self.style_page.analyzeRequested.connect(self.run_style)
        self.style_page.acceptRequested.connect(self.accept_style)
        self.style_page.rejected.connect(self._reject_style)
        self.nav_buttons["estilo"].setText(f"  {t('estilo.nav')}")

    # ------------------------------------------------------------------ navegación
    def _go(self, key: str, animate: bool = True) -> None:
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        if key == "configuracion":
            self.settings_page.refresh()
        if animate and theme.animations_enabled:
            # Transición discreta: un velo del color de fondo se desvanece sobre la página nueva.
            # (Un efecto de opacidad sobre la página misma pinta en negro sus tablas durante la animación.)
            self._veil.setGeometry(self.stack.rect())
            self._veil.raise_()
            self._veil.show()
            self._veil_animation.stop()
            self._veil_animation.start()

    def _update_navigation(self) -> None:
        self.nav_buttons["analisis"].setEnabled(self.report is not None)
        self.nav_buttons["vista"].setEnabled(self.working_copy is not None)
        self.nav_buttons["estilo"].setEnabled(self.working_copy is not None)
        self.style_page.set_document(self.working_copy is not None)
        self.nav_buttons["resultados"].setEnabled(self.result is not None)
        self.standards_page.set_document(self.file_info.nombre if self.working_copy else None)

    def _on_busy(self, busy: bool, message: str) -> None:
        self.sidebar.setEnabled(not busy)
        self.stack.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.status_label.setText(message)

    def _on_task_error(self, message: str) -> None:
        self.status_label.setText("La operación no se completó.")
        current = next(k for k, page in self.pages.items() if page is self.stack.currentWidget())
        self.nav_buttons[current].setChecked(True)  # la barra lateral vuelve a indicar la página visible
        QMessageBox.critical(self, APP_NAME, message)

    # ------------------------------------------------------------------ flujo
    def browse_document(self) -> None:
        start = str(self.file_info.carpeta) if self.file_info else str(Path.home() / "Documents")
        path, _ = QFileDialog.getOpenFileName(self, "Importar documento", start,
                                              "Documentos (*.docx *.doc *.odt *.rtf);;Todos los archivos (*)")
        if path:
            self.import_document(path)

    def import_document(self, path: str) -> None:
        if self.runner.busy:
            return
        self._go("documento")
        try:
            info = inspect_file(path)
        except LoadError as exc:
            self.import_page.show_error(str(exc))
            return
        self.import_page.show_file_info(info)
        if not info.soportado:
            self.status_label.setText("Formato no compatible: el archivo no se modificó.")
            return
        folder, keep = self.settings_page.backup_path(), self.settings.get("conservar_respaldos")
        self.runner.run(lambda: _load_job(info, folder, keep), self._on_loaded, self._on_load_error,
                        f"Analizando la estructura de «{info.nombre}»…")

    def _on_load_error(self, message: str) -> None:
        self.import_page.show_error(message)
        self.status_label.setText("No se pudo importar el documento.")

    def _on_loaded(self, payload) -> None:
        self.file_info, self.working_copy, self.structure = payload
        self.report = self.result = None
        self.exceptions.clear()  # las excepciones señalan elementos de un documento concreto
        self.style_rejected.clear()
        self.style_page.show_findings("es", "", [])
        self.import_page.show_structure(self.structure)
        self._update_navigation()
        self._add_recent(str(self.file_info.ruta))
        self.status_label.setText(f"«{self.file_info.nombre}» analizado · copia de trabajo: {self.working_copy}")

    def _open_standard(self, standard_id: str) -> None:
        self._select_standard(standard_id)
        self._go("normativa")

    def _select_standard(self, standard_id: str) -> None:
        self.standard = next(s for s in self.standards if s.id == standard_id)
        self.standards_page.set_selection(self.selections[standard_id])
        self.report = self.result = None
        self._update_navigation()
        self._refresh_profiles()
        if self.structure is not None:
            self.import_page.refresh_exceptions()  # los nombres de reglas dependen de la normativa

    # ------------------------------------------------------------------ perfiles
    def _refresh_profiles(self) -> None:
        names = {s.id: s.nombre for s in self.standards}
        self.home_page.set_profiles(self.profiles.list(), names)
        if self.standard:
            active = self.active_profiles.get(self.standard.id)
            if active is not None and self.profiles.get(active) is None:  # se eliminó
                self.active_profiles[self.standard.id] = active = None
            self.standards_page.set_profiles(self.profiles.list(self.standard.id), active)
        self.settings_page.refresh()
        self._update_dirty()

    def _update_dirty(self) -> None:
        if not self.standard:
            return
        active = self.active_profiles.get(self.standard.id)
        profile = self.profiles.get(active) if active is not None else None
        dirty = profile is not None and _comparable(self.selections[self.standard.id].to_dict()) != _comparable(profile.datos)
        self.standards_page.set_dirty(profile is not None, dirty)

    def load_profile(self, profile_id: int, quiet: bool = False) -> bool:
        profile = self.profiles.get(profile_id)
        if profile is None:
            return False
        if profile.normativa not in self.selections:
            QMessageBox.warning(self, APP_NAME, f"El perfil «{profile.nombre}» usa la normativa «{profile.normativa}», "
                                                "que no está disponible en esta instalación.")
            return False
        if self.standard is None or self.standard.id != profile.normativa:
            self.standard = next(s for s in self.standards if s.id == profile.normativa)
        selection = self.selections[profile.normativa]
        problems = selection.apply_dict(profile.datos)
        self.active_profiles[profile.normativa] = profile.id
        self.standards_page.set_selection(selection)
        self.report = self.result = None
        self._update_navigation()
        self._refresh_profiles()
        message = f"Se cargó el perfil «{profile.nombre}»." + ("\n" + "\n".join(problems) if problems else "")
        self.standards_page.message.show_message(message, "warning" if problems else "info")
        if not quiet:
            self.status_label.setText(f"Perfil «{profile.nombre}» cargado.")
        return True

    def _open_profile(self, profile_id: int) -> None:
        if self.load_profile(profile_id):
            self._go("normativa")

    def _profile_chosen(self, profile_id) -> None:
        if profile_id is None:  # «Valores de la normativa»
            selection = self.selections[self.standard.id]
            selection.reset()
            self.active_profiles[self.standard.id] = None
            self.standards_page.set_selection(selection)
            self.standards_page.message.show_message("Se restauraron los valores de la normativa (sin perfil).", "info")
            self.report = self.result = None
            self._update_navigation()
            self._refresh_profiles()
        else:
            self.load_profile(profile_id)

    def save_profile(self) -> None:
        active = self.active_profiles.get(self.standard.id)
        if active is None:
            self.save_profile_as()
            return
        profile = self.profiles.update(active, datos=self.selections[self.standard.id].to_dict())
        self.standards_page.message.show_message(f"Se guardaron los cambios en «{profile.nombre}».", "success")
        self._refresh_profiles()

    def save_profile_as(self) -> None:
        if not self.standard:
            return
        dialog = ProfileDialog(self, "Guardar como perfil", hint=f"Se guardará la configuración actual de {self.standard.nombre}: "
                                                                 "reglas activas y sus valores.")
        while dialog.exec() == QDialog.DialogCode.Accepted:
            nombre, descripcion = dialog.values()
            try:
                profile = self.profiles.create(nombre, self.standard.id, self.selections[self.standard.id].to_dict(),
                                               descripcion)
            except ProfileError as exc:
                QMessageBox.warning(self, "Guardar como perfil", str(exc))
                continue
            self.active_profiles[self.standard.id] = profile.id
            self.standards_page.message.show_message(f"Se creó el perfil «{profile.nombre}».", "success")
            self._refresh_profiles()
            return

    # ------------------------------------------------------------------ limpieza de estilo
    def run_style(self) -> None:
        if not self.working_copy:
            return
        copy = self.working_copy
        self.runner.run(lambda: _style_job(copy), self._on_style, self._on_task_error, t("estilo.analizar") + "…")

    def _on_style(self, payload, message: str = "") -> None:
        language, text, findings = payload
        visible = [f for f in findings if finding_key(f) not in self.style_rejected]
        self.style_page.show_findings(language, text, visible, message)
        self.status_label.setText(t("estilo.titulo"))

    def accept_style(self, findings: list) -> None:
        if not self.working_copy or not findings:
            return
        copy, folder, keep = self.working_copy, self.settings_page.backup_path(), self.settings.get("conservar_respaldos")
        self.runner.run(lambda: _accept_style_job(copy, folder, keep, findings), self._on_style_accepted,
                        self._on_task_error, t("estilo.aceptar") + "…")

    def _on_style_accepted(self, payload) -> None:
        new_copy, structure, applied, language, text, findings = payload
        self.working_copy, self.structure = new_copy, structure
        self.report = self.result = None  # el texto cambió: el análisis de formato anterior ya no vale
        self.import_page.show_structure(structure)
        self._update_navigation()
        self._on_style((language, text, findings), t("estilo.aplicados", n=applied))

    def _reject_style(self, key: tuple) -> None:
        self.style_rejected.add(key)
        page = self.style_page
        page.show_findings("es", page.review_text, [f for f in page.findings if finding_key(f) != key],
                           t("estilo.rechazado"))

    def _apply_language(self) -> None:
        set_language(self.settings.get("idioma"))
        self.nav_buttons["estilo"].setText(f"  {t('estilo.nav')}")
        self.style_page.retranslate()

    def _apply_appearance(self) -> None:
        theme.animations_enabled = self.settings.get("animaciones")
        apply_theme(QApplication.instance(), self.settings.get("escala_interfaz"))

    def _exceptions_changed(self) -> None:
        self.report = self.result = None  # el análisis anterior ya no refleja las excepciones
        self._update_navigation()
        self.status_label.setText(f"{len(self.exceptions.items)} excepción(es) definidas. Vuelva a analizar para verlas reflejadas.")

    def _warnings(self) -> list[tuple[str, str]]:
        selection = self.selections[self.standard.id]
        return selection.compliance_warnings() + self.exceptions.warnings(self.structure, selection)

    def show_preview(self) -> None:
        if not self.working_copy or not self.standard:
            QMessageBox.information(self, APP_NAME, "Importe primero un documento DOCX.")
            return
        copy, selection, exceptions = self.working_copy, self.selections[self.standard.id], self.exceptions
        self.runner.run(lambda: _preview_job(copy, selection, exceptions), self._on_preview, self._on_task_error,
                        "Generando la vista previa en memoria…")

    def _on_preview(self, data: PreviewData) -> None:
        self.preview_page.show_preview(data)
        self.status_label.setText("Vista previa generada. Ningún archivo se ha modificado.")
        self.nav_buttons["vista"].setChecked(True)
        self.stack.setCurrentWidget(self.preview_page)

    def _back_from_preview(self) -> None:
        self._go("analisis" if self.report is not None else "normativa")

    def run_analysis(self) -> None:
        if not self.working_copy or not self.standard:
            QMessageBox.information(self, APP_NAME, "Importe primero un documento DOCX.")
            return
        selection = self.selections[self.standard.id]
        if not selection.active_rules():
            QMessageBox.information(self, APP_NAME, "Active al menos una regla para analizar el documento.")
            return
        copy, exceptions = self.working_copy, self.exceptions
        self.runner.run(lambda: _validate_job(copy, selection, exceptions), self._on_analyzed, self._on_task_error,
                        "Comparando el documento con las reglas seleccionadas…")

    def _on_analyzed(self, report) -> None:
        self.report = report
        self.result = None
        self.analysis_page.show_report(report, self.structure, self._warnings())
        self._update_navigation()
        self.status_label.setText("Análisis completado. Revise los cambios propuestos antes de exportar.")
        self._go("analisis")

    def export_document(self) -> None:
        if not self.working_copy:
            return
        selection = self.selections[self.standard.id]
        blocking = [text for level, text in self.exceptions.warnings(self.structure, selection) if level == "advertencia"]
        if blocking:  # las excepciones prevalecen, pero si anulan reglas obligatorias se pide confirmación
            answer = QMessageBox.question(
                self, "Excepciones y normativa",
                "Las excepciones impiden aplicar reglas obligatorias de la normativa:\n\n• " + "\n• ".join(blocking)
                + "\n\nEl documento exportado no cumplirá completamente la normativa. ¿Exportar de todos modos?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar documento con formato", str(self._suggested_export_path()),
                                              "Documento de Word (*.docx)")
        if not path:
            return
        copy, original, exceptions = self.working_copy, self.file_info.ruta, self.exceptions
        self.runner.run(lambda: process_document(copy, original, path, selection, exceptions), self._on_processed,
                        self._on_task_error, "Aplicando reglas y verificando el archivo exportado…")

    def _suggested_export_path(self) -> Path:
        """Nombre y carpeta propuestos según las preferencias de exportación."""
        suffix = self.settings.get("sufijo_exportacion").replace("{normativa}", self.standard.id.upper())
        suffix = _INVALID_FILENAME.sub("", suffix)
        custom = self.settings.get("carpeta_exportacion")
        folder = Path(custom) if custom and Path(custom).is_dir() else self.file_info.carpeta
        return folder / f"{self.file_info.ruta.stem}{suffix}.docx"

    def _on_processed(self, result) -> None:
        self.result = result
        self.results_page.show_result(result)
        self._update_navigation()
        self.status_label.setText(f"Exportado: {result.destino}")
        self._go("resultados")
        if self.settings.get("abrir_al_exportar"):
            self._open_result()

    def _open_result(self) -> None:
        if self.result:
            try:
                os.startfile(str(self.result.destino))  # noqa: S606 — abre con la aplicación predeterminada
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f"No se pudo abrir el documento: {exc}")

    def _show_result_in_folder(self) -> None:
        if self.result:
            subprocess.Popen(["explorer", "/select,", str(self.result.destino)])  # noqa: S603,S607

    # ------------------------------------------------------------------ recientes
    def _recent(self) -> list[str]:
        return [p for p in self.settings.get("recientes") if isinstance(p, str) and Path(p).is_file()]

    def _add_recent(self, path: str) -> None:
        paths = [path] + [p for p in self._recent() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.set("recientes", paths[:MAX_RECENT])
        self.home_page.set_recent(self._recent())

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.runner.busy:
            self.status_label.setText("Esperando a que termine la operación en curso…")
            self.runner.wait()
        self.db.close()
        event.accept()
