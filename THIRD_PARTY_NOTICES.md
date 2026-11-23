# Componentes de terceros

Estandria usa los siguientes componentes. Cada uno conserva su licencia; la licencia de Estandria
(`LICENSE.md`) solo cubre el código propio del proyecto.

| Componente | Versión | Licencia | Uso |
|---|---|---|---|
| [Qt for Python (PySide6-Essentials, shiboken6)](https://www.qt.io/qt-for-python) | 6.12.0 | LGPL-3.0 (también disponible bajo GPL-2.0/GPL-3.0) | Interfaz gráfica |
| [Qt](https://www.qt.io/) (bibliotecas incluidas en PySide6) | 6.12 | LGPL-3.0 | Interfaz gráfica |
| [python-docx](https://github.com/python-openxml/python-docx) | 1.2.0 | MIT | Lectura y escritura de DOCX |
| [lxml](https://lxml.de/) (incluye libxml2 y libxslt) | 6.1.3 | BSD-3-Clause (libxml2/libxslt: MIT) | Procesamiento XML |
| [typing_extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 | Dependencia de python-docx |
| [Python](https://www.python.org/) (intérprete incluido en el ejecutable) | 3.13 | PSF-2.0 | Entorno de ejecución |
| [PyInstaller](https://pyinstaller.org/) (cargador del ejecutable) | 6.22 | GPL-2.0 con excepción para el cargador, que permite distribuir el ejecutable con cualquier licencia | Empaquetado |

## Qt y PySide6 (LGPL-3.0)

Qt y PySide6 se usan sin modificaciones y se enlazan dinámicamente. En la distribución recomendada
(`onedir`, carpeta `Estandria\`), sus bibliotecas son archivos independientes dentro de `_internal\`
que pueden reemplazarse por otras versiones compatibles, como exige la LGPL. El código fuente de Qt y
PySide6 está disponible en <https://download.qt.io/> y <https://code.qt.io/>.

Los textos completos de la LGPL-3.0 y de la GPL-3.0 (a la que la LGPL remite) se incluyen en la carpeta
`licenses/` y en el ejecutable.
