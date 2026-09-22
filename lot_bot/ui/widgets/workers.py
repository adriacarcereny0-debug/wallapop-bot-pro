"""Ejecucion de tareas largas fuera del hilo de la interfaz.

Sincronizar con Wallapop o consultar la IA puede tardar segundos. Si se hiciera
en el hilo grafico, la ventana se quedaria congelada. Estas clases ejecutan el
trabajo en segundo plano y devuelven el resultado a la interfaz.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str, str)
    done = Signal()


class _Task(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.signals = _Signals()
        self._function = function
        self._args = args
        self._kwargs = kwargs

    @Slot()
    def run(self) -> None:  # pragma: no cover - se ejecuta en otro hilo
        try:
            result = self._function(*self._args, **self._kwargs)
        except Exception as exc:
            logger.exception("Error en tarea en segundo plano")
            self.signals.failed.emit(_friendly_message(exc), traceback.format_exc())
        else:
            self.signals.finished.emit(result)
        finally:
            self.signals.done.emit()


class TaskRunner:
    """Lanza funciones en segundo plano y entrega el resultado a la interfaz."""

    def __init__(self, max_threads: int = 4) -> None:
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max_threads)

    def run(
        self,
        function: Callable[..., Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
        on_done: Callable[[], None] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        task = _Task(function, *args, **kwargs)
        if on_success is not None:
            task.signals.finished.connect(on_success)
        if on_error is not None:
            task.signals.failed.connect(on_error)
        if on_done is not None:
            task.signals.done.connect(on_done)
        self._pool.start(task)

    def wait(self, timeout_ms: int = 5000) -> bool:
        return self._pool.waitForDone(timeout_ms)


def _friendly_message(exc: Exception) -> str:
    """Traduce la excepcion a un mensaje entendible por el usuario."""
    from lot_bot.wallapop.errors import WallapopError

    if isinstance(exc, WallapopError):
        return exc.user_message
    if isinstance(exc, PermissionError):
        return str(exc)
    if isinstance(exc, ValueError):
        return str(exc)
    return f"Se ha producido un error inesperado ({type(exc).__name__}). Consulta la pantalla de Logs."
