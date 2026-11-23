# Especificación de PyInstaller para Estandria.
# Modo por defecto: onedir (carpeta dist\Estandria\). Con ESTANDRIA_ONEFILE=1: un único dist\Estandria.exe.
import os

from PyInstaller.utils.hooks import collect_data_files

ONEFILE = os.environ.get("ESTANDRIA_ONEFILE") == "1"

datas = [
    ("app/standards", "app/standards"),  # catálogos JSON de normativas
    ("assets", "assets"),                # estilos e iconos
    ("LICENSE.md", "."),                 # licencia y avisos legales dentro del ejecutable
    ("NOTICE.md", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("licenses", "licenses"),
]
datas += collect_data_files("docx")      # plantillas internas de python-docx (encabezados, estilos)

a = Analysis(
    ["main.py"],
    pathex=[],
    datas=datas,
    hiddenimports=["PySide6.QtSvg"],
    excludes=["tkinter", "pytest", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(name="Estandria", console=False, icon="assets/icons/app.ico", upx=False, debug=False)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="Estandria", upx=False)
