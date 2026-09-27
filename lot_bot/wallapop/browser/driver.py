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
import time
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
    def click_option(
        self, text: str, timeout_ms: int, opener: str | None = None, opener_box: dict | None = None
    ) -> bool:
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

    def is_checked(self, target: str) -> bool:
        """Estado de un interruptor/casilla."""
        return False

    def press(self, key: str) -> None:
        """Pulsa una tecla (p. ej. «Escape» para cerrar una lista abierta)."""
        return None

    def set_checked(self, target: str, value: bool) -> None:
        """Deja una casilla/interruptor marcado o no (vale con su etiqueta)."""
        if self.is_checked(target) != value:
            self.click(target)

    def type_text(self, target: str, text: str) -> None:
        """Escribe tecla a tecla (para buscadores que sugieren al escribir),
        sin hacer clic (una barra fija podría tapar el campo)."""
        self.fill(target, text)

    # --- Piezas para el selector de categoría (category.py) ---
    def bbox(self, target: str) -> dict | None:
        """Posición del elemento en pantalla (x, y, width, height)."""
        return None

    def text_candidates(
        self, text: str, within: str | None = None, field: str | None = None
    ) -> list[dict]:
        """Elementos cuyo texto es EXACTAMENTE `text` (dentro de `within` si se
        indica): [{index, visible, enabled, box, previo, en_campo}]. `en_campo`:
        el elemento está dentro del campo `field` (el propio desplegable)."""
        return [{"index": 0, "visible": True, "enabled": True, "box": None}]

    def click_text(self, text: str, index: int, within: str | None = None) -> None:
        """Pulsa la FILA (opción) que contiene el texto número `index`."""
        if not self.click_option(text, 0):
            raise RuntimeError(f"No se ha podido pulsar «{text}».")

    def outer_html(self, target: str, limit: int = 20000) -> str:
        """HTML de un elemento (para diagnóstico; sin cookies ni tokens)."""
        return ""

    def click_suggestion(self, text: str, timeout_ms: int) -> bool:
        """Pulsa la primera sugerencia visible que CONTIENE `text` (p. ej. al
        escribir «Madrid» aparece «Madrid, Madrid»)."""
        return self.click_option(text, timeout_ms)

    def mark_existing(self, texts: list[str]) -> int:
        """Marca los elementos con esos textos que YA están en la página antes
        de abrir una lista: nunca serán opciones de esa lista."""
        return 0

    def unmark_existing(self) -> None:
        return None

    def attached(self, target: str) -> int:
        """Elementos que EXISTEN en la página, aunque estén ocultos."""
        return self.count(target)

    def upload_with_chooser(self, button: str, paths: list[str], timeout_ms: int) -> None:
        """Pulsa `button` y entrega los archivos en la ventana «Abrir archivo»."""
        self.click(button)

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


def _inside(box: dict, outer: dict) -> bool:
    """¿El centro de `box` cae dentro de `outer`? (coordenadas de pantalla)"""
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    return (
        outer["x"] <= cx <= outer["x"] + outer["width"]
        and outer["y"] <= cy <= outer["y"] + outer["height"]
    )


_ACCENTS = {"a": "aáàä", "e": "eéèë", "i": "iíìï", "o": "oóòö", "u": "uúùü", "n": "nñ"}


def _plain(text: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    ).casefold()


def tolerant_pattern(text: str) -> re.Pattern:
    """Texto EXACTO, pero sin importar mayúsculas, tildes ni el plural de cada
    palabra: «Estructuras de camas» encuentra «Estructura de camas»."""
    words = []
    for word in _plain(text).split():
        stem = word[:-2] if word.endswith("es") and len(word) > 4 else word
        stem = stem[:-1] if stem.endswith("s") and len(stem) > 3 else stem
        chars = "".join(f"[{_ACCENTS[c]}]" if c in _ACCENTS else re.escape(c) for c in stem)
        words.append(chars + "(?:e?s)?")
    return re.compile(r"^\s*" + r"\s+".join(words) + r"\s*$", re.IGNORECASE)


def same_text(a: str, b: str) -> bool:
    return bool(tolerant_pattern(a).match(" ".join((b or "").split())))


def contains_text(needle: str, haystack: str) -> bool:
    """¿`haystack` contiene `needle` (con la misma tolerancia)?"""
    pattern = tolerant_pattern(needle).pattern.strip("^$").replace(r"^\s*", "").replace(r"\s*$", "")
    return bool(re.search(pattern, _plain(" ".join((haystack or "").split())), re.IGNORECASE))


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
        """Escribe `text` SUSTITUYENDO lo que hubiera (p. ej. la descripción que
        ha generado la IA de Wallapop). No hace clic antes: si una lista
        desplegable quedara encima del campo, el clic se bloquearía."""
        locator = self._page.locator(target).first
        locator.scroll_into_view_if_needed(timeout=5000)
        try:
            kind = (locator.get_attribute("type", timeout=2000) or "").lower()
        except Exception:
            kind = ""
        if kind == "number" and re.fullmatch(r"-?\d+,\d+", text.strip()):
            # Campo numérico (el precio de Wallapop): el navegador NO admite la
            # coma («11,44» acababa como «1144»). Se escribe con punto.
            text = text.strip().replace(",", ".")
        try:
            locator.fill(text, timeout=10000)
        except Exception:
            # Editores que no admiten fill: foco, seleccionar todo, borrar y escribir.
            locator.focus(timeout=5000)
            self._page.keyboard.press("Control+A")
            self._page.keyboard.press("Delete")
            self._page.keyboard.insert_text(text)

    def press(self, key: str) -> None:
        self._page.keyboard.press(key)

    def set_checked(self, target: str, value: bool) -> None:
        locator = self._page.locator(target).first
        try:
            if locator.is_visible():
                locator.set_checked(value, timeout=5000)
                return
        except Exception:
            pass
        # Interruptor dibujado encima de una casilla OCULTA: se pulsa lo que se
        # ve (su etiqueta o el elemento que la contiene), como una persona.
        if self.is_checked(target) == value:
            return
        for visible in (
            locator.locator("xpath=ancestor::label[1]"),
            locator.locator("xpath=following-sibling::*[1]"),
            locator.locator("xpath=.."),
        ):
            try:
                if visible.count() and visible.first.is_visible():
                    visible.first.click(timeout=5000)
                    if self.is_checked(target) == value:
                        return
            except Exception:
                continue
        locator.click(timeout=5000)

    def type_text(self, target: str, text: str) -> None:
        locator = self._page.locator(target).first
        locator.scroll_into_view_if_needed(timeout=5000)
        locator.focus(timeout=5000)
        locator.fill("", timeout=5000)
        locator.press_sequentially(text, delay=60)

    def click(self, target: str) -> None:
        self._page.locator(target).first.click()

    def click_option(
        self, text: str, timeout_ms: int, opener: str | None = None, opener_box: dict | None = None
    ) -> bool:
        """Pulsa la opción visible cuyo texto es EXACTAMENTE `text`.

        `opener_box`: posición del desplegable ANTES de abrirlo (si la lista
        está dentro del componente, medirlo abierto taparía las opciones). Los
        textos marcados como previos (ya estaban antes de abrir, p. ej.
        «Sugerencias inteligentes») nunca se pulsan.

        Vale para listas de cualquier tipo (role=option, <li>, <div>…), también
        cuando cada opción tiene una segunda línea («Estructura de camas» +
        «Camas y accesorios > …») o cuando la lista está DENTRO del propio
        componente del desplegable (como en Wallapop). Solo se descarta el
        botón `opener` que abre la lista (que puede mostrar ya ese valor).
        """
        exact = tolerant_pattern(text)
        texts = self._page.get_by_text(exact)
        if opener and opener_box is None:
            try:
                opener_box = self._page.locator(opener).first.bounding_box()
            except Exception:
                opener_box = None
        deadline = time.monotonic() + max(timeout_ms, 0) / 1000
        while True:
            try:
                count = min(texts.count(), 15)
            except Exception:
                count = 0
            usable = []
            for index in range(count):
                item = texts.nth(index)
                try:
                    if not item.is_visible():
                        continue
                    if item.evaluate("e => !!e.closest('[data-lotbot-previo]')"):
                        continue  # ya estaba en la página antes de abrir la lista
                    box = item.bounding_box()
                    if opener_box and box and _inside(box, opener_box):
                        continue  # es el propio desplegable, no una opción
                    in_list = item.evaluate(
                        "e => !!e.closest('[role=option],[role=listbox],[role=menuitem],"
                        "[role=menu],[role=radio],li')"
                    )
                    usable.append((0 if in_list else 1, index, item))
                except Exception:
                    continue
            # Primero lo que está DENTRO de una lista (la opción de verdad).
            for _, _, item in sorted(usable, key=lambda u: (u[0], u[1])):
                try:
                    item.scroll_into_view_if_needed(timeout=2000)
                    item.click(timeout=5000, position=self._text_point(item))
                    return True
                except Exception:
                    continue
            if time.monotonic() >= deadline:
                return False
            self._page.wait_for_timeout(150)

    @staticmethod
    def _text_point(item) -> dict | None:
        """Clic en el PROPIO texto de la opción (un poco dentro de su borde
        izquierdo), no en el centro de un contenedor grande."""
        try:
            box = item.bounding_box()
        except Exception:
            box = None
        if not box:
            return None
        return {"x": min(12, box["width"] / 2), "y": box["height"] / 2}

    def set_files(self, target: str, paths: list[str]) -> None:
        # Funciona aunque el campo esté oculto (no hace falta que se vea).
        self._page.locator(target).first.set_input_files(paths, timeout=10000)

    def is_alive(self) -> bool:
        try:
            return not self._page.is_closed() and bool(self._page.context.pages)
        except Exception:
            return False

    def _text_locator(self, text: str, within: str | None):
        exact = tolerant_pattern(text)
        root = self._page.locator(within).first if within else self._page
        return root.get_by_text(exact)

    def bbox(self, target: str) -> dict | None:
        try:
            return self._page.locator(target).first.bounding_box()
        except Exception:
            return None

    def text_candidates(
        self, text: str, within: str | None = None, field: str | None = None
    ) -> list[dict]:
        found: list[dict] = []
        locator = self._text_locator(text, within)
        field_handle = None
        if field:
            try:
                field_handle = self._page.locator(field).first.element_handle(timeout=1000)
            except Exception:
                field_handle = None
        try:
            count = min(locator.count(), 20)
        except Exception:
            return found
        for index in range(count):
            item = locator.nth(index)
            try:
                visible = item.is_visible()
            except Exception:
                visible = False
            try:
                enabled = item.is_enabled()
            except Exception:
                enabled = True
            box = None
            if visible:
                try:
                    box = item.bounding_box()
                except Exception:
                    box = None
            try:
                pre = bool(item.evaluate("e => !!e.closest('[data-lotbot-previo]')"))
            except Exception:
                pre = False
            in_field = False
            if field_handle is not None:
                try:
                    in_field = bool(
                        item.evaluate("(e, f) => f === e || f.contains(e)", field_handle)
                    )
                except Exception:
                    in_field = False
            found.append(
                {"index": index, "visible": visible, "enabled": enabled, "box": box,
                 "previo": pre, "en_campo": in_field}
            )
        return found

    def click_suggestion(self, text: str, timeout_ms: int) -> bool:
        """Pulsa la primera sugerencia visible que contiene `text`: en listas
        (role=option, li) o en <div> que empiecen por la ciudad (nunca el
        propio campo donde se ha escrito). Se buscan las dos a la vez."""
        contains = re.compile(re.escape(text), re.IGNORECASE)
        starts = re.compile(rf"^\s*{re.escape(text)}\b", re.IGNORECASE)
        options = (
            self._page.locator("[role=option], [role=menuitem], li")
            .filter(has_text=contains)
            .filter(visible=True)
        )
        texts = self._page.get_by_text(starts)
        deadline = time.monotonic() + max(timeout_ms, 0) / 1000
        while True:
            try:
                if options.count():
                    options.first.click(timeout=5000)
                    return True
                for index in range(min(texts.count(), 10)):
                    item = texts.nth(index)
                    tag = (item.evaluate("e => e.tagName") or "").lower()
                    if tag in ("input", "textarea") or not item.is_visible():
                        continue
                    item.click(timeout=5000)
                    return True
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return False
            self._page.wait_for_timeout(150)

    def mark_existing(self, texts: list[str]) -> int:
        marked = 0
        for text in texts:
            locator = self._text_locator(text, None)
            try:
                count = min(locator.count(), 50)
            except Exception:
                continue
            for index in range(count):
                try:
                    item = locator.nth(index)
                    # Solo lo que SE VE antes de abrir (enlaces, «Sugerencias
                    # inteligentes»). Las opciones que la web tiene cargadas pero
                    # ocultas hasta abrir la lista NO se marcan: son las que hay
                    # que pulsar (marcarlas bloqueaba «Estado: Nuevo»).
                    if not item.is_visible():
                        continue
                    item.evaluate("e => e.setAttribute('data-lotbot-previo', '1')")
                    marked += 1
                except Exception:
                    continue
        return marked

    def unmark_existing(self) -> None:
        try:
            self._page.evaluate(
                "() => document.querySelectorAll('[data-lotbot-previo]')"
                ".forEach(e => e.removeAttribute('data-lotbot-previo'))"
            )
        except Exception:
            pass

    #: La «fila» que se pulsa: el antepasado más cercano que es una opción.
    _ROW_XPATH = (
        "xpath=ancestor-or-self::*[@role='option' or @role='menuitem' or @role='treeitem'"
        " or @role='button' or self::button or self::li or self::a or @tabindex][1]"
    )

    def click_text(self, text: str, index: int, within: str | None = None) -> None:
        item = self._text_locator(text, within).nth(index)
        row = item.locator(self._ROW_XPATH)
        target = row.first if row.count() else item
        target.scroll_into_view_if_needed(timeout=3000)
        target.click(timeout=5000)

    def outer_html(self, target: str, limit: int = 20000) -> str:
        try:
            return (self._page.locator(target).first.evaluate("e => e.outerHTML") or "")[:limit]
        except Exception:
            return ""

    def is_checked(self, target: str) -> bool:
        locator = self._page.locator(target).first
        try:
            return locator.is_checked()
        except Exception:
            return (locator.get_attribute("aria-checked") or "").lower() == "true"

    def attached(self, target: str) -> int:
        try:
            return self._page.locator(target).count()
        except Exception:
            return 0

    def upload_with_chooser(self, button: str, paths: list[str], timeout_ms: int) -> None:
        with self._page.expect_file_chooser(timeout=timeout_ms) as chooser:
            self._page.locator(button).first.click()
        chooser.value.set_files(paths)

    def value_of(self, target: str) -> str:
        locator = self._page.locator(target).first
        # Tiempo corto: si el elemento ya no está, no quedarse 30 s esperando.
        tag = (locator.evaluate("e => e.tagName", timeout=3000) or "").lower()
        if tag in ("input", "textarea", "select"):
            return locator.input_value(timeout=3000) or ""
        return (locator.inner_text(timeout=3000) or "").strip()

    def count(self, target: str) -> int:
        try:
            return self._page.locator(target).count()
        except Exception:
            return 0

    def text_of(self, target: str) -> str:
        return (self._page.locator(target).first.inner_text(timeout=3000) or "").strip()

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
