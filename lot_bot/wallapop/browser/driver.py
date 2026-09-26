"""Control del navegador.

`BrowserPage` es la interfaz mínima que usa LOT Bot. `PlaywrightLauncher`
la implementa con Playwright; las pruebas usan una versión simulada, así que
ninguna prueba abre Wallapop.

Se lanza un navegador NORMAL y VISIBLE con el perfil de la cuenta. No se usa
ningún truco para ocultar que es un navegador automatizado, ni para evitar
CAPTCHA o verificaciones: si Wallapop pide algo, lo hace el usuario.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BrowserUnavailable(RuntimeError):
    """No hay Playwright o ningún navegador compatible instalado."""


class BrowserPage(ABC):
    @abstractmethod
    def goto(self, url: str) -> None: ...

    @abstractmethod
    def current_url(self) -> str: ...

    @abstractmethod
    def first_visible(self, targets: list[str], timeout_ms: int = 0) -> str | None:
        """Devuelve el primer selector visible (esperando hasta `timeout_ms`)."""

    @abstractmethod
    def fill(self, target: str, text: str) -> None: ...

    @abstractmethod
    def click(self, target: str) -> None: ...

    @abstractmethod
    def click_option(self, text: str, timeout_ms: int) -> bool:
        """Pulsa una opción visible con ese texto exacto (listas desplegables)."""

    @abstractmethod
    def set_files(self, target: str, paths: list[str]) -> None: ...

    @abstractmethod
    def text_of(self, target: str) -> str: ...

    @abstractmethod
    def links_matching(self, pattern: str) -> list[str]: ...

    def body_text(self) -> str:
        """Texto visible de la página (para leer estadísticas)."""
        return ""

    def is_alive(self) -> bool:
        """False si el usuario ha cerrado la ventana o la pestaña."""
        return True

    def value_of(self, target: str) -> str:
        """Lo que contiene un campo (input/textarea) o el texto de un elemento.

        Se usa para COMPROBAR el formulario antes de publicar.
        """
        return self.text_of(target)

    def count(self, target: str) -> int:
        """Cuántos elementos coinciden (p. ej. miniaturas de fotos cargadas)."""
        return 1 if self.first_visible([target], 0) else 0

    def diagnostics(self) -> dict[str, Any]:
        """Datos para diagnosticar fallos. Nunca cookies, contraseñas ni tokens."""
        return {}

    @abstractmethod
    def wait(self, ms: int) -> None: ...

    @abstractmethod
    def screenshot(self, path: Path) -> None: ...


class BrowserLauncher(ABC):
    @abstractmethod
    @contextmanager
    def open(
        self, profile_dir: Path, *, visible: bool, channels: list[str], locale: str
    ) -> Iterator[BrowserPage]: ...

    def available(self) -> tuple[bool, str]:
        return True, ""


# ---------------------------------------------------------------------------
# Implementación con Playwright
# ---------------------------------------------------------------------------
def safe_url(url: str) -> str:
    """URL sin parámetros ni fragmento (pueden llevar tokens)."""
    return re.split(r"[?#]", url or "", maxsplit=1)[0]


class _PlaywrightPage(BrowserPage):
    MAX_EVENTS = 15

    def __init__(self, page, default_timeout_ms: int, launch_info: str = "") -> None:
        self._page = page
        self._page.set_default_timeout(default_timeout_ms)
        self._launch_info = launch_info
        self._console_errors: list[str] = []
        self._network_errors: list[str] = []
        self._navigation_errors: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", lambda exc: self._add(self._console_errors, f"pageerror: {exc}"))
        page.on("requestfailed", self._on_request_failed)

    def _add(self, bucket: list[str], text: str) -> None:
        if len(bucket) < self.MAX_EVENTS:
            bucket.append(text[:300])

    def _on_console(self, message) -> None:
        try:
            if message.type == "error":
                self._add(self._console_errors, message.text)
        except Exception:
            pass

    def _on_request_failed(self, request) -> None:
        try:
            self._add(
                self._network_errors,
                f"{request.resource_type} {safe_url(request.url)} → {request.failure or 'fallo'}",
            )
        except Exception:
            pass

    def diagnostics(self) -> dict[str, Any]:
        try:
            javascript = self._page.evaluate("() => 1 + 1") == 2
        except Exception:
            javascript = None
        try:
            user_agent_version = self._page.evaluate(
                "() => (navigator.userAgent.match(/(Chrome|Edg)\\/[\\d.]+/g) || []).join(' ')"
            )
        except Exception:
            user_agent_version = "desconocida"
        return {
            "arranque": self._launch_info,
            "version": user_agent_version,
            "url": safe_url(self._page.url),
            "javascript": javascript,
            "errores_navegacion": list(self._navigation_errors),
            "errores_consola": list(self._console_errors),
            "errores_red": list(self._network_errors),
        }

    def goto(self, url: str) -> None:
        try:
            self._page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            self._add(self._navigation_errors, f"{safe_url(url)}: {str(exc).splitlines()[0]}")
            raise

    def current_url(self) -> str:
        return self._page.url

    def first_visible(self, targets: list[str], timeout_ms: int = 0) -> str | None:
        waited = 0
        step = 250
        while True:
            for target in targets:
                try:
                    if self._page.locator(target).first.is_visible():
                        return target
                except Exception:  # selector no válido en esta página
                    continue
            if waited >= timeout_ms:
                return None
            self._page.wait_for_timeout(step)
            waited += step

    def fill(self, target: str, text: str) -> None:
        locator = self._page.locator(target).first
        locator.click()
        locator.fill(text)

    def click(self, target: str) -> None:
        self._page.locator(target).first.click()

    def click_option(self, text: str, timeout_ms: int) -> bool:
        """Elige una opción de la lista desplegable abierta, en una sola espera."""
        pattern = re.compile(rf"^\s*{re.escape(text)}\s*$", re.IGNORECASE)
        options = self._page.locator(
            "[role=option], [role=menuitem], [role=menuitemradio], [role=radio], li, label"
        ).filter(has_text=pattern)
        try:
            options.first.wait_for(state="visible", timeout=timeout_ms)
            options.first.click()
            return True
        except Exception:
            pass
        try:
            self._page.get_by_text(pattern).first.click(timeout=min(timeout_ms, 3000))
            return True
        except Exception:
            return False

    def set_files(self, target: str, paths: list[str]) -> None:
        self._page.locator(target).first.set_input_files(paths)

    def is_alive(self) -> bool:
        try:
            return not self._page.is_closed() and bool(self._page.context.pages)
        except Exception:
            return False

    def value_of(self, target: str) -> str:
        locator = self._page.locator(target).first
        tag = (locator.evaluate("e => e.tagName") or "").lower()
        if tag in ("input", "textarea", "select"):
            return locator.input_value() or ""
        return (locator.inner_text() or "").strip()

    def count(self, target: str) -> int:
        try:
            return self._page.locator(target).count()
        except Exception:
            return 0

    def text_of(self, target: str) -> str:
        return (self._page.locator(target).first.inner_text() or "").strip()

    def body_text(self) -> str:
        try:
            return self._page.inner_text("body") or ""
        except Exception:
            return ""

    def links_matching(self, pattern: str) -> list[str]:
        regex = re.compile(pattern)
        hrefs = self._page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        return [h for h in hrefs if regex.search(h or "")]

    def wait(self, ms: int) -> None:
        self._page.wait_for_timeout(ms)

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(path))


#: Opciones que Playwright añade por defecto y que REDUCEN la seguridad del
#: navegador sin que LOT Bot las necesite. Se quitan para que el navegador
#: funcione como uno normal. No se toca nada relacionado con la detección de
#: automatización: el aviso «controlado por software automatizado» se mantiene.
UNSAFE_DEFAULT_ARGS = [
    "--disable-client-side-phishing-detection",  # protección contra phishing
    "--disable-popup-blocking",  # bloqueo de ventanas emergentes
    "--disable-component-update",  # actualización de componentes de seguridad
    "--unsafely-disable-devtools-self-xss-warnings",
]

#: Nunca se pasan (ni en Windows ni en ningún otro sistema salvo que el
#: desarrollador lo pida expresamente en Linux).
FORBIDDEN_ARGS = {"--no-sandbox", "--disable-setuid-sandbox", "--no-zygote", "--single-process"}


@dataclass(slots=True)
class BrowserCandidate:
    """Un navegador que se puede intentar abrir."""

    name: str
    channel: str | None = None
    executable: str | None = None

    def describe(self) -> str:
        return f"{self.name} ({self.executable or self.channel or 'Chromium de Playwright'})"


def windows_browser_paths(env: dict[str, str] | None = None) -> list[tuple[str, Path]]:
    """Rutas habituales de Chrome y Edge en Windows."""
    env = env if env is not None else dict(os.environ)
    roots = [env.get("PROGRAMFILES"), env.get("PROGRAMFILES(X86)"), env.get("LOCALAPPDATA")]
    candidates: list[tuple[str, Path]] = []
    for name, relative in (
        ("Google Chrome", Path("Google/Chrome/Application/chrome.exe")),
        ("Microsoft Edge", Path("Microsoft/Edge/Application/msedge.exe")),
    ):
        for root in roots:
            if root:
                candidates.append((name, Path(root) / relative))
    return candidates


def find_browsers(
    channels: list[str],
    *,
    platform: str | None = None,
    env: dict[str, str] | None = None,
    exists=lambda p: Path(p).is_file(),
) -> list[BrowserCandidate]:
    """Navegadores a probar, en orden. Chrome y Edge instalados primero."""
    platform = platform or sys.platform
    env = env if env is not None else dict(os.environ)
    explicit = env.get("LOT_BOT_BROWSER_EXECUTABLE", "").strip()
    if explicit:
        return [BrowserCandidate("Navegador indicado", executable=explicit)]
    found: list[BrowserCandidate] = []
    if platform.startswith("win"):
        seen: set[str] = set()
        for name, path in windows_browser_paths(env):
            if name not in seen and exists(path):
                found.append(BrowserCandidate(name, executable=str(path)))
                seen.add(name)
    labels = {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}
    for channel in channels:
        if channel == "chromium":
            found.append(BrowserCandidate("Chromium de Playwright"))
        elif labels.get(channel) not in {c.name for c in found}:
            found.append(BrowserCandidate(labels.get(channel, channel), channel=channel))
    return found


def order_candidates(
    candidates: list[BrowserCandidate], marker: str | None
) -> list[BrowserCandidate]:
    """Si el perfil ya se creó con un navegador, SOLO se usa ese.

    Abrir un perfil de Chrome con Edge (o al revés) da un perfil sin sesión:
    las cookies van cifradas para el navegador que las creó.
    """
    if not marker:
        return candidates
    same = [c for c in candidates if c.name == marker]
    return same or candidates


def sandbox_enabled(platform: str | None = None, env: dict[str, str] | None = None) -> bool:
    """El sandbox de Chromium SIEMPRE activado en Windows y macOS.

    Solo en Linux (desarrollo o contenedores sin espacios de nombres) se
    puede desactivar a propósito con LOT_BOT_BROWSER_SANDBOX=0.
    """
    platform = platform or sys.platform
    env = env if env is not None else dict(os.environ)
    if platform.startswith("linux") and env.get("LOT_BOT_BROWSER_SANDBOX", "").strip() == "0":
        return False
    return True


def build_launch_options(
    candidate: BrowserCandidate,
    profile_dir: Path,
    *,
    visible: bool,
    locale: str,
    platform: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Opciones de `launch_persistent_context`: perfil propio y persistente,
    ventana normal (ni invitado ni incógnito) y sandbox activado."""
    options: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": not visible,
        "locale": locale,
        "no_viewport": True,
        # Sin esto, Playwright añade «--no-sandbox».
        "chromium_sandbox": sandbox_enabled(platform, env),
        "ignore_default_args": list(UNSAFE_DEFAULT_ARGS),
        "args": [],
    }
    if candidate.executable:
        options["executable_path"] = candidate.executable
    elif candidate.channel:
        options["channel"] = candidate.channel
    assert not FORBIDDEN_ARGS & set(options["args"])
    return options


def describe_launch(candidate: BrowserCandidate, options: dict[str, Any]) -> str:
    """Resumen para el registro: navegador, ruta, perfil y argumentos. Sin datos
    sensibles (el perfil es una carpeta; nunca se leen cookies ni contraseñas)."""
    return (
        f"navegador={candidate.name}; ejecutable={candidate.executable or '-'}; "
        f"canal={candidate.channel or '-'}; perfil={options['user_data_dir']}; "
        f"visible={not options['headless']}; sandbox={options['chromium_sandbox']}; "
        f"args={options['args']}; quitados={options['ignore_default_args']}"
    )


class PlaywrightLauncher(BrowserLauncher):
    """Abre Chrome/Edge/Chromium con un perfil persistente por cuenta."""

    def __init__(self, default_timeout_ms: int = 20000) -> None:
        self._timeout = default_timeout_ms

    def available(self) -> tuple[bool, str]:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False, (
                "Falta el componente de navegador (Playwright). En el entorno de desarrollo: "
                "pip install playwright"
            )
        return True, ""

    @contextmanager
    def open(
        self, profile_dir: Path, *, visible: bool, channels: list[str], locale: str
    ) -> Iterator[BrowserPage]:
        ok, message = self.available()
        if not ok:
            raise BrowserUnavailable(message)
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        from lot_bot.wallapop.browser.profiles import (
            profile_locked,
            read_browser_marker,
            write_browser_marker,
        )
        from lot_bot.wallapop.errors import ProfileInUseError

        profile_dir = Path(profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        # CAUSA DEL FALLO «abre la ventana pero no publica»: si el Chrome normal
        # de la cuenta (abierto con «Abrir cuenta» o al iniciar sesión) sigue
        # abierto, Chrome entrega la orden a esa ventana —que muestra la cuenta—
        # y el navegador que lanza Playwright se cierra al momento: LOT Bot se
        # queda sin página que controlar. Se detecta ANTES de lanzar nada.
        if profile_locked(profile_dir):
            raise ProfileInUseError(f"Perfil en uso: {profile_dir}")
        candidates = order_candidates(find_browsers(channels), read_browser_marker(profile_dir))
        with sync_playwright() as pw:
            context = None
            errors: list[str] = []
            for candidate in candidates:
                options = build_launch_options(
                    candidate, profile_dir, visible=visible, locale=locale
                )
                try:
                    context = pw.chromium.launch_persistent_context(**options)
                    logger.info("Navegador abierto: %s", describe_launch(candidate, options))
                    write_browser_marker(profile_dir, candidate.name)
                    break
                except PlaywrightError as exc:
                    if profile_locked(profile_dir):
                        raise ProfileInUseError(f"Perfil en uso: {profile_dir}") from exc
                    detail = str(exc).splitlines()[0][:300]
                    logger.error(
                        "No se ha podido abrir el navegador. %s; error=%s",
                        describe_launch(candidate, options),
                        detail,
                    )
                    errors.append(f"{candidate.describe()}: {detail[:120]}")
            if context is None:
                raise BrowserUnavailable(
                    "No se ha podido abrir ningún navegador (Chrome, Edge o Chromium). "
                    "Los detalles están en la pantalla «Logs y errores». "
                    + " | ".join(errors)
                )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                yield _PlaywrightPage(page, self._timeout, describe_launch(candidate, options))
            finally:
                try:
                    context.close()
                except Exception:  # pragma: no cover
                    pass
