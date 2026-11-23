"""Ejecución de tareas largas fuera del hilo de la interfaz."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal

from app.core.document_exporter import ExportError
from app.core.document_loader import LoadError
from app.core.rule_engine import CatalogError, RuleError
from app.formats.docx_handler import DocxError

log = logging.getLogger(__name__)
_EXPECTED_ERRORS = (LoadError, DocxError, ExportError, RuleError, CatalogError)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, _EXPECTED_ERRORS):
        return str(exc)
    return f"Error inesperado ({type(exc).__name__}): {exc}\n\nLos detalles se guardaron en el registro de la aplicación."


class TaskRunner(QObject):
    """Ejecuta una tarea a la vez en segundo plano y entrega el resultado en el hilo de la interfaz."""

    busyChanged = Signal(bool, str)
    _finished = Signal(object, object)  # (callback, valor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        # Conexión en cola: el callback siempre se ejecuta en el hilo de este objeto (la interfaz).
        self._finished.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, job: Callable[[], object], on_done: Callable, on_error: Callable[[str], None], message: str) -> bool:
        if self._busy:
            return False
        self._busy = True
        self.busyChanged.emit(True, message)

        def work():
            try:
                result = job()
            except Exception as exc:  # se informa al usuario; nunca se cierra la aplicación
                log.exception("La tarea «%s» falló", message)
                self._finished.emit(on_error, friendly_error(exc))
                return
            self._finished.emit(on_done, result)

        self._pool.start(work)
        return True

    def _dispatch(self, callback, value) -> None:
        self._busy = False
        self.busyChanged.emit(False, "")
        callback(value)

    def wait(self) -> None:
        self._pool.waitForDone()
