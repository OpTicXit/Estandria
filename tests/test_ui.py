"""Prueba de humo de la interfaz: el flujo completo a través de la ventana real (sin pantalla)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    from app.ui.theme import apply_theme
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(application)
    return application


def wait(app, window):
    deadline = time.time() + 30
    while window.runner.busy and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_window_full_flow(app, full_doc, tmp_path, monkeypatch):
    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.import_document(str(full_doc))
    wait(app, window)
    assert window.structure is not None and window.import_page.table.rowCount() == len(window.structure.elements)

    page = window.standards_page
    page._toggle("par_sangria_primera", False)
    assert "Sangría de primera línea" in page.warnings.text()

    # Interruptor de categoría y su contador
    switch, counter = page.category_controls["referencias"]
    total = len(page.selection.standard.rules_in("referencias"))
    switch.setChecked(False)
    assert counter.text() == f"0 de {total} activas"
    switch.setChecked(True)
    assert counter.text() == f"{total} de {total} activas"

    # Vínculo fuente → tamaño: el editor de tamaño refleja el ajuste automático
    page._set_param("tip_familia", "familia", "Calibri")
    size_row = next(r for r in page.rows if r.rule.id == "tip_tamano")
    assert size_row.editors["tamano"].value() == 11
    assert "11 pt" in page.message.text()
    page._set_param("tip_familia", "familia", "Times New Roman")
    window.run_analysis()
    wait(app, window)
    active = len(page.selection.active_rules())
    assert window.report is not None and window.analysis_page.tree.topLevelItemCount() == active
    assert window.analysis_page.tiles["revisar"].value.text() != "0"

    # Excepción: el encabezado «Introducción» no se modifica
    from app.core.exceptions import DocException
    intro = next(e for e in window.structure.elements if e.text == "Introducción")
    window.exceptions.add(DocException("elemento", (intro.index,)))
    window.import_page.refresh_exceptions()
    window.import_page.exceptionsChanged.emit()
    assert window.report is None, "las excepciones invalidan el análisis anterior"
    row = window.structure.elements.index(intro)
    assert window.import_page.table.item(row, 5).text().startswith("Excluido")

    # Vista previa en memoria
    window.show_preview()
    wait(app, window)
    preview = window.preview_page
    assert preview.before.toPlainText() and preview.after.toPlainText()
    assert preview.changes.count() > 0
    assert window.stack.currentWidget() is preview

    # Exportar: se pide confirmación porque la excepción anula reglas obligatorias
    asked = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a) or QtWidgets.QMessageBox.StandardButton.Yes))
    target = tmp_path / "exportado.docx"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    window.export_document()
    assert asked, "se pidió confirmación"
    wait(app, window)
    assert window.result is not None and window.result.errores == []
    assert target.is_file()
    window.close()


def test_profiles_and_settings(app, full_doc, monkeypatch):
    from app.ui.main_window import MainWindow
    from app.ui.profile_dialog import ProfileDialog
    window = MainWindow()
    page = window.standards_page
    page._toggle("par_sangria_primera", False)

    monkeypatch.setattr(ProfileDialog, "exec", lambda self: QtWidgets.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ProfileDialog, "values", lambda self: ("APA 7 Profesor", "Sin sangría"))
    window.save_profile_as()
    profile = window.profiles.list()[0]
    assert window.active_profiles["apa7"] == profile.id
    assert page.profile_combo.currentText() == "APA 7 Profesor"
    assert not page.save_profile.isEnabled(), "recién guardado: sin cambios pendientes"

    page._toggle("tip_color", False)
    assert page.save_profile.isEnabled() and "sin guardar" in page.dirty_label.text()
    window._profile_chosen(None)
    assert window.selections["apa7"].is_active("par_sangria_primera")
    window.load_profile(profile.id)
    assert not window.selections["apa7"].is_active("par_sangria_primera")
    assert window.selections["apa7"].is_active("tip_color"), "el cambio no guardado se descartó"

    window.settings.set("perfil_inicial", profile.id)
    window.import_document(str(full_doc))
    wait(app, window)
    window.close()

    reopened = MainWindow()  # la configuración sobrevive al reinicio
    assert reopened.active_profiles["apa7"] == profile.id
    assert not reopened.selections["apa7"].is_active("par_sangria_primera")
    assert reopened.home_page.recent_list.count() == 1
    assert reopened.home_page.profile_list.item(0).text().startswith("APA 7 Profesor")
    reopened._go("configuracion")
    assert reopened.settings_page.profile_list.count() == 1
    reopened.close()


def test_style_cleanup_flow(app, tmp_path):
    import hashlib
    from docx import Document
    from app.ui.main_window import MainWindow
    source = tmp_path / "estilo.docx"
    doc = Document()
    doc.add_paragraph("Cabe destacar que el sueño mejora la memoria. Se usó un lapso de tiempo breve.")
    doc.save(source)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    window = MainWindow()
    window.import_document(str(source))
    wait(app, window)
    first_copy = window.working_copy
    window.run_style()
    wait(app, window)
    page = window.style_page
    rules = {f.ruleId for f in page.findings}
    assert {"muletilla", "pleonasmo"} <= rules
    assert page.tree.topLevelItemCount() == len(rules)

    pleonasm = next(f for f in page.findings if f.ruleId == "pleonasmo")
    page._show_detail(pleonasm)
    assert "[−lapso de tiempo−]" in page.diff.text() and "{+lapso+}" in page.diff.text()
    page.rejected.emit(("pleonasmo", pleonasm.elemento, pleonasm.excerpt))
    assert all(f.ruleId != "pleonasmo" for f in page.findings)

    filler = next(f for f in page.findings if f.ruleId == "muletilla")
    window.accept_style([filler])
    wait(app, window)
    assert window.working_copy != first_copy, "se trabaja sobre una copia nueva"
    assert all(f.ruleId != "muletilla" for f in page.findings)
    assert window.structure.elements[0].text.startswith("El sueño mejora")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash, "el original no cambia"
    window.close()


def test_unsupported_file_shows_message(app, tmp_path):
    from app.ui.main_window import MainWindow
    window = MainWindow()
    path = tmp_path / "viejo.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    window.import_document(str(path))
    assert window.working_copy is None
    assert window.import_page.compat_badge.text() == "No compatible"
    window.close()
