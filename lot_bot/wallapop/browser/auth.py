"""Conexión de una cuenta mediante el navegador.

1. LOT Bot abre un navegador con un perfil NUEVO y exclusivo de la cuenta.
2. El usuario inicia sesión en Wallapop él mismo (y completa cualquier
   verificación que Wallapop pida).
3. LOT Bot detecta que la sesión está iniciada y cierra el navegador.
4. La interfaz pide al usuario que confirme que quiere conectar esa cuenta.

LOT Bot no ve ni guarda la contraseña: la sesión queda dentro del perfil del
navegador de esa cuenta, en la carpeta de datos del usuario.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
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
from lot_bot.wallapop.browser.service import BrowserWallapopService

logger = logging.getLogger(__name__)

AUTHORIZED_USE_NOTE = (
    "Cuenta de Wallapop conectada para el uso personal autorizado del titular de "
    "LOT Bot. No es una integración oficial de Wallapop ni una autorización transferible."
)


@dataclass(slots=True)
class LoginResult:
    ok: bool
    login: str = ""
    message: str = ""


def profiles_lock(method: BrowserSessionAuthMethod, account_ref: str):
    return method.service.profiles.lock(account_ref)


class BrowserSessionAuthMethod(AuthMethod):
    kind = AuthKind.BROWSER_SESSION
    display_name = "Sesión en navegador (uso personal autorizado)"
    description = (
        "Se abre un navegador y tú inicias sesión en Wallapop. LOT Bot no ve ni "
        "guarda tu contraseña; la sesión se queda en un perfil de navegador propio "
        "de cada cuenta."
    )
    interactive = True

    def __init__(self, service: BrowserWallapopService, login_timeout: float = 600.0) -> None:
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

    def wait_for_login(
        self,
        account_ref: str,
        *,
        on_status: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> LoginResult:
        """Abre el navegador y espera a que el usuario inicie sesión."""
        notify = on_status or (lambda _msg: None)
        profiles = self.service.profiles
        site = self.service.site
        try:
            with profiles.lock(account_ref), self.service.launcher.open(
                profiles.profile_dir(account_ref),
                visible=True,
                channels=site.channels,
                locale=site.locale,
            ) as page:
                page.goto(site.url("inicio"))
                notify("Inicia sesión en Wallapop en la ventana del navegador.")
                deadline = time.monotonic() + self.login_timeout
                while time.monotonic() < deadline:
                    if should_stop and should_stop():
                        return LoginResult(False, message="Cancelado por el usuario.")
                    try:
                        state = self.service.session_state(page, timeout_ms=1500)
                    except Exception:
                        return LoginResult(
                            False, message="Se ha cerrado el navegador antes de terminar."
                        )
                    if state == "iniciada":
                        login = ""
                        found = page.first_visible(site.user_name, 0) if site.user_name else None
                        if found:
                            try:
                                login = page.text_of(found)[:120]
                            except Exception:
                                login = ""
                        return LoginResult(True, login=login, message="Sesión detectada.")
                    if state == "verificacion":
                        notify("Wallapop pide una verificación: complétala en el navegador.")
                    page.wait(1500)
                return LoginResult(False, message="No se ha detectado el inicio de sesión a tiempo.")
        except BrowserUnavailable as exc:
            return LoginResult(False, message=str(exc))

    def open_for_user(self, account_ref: str, max_seconds: float = 1800.0) -> str:
        """Abre el navegador de la cuenta para que el usuario haga algo a mano
        (p. ej. completar una verificación). Vuelve cuando lo cierra."""
        site = self.service.site
        try:
            with profiles_lock(self, account_ref), self.service.launcher.open(
                self.service.profiles.profile_dir(account_ref),
                visible=True,
                channels=site.channels,
                locale=site.locale,
            ) as page:
                page.goto(site.url("inicio"))
                deadline = time.monotonic() + max_seconds
                while time.monotonic() < deadline:
                    try:
                        page.wait(1000)
                        page.current_url()
                    except Exception:
                        break
            return "Navegador cerrado."
        except BrowserUnavailable as exc:
            return str(exc)

    def authenticate(self, account_ref: str, **context: Any) -> AuthOutcome:
        """`login_detected=True` cuando la interfaz ya ha esperado el inicio de
        sesión y el usuario lo ha confirmado. Sin él, se espera aquí."""
        login = str(context.get("login") or "")
        if not context.get("login_detected"):
            result = self.wait_for_login(account_ref)
            if not result.ok:
                return AuthOutcome(success=False, message=result.message)
            login = result.login
        if not self.service.profiles.exists(account_ref):
            return AuthOutcome(success=False, message="No hay sesión de navegador para esta cuenta.")
        return AuthOutcome(
            success=True,
            credential=AuthCredential(
                kind=AuthKind.BROWSER_SESSION,
                metadata={
                    "account_ref": account_ref,
                    "login": login or None,
                    "uso": AUTHORIZED_USE_NOTE,
                },
            ),
            message="Cuenta conectada mediante el navegador.",
        )

    def revoke(self, credential: AuthCredential) -> bool:
        ref = credential.metadata.get("account_ref")
        return bool(ref) and self.service.profiles.delete(str(ref))
