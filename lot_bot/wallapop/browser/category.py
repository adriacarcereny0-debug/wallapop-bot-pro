"""Selector de categoría de Wallapop, paso a paso y con verificación real.

Flujo (como un usuario):

    1. medir el campo «Categoría» ANTES de abrirlo (para no confundirlo luego
       con las opciones: en Wallapop la lista está dentro del mismo componente);
    2. pulsar el campo y ESPERAR a que el panel de categorías sea visible;
    3. buscar la categoría final («Estructura de camas») DENTRO del panel
       (entre las sugeridas); si no está, recorrer la ruta nivel a nivel
       («Muebles y organización» → «Camas y accesorios» → final), esperando a
       que aparezca cada nivel siguiente;
    4. pulsar la FILA de la opción (no solo el texto);
    5. esperar a que el panel se cierre y el campo muestre la categoría;
    6. VERIFICAR: panel cerrado + el campo (sin el panel) contiene la
       categoría final. Si no, error descriptivo con captura y HTML del panel.

Nunca se da por buena una categoría solo porque el clic se ejecutó.
Los selectores están en wallapop_browser.yaml (publicar.formulario.categoria).
Diagnóstico detallado: LOT_BOT_BROWSER_DEBUG=1 (si no, solo al fallar).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from lot_bot.wallapop.browser.driver import BrowserPage

logger = logging.getLogger(__name__)


def debug_enabled() -> bool:
    return os.environ.get("LOT_BOT_BROWSER_DEBUG", "").strip() in ("1", "true", "si", "sí")


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


class CategorySelectionError(RuntimeError):
    """La categoría no ha quedado seleccionada. `detail` explica por qué."""

    def __init__(self, reason: str, diagnostics: dict[str, Any]) -> None:
        self.reason = reason
        self.diagnostics = diagnostics
        super().__init__(reason)


@dataclass(slots=True)
class CategoryPicker:
    page: BrowserPage
    opener_targets: list[str]
    panel_targets: list[str]
    selected_targets: list[str] = field(default_factory=list)
    timeout_ms: int = 20000
    #: Registro de lo que se ha hecho (va al .json de diagnóstico).
    trace: list[dict[str, Any]] = field(default_factory=list)
    _opener_box: dict | None = None
    _path: list[str] = field(default_factory=list)
    _panel_seen: bool = False
    _open_reason: dict | None = None
    _opener: str | None = None

    # ------------------------------------------------------------------
    def _log(self, event: str, **data: Any) -> None:
        entry = {"t": round(time.monotonic(), 3), "evento": event, **data}
        self.trace.append(entry)
        if debug_enabled():
            logger.info("Categoría: %s", json.dumps(entry, ensure_ascii=False, default=str))

    def _wait(self, condition, timeout_ms: int) -> bool:
        """Espera a un ESTADO de la interfaz (sondeo corto, no un sleep fijo)."""
        deadline = time.monotonic() + max(timeout_ms, 0) / 1000
        while True:
            if condition():
                return True
            if time.monotonic() >= deadline:
                return False
            self.page.wait(100)

    def _panel(self) -> str | None:
        found = self.page.first_visible(self.panel_targets, 0) if self.panel_targets else None
        if found:
            self._panel_seen = True
        return found

    def _field_box(self) -> dict | None:
        """Zona del campo AHORA. Si el componente ha crecido (porque la lista
        está dentro de él), se usa la medida de antes de abrirlo."""
        before = self._opener_box
        now = self.page.bbox(self._opener) if self._opener else None
        if now and before and now["height"] <= before["height"] * 2 + 10:
            return now
        return before or now

    def _is_field(self, c: dict) -> bool:
        """¿Este texto es el propio campo (no una opción de la lista)?"""
        box = c.get("box")
        area = self._field_box()
        if c.get("en_campo"):
            return bool(box and area and _inside(box, area))
        return bool(box and self._opener_box and _inside(box, self._opener_box))

    def _near_field(self, box: dict | None) -> bool:
        area = self._opener_box
        if not area or not box:
            return False
        near = {"x": area["x"] - 50, "y": area["y"] - 150,
                "width": area["width"] + 100, "height": area["height"] + 300}
        return _inside(box, near)

    def _panel_open(self) -> bool:
        """¿Sigue abierta la lista? Por su selector o, si Wallapop cambia su
        forma, porque se ven opciones de la ruta fuera del campo."""
        if self._panel() is not None:
            return True
        if self._panel_seen:
            return False  # el selector del panel funciona: y ya no se ve
        for text in self._path:
            for c in self.page.text_candidates(text, field=self._opener):
                if c.get("previo") or self._is_field(c):
                    continue  # un enlace que ya estaba, o el propio campo
                if c.get("visible") and c.get("box") and not _inside(c["box"], self._opener_box or {}):
                    if not self._near_field(c["box"]) or text != self._path[-1]:
                        self._open_reason = {"texto": text, **c}
                        return True
        return False

    def _field_text(self, opener: str) -> str:
        """Texto del campo Categoría. Solo se lee con el panel CERRADO (con el
        panel abierto el componente contiene también las opciones)."""
        for target in [*self.selected_targets, opener]:
            try:
                if self.page.first_visible([target], 0):
                    return self.page.value_of(target)
            except Exception:
                continue
        return ""

    def _is_selected(self, opener: str, leaf: str) -> bool:
        """Panel CERRADO y la categoría final visible en el formulario (en el
        campo; o, si el campo cambia de forma al elegir, en la página)."""
        if self._panel() is not None:
            return False
        if _norm(leaf) in _norm(self._field_text(opener)):
            return not self._panel_open()
        # El campo puede cambiar de forma al elegir: se acepta el texto de la
        # categoría SOLO si está donde estaba el campo (no en otra parte).
        return any(
            c.get("visible") and not c.get("previo")
            and (self._is_field(c) or self._near_field(c.get("box")))
            for c in self.page.text_candidates(leaf, field=self._opener)
        ) and not self._panel_open()

    def _candidates(self, text: str, opener_box: dict | None) -> list[dict[str, Any]]:
        panel = self._panel()
        found = self.page.text_candidates(text, within=panel, field=self._opener)
        usable = []
        for c in found:
            c["en_panel"] = bool(panel)
            c["es_el_campo"] = self._is_field(c)
            usable_now = c.get("visible") and c.get("enabled", True)
            if usable_now and not c["es_el_campo"] and not c.get("previo"):
                usable.append(c)
        self._log("buscar", texto=text, panel=panel, encontrados=len(found), usables=len(usable),
                  detalle=[{k: v for k, v in c.items() if k != "box"} for c in found][:10])
        return usable

    def _click(self, text: str, opener_box: dict | None, timeout_ms: int) -> bool:
        """Espera a que la opción aparezca (visible) en el panel y la pulsa."""
        chosen: list[dict[str, Any]] = []

        def appears() -> bool:
            options = self._candidates(text, opener_box)
            if options:
                chosen.append(options[0])  # varias iguales: la primera del panel
                return True
            return False

        if not self._wait(appears, timeout_ms):
            return False
        option = chosen[-1]
        self.page.click_text(text, option["index"], within=self._panel())
        self._log("clic", texto=text, indice=option["index"], ejecutado=True)
        return True

    # ------------------------------------------------------------------
    def select(self, path: list[str]) -> str:
        """Selecciona la ruta y devuelve la categoría final ya VERIFICADA."""
        try:
            return self._select(path)
        finally:
            self.page.unmark_existing()

    def _select(self, path: list[str]) -> str:
        leaf = path[-1]
        self._path = list(path)
        self._opener = None
        opener = self.page.first_visible(self.opener_targets, self.timeout_ms)
        if opener is None:
            raise CategorySelectionError("No aparece el campo «Categoría».", self._diag(path))
        self._opener = opener
        opener_box = self.page.bbox(opener)  # ANTES de abrir la lista
        self._opener_box = opener_box
        self._log("campo", selector=opener, caja=opener_box)
        if _norm(leaf) in _norm(self._field_text(opener)) and self._panel() is None:
            self._log("ya_seleccionada", categoria=leaf)
            return leaf

        # Lo que ya se ve ANTES de abrir (enlaces, textos ocultos…) no es una
        # opción de la lista aunque tenga el mismo nombre.
        self._log("marcados_previos", total=self.page.mark_existing(path))
        self.page.click(opener)
        if not self._wait(self._panel_open, self.timeout_ms):
            raise CategorySelectionError(
                "Se ha pulsado «Categoría» pero no se ha abierto la lista de categorías.",
                self._diag(path),
            )
        self._log("panel_abierto", panel=self._panel())

        # 1. La final entre las sugeridas.
        if self._click(leaf, opener_box, min(self.timeout_ms, 4000)) and self._wait(
            lambda: self._is_selected(opener, leaf), min(self.timeout_ms, 5000)
        ):
            self._log("verificada", categoria=leaf, via="sugerida")
            return leaf

        # 2. Recorrer la ruta nivel a nivel.
        if not self._panel_open():
            self.page.click(opener)
            self._wait(self._panel_open, self.timeout_ms)
        for index, part in enumerate(path):
            if not self._click(part, opener_box, self.timeout_ms):
                raise CategorySelectionError(
                    f"No aparece «{part}» en la lista de categorías "
                    f"(nivel {index + 1} de {len(path)}).",
                    self._diag(path),
                )
            if index < len(path) - 1:
                following = path[index + 1]
                if not self._wait(
                    lambda f=following: bool(self._candidates(f, opener_box)), self.timeout_ms
                ):
                    raise CategorySelectionError(
                        f"Tras pulsar «{part}» no aparece el siguiente nivel «{following}».",
                        self._diag(path),
                    )

        if not self._wait(lambda: self._is_selected(opener, leaf), self.timeout_ms):
            if self._panel_open():
                reason = (
                    f"Se ha pulsado «{leaf}» pero la lista de categorías sigue abierta: "
                    "Wallapop no ha aceptado la selección."
                )
            else:
                reason = (
                    f"La lista se ha cerrado pero el campo muestra «{self._field_text(opener)}» "
                    f"en vez de «{leaf}»."
                )
            raise CategorySelectionError(reason, self._diag(path))
        self._log("verificada", categoria=leaf, via="ruta")
        return leaf

    def _diag(self, path: list[str]) -> dict[str, Any]:
        panel = self._panel()
        html = self.page.outer_html(panel, 20000) if panel else ""
        return {
            "ruta": path,
            "panel_visible": panel,
            "html_panel": html,
            "pasos": list(self.trace)[-40:],
            "lista_abierta_por": self._open_reason,
        }


def _inside(box: dict, outer: dict) -> bool:
    if not outer:
        return False
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    return (
        outer["x"] <= cx <= outer["x"] + outer["width"]
        and outer["y"] <= cy <= outer["y"] + outer["height"]
    )
