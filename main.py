"""Punto de entrada de Estandria.

Uso normal: ejecutar sin argumentos.
Diagnóstico del ejecutable: Estandria.exe --autoprueba <documento.docx> <carpeta_salida>
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import APP_NAME, APP_VERSION
from app.paths import user_data_dir


def _setup_logging() -> Path:
    log_file = user_data_dir() / "registro.log"
    logging.basicConfig(filename=log_file, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return log_file


def _install_excepthook(log_file: Path) -> None:
    """Un error inesperado se registra y se muestra; nunca cierra la aplicación en silencio."""
    def hook(kind, value, tb):
        logging.getLogger(APP_NAME).error("Error no controlado:\n%s", "".join(traceback.format_exception(kind, value, tb)))
        if QApplication.instance():
            QMessageBox.critical(None, APP_NAME, f"Se produjo un error inesperado:\n{value}\n\nDetalles en: {log_file}")
    sys.excepthook = hook


def _self_test(document: Path, output_dir: Path) -> int:
    """Abre la ventana real y procesa un documento de punta a punta; escribe autoprueba.json."""
    from app.core.document_analyzer import analyze_document
    from app.core.document_loader import create_working_copy, inspect_file
    from app.core.document_processor import process_document
    from app.core.exceptions import DocException, ExceptionSet
    from app.database.database import Database
    from app.database.profile_repository import ProfileRepository
    from app.formats.docx_handler import open_docx
    from app.ui.main_window import MainWindow, _preview_job
    from app.ui.theme import apply_theme, icon

    app = QApplication(sys.argv[:1])
    apply_theme(app)
    window = MainWindow()
    window._apply_appearance()  # escala y animaciones guardadas
    window.show()
    app.processEvents()
    report: dict = {"version": APP_VERSION, "ejecutable": bool(getattr(sys, "frozen", False))}
    try:
        report["normativas"] = [s.id for s in window.standards]
        report["iconos_svg"] = not icon("home").pixmap(24, 24).isNull()
        selection = window.selections[window.standards[0].id]
        test_db = Database(output_dir / "autoprueba.db")
        profile = ProfileRepository(test_db).create("Autoprueba", selection.standard.id, selection.to_dict())
        report["perfiles"] = ProfileRepository(test_db).get(profile.id).datos == selection.to_dict()
        test_db.close()
        info = inspect_file(document)
        copy = create_working_copy(info)
        structure = analyze_document(open_docx(copy))
        report["elementos"] = len(structure.elements)
        exceptions = ExceptionSet()
        exceptions.add(DocException("elemento", (structure.elements[-1].index,)))
        preview = _preview_job(copy, selection, exceptions)
        window.preview_page.show_preview(preview)
        report["vista_previa"] = bool(window.preview_page.after.toPlainText().strip() and preview.changes)
        result = process_document(copy, info.ruta, output_dir / "autoprueba_resultado.docx", selection, exceptions)
        report["cambios"] = len(result.cambios)
        report["errores"] = result.errores
        report["integridad_ok"] = all(c.ok for c in result.integridad)
        report["cumplimiento"] = {r.rule.id: r.estado for r in result.cumplimiento.reglas}
        report["excluidos"] = sum(r.excluidos for r in result.cumplimiento.reglas)
        report["ok"] = bool(report["iconos_svg"] and report["integridad_ok"] and not result.errores
                            and report["vista_previa"] and report["excluidos"] > 0 and report["perfiles"])
    except Exception as exc:
        report["excepcion"] = "".join(traceback.format_exception(exc))
        report["ok"] = False
    (output_dir / "autoprueba.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    QTimer.singleShot(600, app.quit)
    app.exec()
    return 0 if report["ok"] else 1


def main() -> int:
    log_file = _setup_logging()
    if len(sys.argv) == 4 and sys.argv[1] == "--autoprueba":
        return _self_test(Path(sys.argv[2]), Path(sys.argv[3]))

    from app.ui.main_window import MainWindow
    from app.ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    apply_theme(app)
    _install_excepthook(log_file)
    window = MainWindow()
    window._apply_appearance()  # escala y animaciones guardadas
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
