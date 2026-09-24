"""Navegadores abiertos por cuenta, reutilizados entre publicaciones.

Cada cuenta tiene UN hilo propio que abre su perfil persistente y lo mantiene
abierto mientras se usa: publicar 50 anuncios en la cuenta B abre el
navegador de B una sola vez y reutiliza su sesión. Tras un tiempo sin uso se
cierra solo (las cookies quedan guardadas en el perfil).

Playwright exige que todo lo relacionado con un navegador se haga desde el
hilo que lo abrió; por eso cada cuenta tiene su hilo y las operaciones se le
envían como funciones `fn(page)`.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from lot_bot.wallapop.browser.driver import BrowserLauncher, BrowserPage

logger = logging.getLogger(__name__)

_STOP = object()


class _AccountWorker:
    def __init__(
        self,
        ref: str,
        launcher: BrowserLauncher,
        profile_dir: Path,
        options: dict[str, Any],
        idle_seconds: float,
        on_exit: Callable[[str, _AccountWorker], None],
    ) -> None:
        self.ref = ref
        self._launcher = launcher
        self._profile = profile_dir
        self._options = options
        self._idle = idle_seconds
        self._on_exit = on_exit
        self._jobs: queue.Queue = queue.Queue()
        self.opened = False
        self._thread = threading.Thread(target=self._run, name=f"lotbot-nav-{ref}", daemon=True)
        self._thread.start()

    def submit(self, fn: Callable[[BrowserPage], Any]) -> Future:
        future: Future = Future()
        self._jobs.put((fn, future))
        return future

    def stop(self) -> None:
        self._jobs.put(_STOP)

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)

    def _fail_pending(self, exc: BaseException) -> None:
        while True:
            try:
                item = self._jobs.get_nowait()
            except queue.Empty:
                return
            if item is not _STOP:
                item[1].set_exception(exc)

    def _run(self) -> None:
        try:
            first = self._jobs.get()
            if first is _STOP:
                return
            try:
                with self._launcher.open(self._profile, **self._options) as page:
                    self.opened = True
                    item = first
                    while item is not _STOP:
                        fn, future = item
                        if future.set_running_or_notify_cancel():
                            try:
                                future.set_result(fn(page))
                            except BaseException as exc:  # se entrega al que espera
                                future.set_exception(exc)
                        try:
                            item = self._jobs.get(timeout=self._idle)
                        except queue.Empty:
                            logger.info("Navegador de %s cerrado por inactividad.", self.ref)
                            break
            except BaseException as exc:  # no se pudo abrir el navegador
                if not first[1].done():
                    first[1].set_exception(exc)
                self._fail_pending(exc)
        finally:
            self._on_exit(self.ref, self)


class BrowserSessionPool:
    def __init__(self, launcher: BrowserLauncher, idle_seconds: float = 900.0) -> None:
        self._launcher = launcher
        self._idle = idle_seconds
        self._workers: dict[str, _AccountWorker] = {}
        self._lock = threading.Lock()
        #: Veces que se ha abierto un navegador por cuenta (diagnóstico/pruebas).
        self.open_count: dict[str, int] = {}

    def _exit(self, ref: str, worker: _AccountWorker) -> None:
        with self._lock:
            if self._workers.get(ref) is worker:
                del self._workers[ref]

    def run(
        self,
        ref: str,
        profile_dir: Path,
        fn: Callable[[BrowserPage], Any],
        *,
        timeout: float | None = None,
        **options: Any,
    ) -> Any:
        """Ejecuta `fn(page)` en el navegador de la cuenta (lo abre si hace falta)."""
        with self._lock:
            worker = self._workers.get(ref)
            if worker is None:
                worker = _AccountWorker(
                    ref, self._launcher, profile_dir, options, self._idle, self._exit
                )
                self._workers[ref] = worker
                self.open_count[ref] = self.open_count.get(ref, 0) + 1
            future = worker.submit(fn)
        return future.result(timeout)

    def is_open(self, ref: str) -> bool:
        with self._lock:
            return ref in self._workers

    def close(self, ref: str, timeout: float = 10.0) -> None:
        """Cierra el navegador de una cuenta (antes de borrar su perfil o de
        abrirlo para iniciar sesión: Chrome no deja usar un perfil dos veces)."""
        with self._lock:
            worker = self._workers.pop(ref, None)
        if worker is not None:
            worker.stop()
            worker.join(timeout)

    def close_all(self, timeout: float = 10.0) -> None:
        with self._lock:
            refs = list(self._workers)
        for ref in refs:
            self.close(ref, timeout)
