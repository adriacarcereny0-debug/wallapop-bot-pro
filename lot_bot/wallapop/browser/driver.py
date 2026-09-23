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
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
class _PlaywrightPage(BrowserPage):
    def __init__(self, page, default_timeout_ms: int) -> None:
        self._page = page
        self._page.set_default_timeout(default_timeout_ms)

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")

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
        pattern = re.compile(rf"^\s*{re.escape(text)}\s*$", re.IGNORECASE)
        for role in ("option", "menuitem", "listitem", "button", "link"):
            locator = self._page.get_by_role(role, name=pattern)
            try:
                locator.first.wait_for(state="visible", timeout=min(timeout_ms, 3000))
                locator.first.click()
                return True
            except Exception:
                continue
        try:
            self._page.get_by_text(pattern).first.click(timeout=timeout_ms)
            return True
        except Exception:
            return False

    def set_files(self, target: str, paths: list[str]) -> None:
        self._page.locator(target).first.set_input_files(paths)

    def text_of(self, target: str) -> str:
        return (self._page.locator(target).first.inner_text() or "").strip()

    def links_matching(self, pattern: str) -> list[str]:
        regex = re.compile(pattern)
        hrefs = self._page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        return [h for h in hrefs if regex.search(h or "")]

    def wait(self, ms: int) -> None:
        self._page.wait_for_timeout(ms)

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(path))


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

        with sync_playwright() as pw:
            context = None
            errors: list[str] = []
            # Ruta explícita a un navegador (Chrome instalado en otra carpeta).
            executable = os.environ.get("LOT_BOT_BROWSER_EXECUTABLE", "").strip()
            if executable:
                channels = ["__ruta__"]
            for channel in channels:
                try:
                    kwargs = {
                        "user_data_dir": str(profile_dir),
                        "headless": not visible,
                        "locale": locale,
                        "no_viewport": True,
                    }
                    if channel == "__ruta__":
                        kwargs["executable_path"] = executable
                    elif channel != "chromium":
                        kwargs["channel"] = channel
                    context = pw.chromium.launch_persistent_context(**kwargs)
                    logger.info("Navegador abierto (%s).", channel)
                    break
                except PlaywrightError as exc:
                    errors.append(f"{channel}: {str(exc).splitlines()[0][:120]}")
            if context is None:
                raise BrowserUnavailable(
                    "No se ha podido abrir ningún navegador (Chrome, Edge o Chromium). "
                    + " | ".join(errors)
                )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                yield _PlaywrightPage(page, self._timeout)
            finally:
                try:
                    context.close()
                except Exception:  # pragma: no cover
                    pass
