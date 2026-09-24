"""Conexión de una cuenta mediante el navegador.

Flujo (sin atajos):

1. LOT Bot abre un navegador VISIBLE con el perfil PERSISTENTE y exclusivo de
   la cuenta, y lo deja abierto.
2. El usuario inicia sesión en Wallapop él mismo (y completa cualquier
   verificación que Wallapop pida). LOT Bot no toca la página mientras tanto.
3. El usuario pulsa «Ya he iniciado sesión» en LOT Bot.
4. LOT Bot hace una comprobación REAL (`verify_session`): página privada sin
   redirección, sin botón de acceso, sin verificación y con contenido privado.
5. Solo si se cumple todo, la interfaz pide confirmación y la cuenta se marca
   como conectada. Abrir el navegador NO conecta nada.

LOT Bot no ve ni guarda la contraseña: la sesión queda dentro del perfil del
navegador de esa cuenta, en la carpeta de datos del usuario.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from lot_bot.wallapop.auth.base import (
    AuthCredential,
    AuthKind,
    AuthMethod,
    AuthOutcome,
    AuthRequirement,
    RequirementSource,
)
from lot_bot.wallapop.browser.driver import BrowserUnavailable
from lot_bot.wallapop.browser.service import BrowserWallapopService, SessionCheck

logger = logging.getLogger(__name__)

AUTHORIZED_USE_NOTE = (
    "Cuenta de Wallapop conectada para el uso personal autorizado del titular de "
    "LOT Bot. No es una integración oficial de Wallapop ni una autorización transferible."
)


class LoginSession:
    """Navegador abierto para que el usuario inicie sesión en una cuenta.

    Todo lo que toca el navegador ocurre en el hilo propio de la sesión; la
    interfaz solo envía órdenes («comprobar», «cerrar») y lee el estado.
    """

    OPENING = "abriendo"
    WAITING = "esperando_usuario"
    CHECKING = "comprobando"
    VERIFIED = "sesion_comprobada"
    NOT_LOGGED = "sin_sesion"
    VERIFICATION = "verificacion"
    UNKNOWN = "desconocido"
    CLOSED = "cerrado"
    ERROR = "error"

    def __init__(self, service: BrowserWallapopService, account_ref: str, timeout: float = 1800.0):
        self.service = service
        self.account_ref = account_ref
        self._timeout = timeout
        self._commands: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._state = self.OPENING
        self._message = "Abriendo el navegador…"
        self.check: SessionCheck | None = None
        self._thread: threading.Thread | None = None

    # -- Estado ------------------------------------------------------------
    def _set(self, state: str, message: str) -> None:
        with self._changed:
            self._state = state
            self._message = message
            self._changed.notify_all()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    @property
    def verified(self) -> bool:
        return self.check is not None and self.check.ok

    def wait_for(self, *states: str, timeout: float = 10.0) -> str:
        """Espera a que el estado sea uno de `states` (útil en pruebas)."""
        deadline = time.monotonic() + timeout
        with self._changed:
            while self._state not in states:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._changed.wait(remaining)
            return self._state

    # -- Órdenes -----------------------------------------------------------
    def start(self) -> LoginSession:
        # Chrome no permite abrir el mismo perfil dos veces.
        self.service.release(self.account_ref)
        self._thread = threading.Thread(
            target=self._run, name=f"lotbot-login-{self.account_ref}", daemon=True
        )
        self._thread.start()
        return self

    def request_check(self) -> None:
        self._commands.put("check")

    def close(self, wait: float = 10.0) -> None:
        self._commands.put("close")
        if self._thread is not None:
            self._thread.join(wait)

    # -- Hilo del navegador -----------------------------------------------
    def _run(self) -> None:
        site = self.service.site
        try:
            with self.service.profiles.lock(self.account_ref), self.service.launcher.open(
                self.service.profiles.profile_dir(self.account_ref),
                visible=True,
                channels=site.channels,
                locale=site.locale,
            ) as page:
                page.goto(site.url("inicio"))
                self._set(
                    self.WAITING,
                    "Inicia sesión en Wallapop en la ventana del navegador. Cuando termines, "
                    "pulsa «Ya he iniciado sesión».",
                )
                deadline = time.monotonic() + self._timeout
                while time.monotonic() < deadline:
                    try:
                        command = self._commands.get(timeout=1.0)
                    except queue.Empty:
                        try:
                            page.current_url()  # ¿sigue abierto?
                        except Exception:
                            self._set(self.CLOSED, "Se ha cerrado el navegador.")
                            return
                        continue
                    if command == "close":
                        break
                    if command == "check":
                        self._set(self.CHECKING, "Comprobando la sesión en Wallapop…")
                        try:
                            result = self.service.verify_session(page)
                        except Exception as exc:
                            result = SessionCheck(False, "error", f"Error al comprobar ({type(exc).__name__}).")
                        self.check = result
                        if result.ok:
                            self._set(self.VERIFIED, "Sesión comprobada correctamente.")
                        elif result.state == "verificacion":
                            self._set(
                                self.VERIFICATION,
                                "Wallapop pide una verificación. Complétala tú en el navegador y "
                                "vuelve a pulsar «Ya he iniciado sesión».",
                            )
                        elif result.state == "sin_sesion":
                            self._set(
                                self.NOT_LOGGED,
                                f"Todavía no hay sesión iniciada. {result.message} Inicia sesión "
                                "en el navegador y vuelve a pulsar «Ya he iniciado sesión».",
                            )
                        else:
                            self._set(self.UNKNOWN, result.message)
                else:
                    self._set(self.CLOSED, "Tiempo agotado: se ha cerrado el navegador.")
                    return
            if self.state not in (self.VERIFIED,):
                self._set(self.CLOSED, "Navegador cerrado.")
        except BrowserUnavailable as exc:
            self._set(self.ERROR, str(exc))
        except Exception as exc:  # pragma: no cover - errores inesperados del navegador
            logger.exception("Error en el inicio de sesión")
            self._set(self.ERROR, f"Error del navegador ({type(exc).__name__}).")


class BrowserSessionAuthMethod(AuthMethod):
    kind = AuthKind.BROWSER_SESSION
    display_name = "Sesión en navegador (uso personal autorizado)"
    description = (
        "Se abre un navegador y tú inicias sesión en Wallapop. LOT Bot no ve ni "
        "guarda tu contraseña; la sesión se queda en un perfil de navegador propio "
        "de cada cuenta."
    )
    interactive = True

    def __init__(self, service: BrowserWallapopService, login_timeout: float = 1800.0) -> None:
        self.service = service
        self.login_timeout = login_timeout

    def requirements(self) -> list[AuthRequirement]:
        ok, message = self.service.launcher.available()
        return [
            AuthRequirement(
                key="navegador",
                label="Componente de navegador",
                description=message or "Playwright y un navegador Chrome, Edge o Chromium.",
                source=RequirementSource.INSTALACION,
                satisfied=ok,
                where="Instalación de LOT Bot",
            )
        ]

    def start_login(self, account_ref: str) -> LoginSession:
        return LoginSession(self.service, account_ref, self.login_timeout).start()

    def check(self, account_ref: str) -> SessionCheck:
        return self.service.check_session(account_ref)

    def open_for_user(self, account_ref: str, max_seconds: float = 1800.0) -> str:
        """Abre el navegador de la cuenta para que el usuario haga algo a mano
        (p. ej. completar una verificación). Vuelve cuando lo cierra."""
        session = LoginSession(self.service, account_ref, max_seconds).start()
        session.wait_for(LoginSession.CLOSED, LoginSession.ERROR, timeout=max_seconds + 5)
        return session.message

    def authenticate(self, account_ref: str, **context: Any) -> AuthOutcome:
        """Solo conecta con una comprobación REAL de la sesión ya hecha.

        `session_check` debe ser el `SessionCheck` correcto devuelto por
        `LoginSession` (o `check`). Sin él, no se conecta nada.
        """
        check = context.get("session_check")
        if not isinstance(check, SessionCheck) or not check.ok:
            return AuthOutcome(
                success=False,
                message="No se ha comprobado que haya una sesión iniciada en Wallapop. "
                "Usa «Añadir cuenta» o «Reconectar» e inicia sesión en el navegador.",
            )
        if not self.service.profiles.exists(account_ref):
            return AuthOutcome(success=False, message="No hay sesión de navegador para esta cuenta.")
        return AuthOutcome(
            success=True,
            credential=AuthCredential(
                kind=AuthKind.BROWSER_SESSION,
                metadata={
                    "account_ref": account_ref,
                    "login": check.login or None,
                    "uso": AUTHORIZED_USE_NOTE,
                },
            ),
            message="Cuenta conectada: sesión comprobada en Wallapop.",
        )

    def revoke(self, credential: AuthCredential) -> bool:
        ref = credential.metadata.get("account_ref")
        if not ref:
            return False
        self.service.release(str(ref))
        return self.service.profiles.delete(str(ref))
