"""Formulario de «Subir producto» de Wallapop, rellenado por LOT Bot.

Aquí está el flujo COMPLETO de publicación. Cada paso es un método con
nombre propio y todos los selectores vienen de `wallapop_browser.yaml`
(sección `publicar.formulario`): este fichero no contiene ninguno.

    open_create_listing → choose_listing_type → fill_title → select_category →
    fill_attributes → fill_description → fill_price → upload_photos →
    verify_form → submit_listing → wait_for_publish_confirmation →
    get_published_listing_url

Reglas:
  * Nunca se resuelve ni se salta un CAPTCHA o verificación. Si aparece, se
    guarda captura, se avisa al usuario y se ESPERA a que la complete en la
    ventana y pulse «Continuar»; entonces se sigue desde el mismo paso.
  * Antes de pulsar «Publicar» se relee el formulario. Si algo no coincide
    (título, precio, descripción, características, fotos o cuenta), NO se
    publica y se dice qué campo falla.
  * Solo se da por publicado si Wallapop lo confirma (URL del anuncio o
    mensaje de éxito). Si no, el resultado es «no confirmado».
  * Cada error guarda captura y contexto en logs/navegador (sin cookies,
    tokens ni contraseñas) para poder corregir los selectores.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from lot_bot.wallapop.browser.config import ATTRIBUTE_KEYS, BrowserSiteConfig, FormField
from lot_bot.wallapop.browser.driver import BrowserPage, safe_url
from lot_bot.wallapop.errors import (
    BrowserStepError,
    FormMismatchError,
    ImageUploadError,
    VerificationRequiredError,
    WallapopError,
)

logger = logging.getLogger(__name__)

#: gate(account_ref, mensaje) -> True si el usuario pulsa «Continuar»,
#: False si cancela o se agota el tiempo.
UserGate = Callable[[str, str], bool]

ATTRIBUTE_LABELS = {"estado": "Estado", "uso": "Uso", "color": "Color", "material": "Material"}


def normalize(text: str) -> str:
    """Para comparar: sin mayúsculas, espacios repetidos ni formas Unicode distintas."""
    text = unicodedata.normalize("NFC", text or "")
    return re.sub(r"\s+", " ", text).strip().casefold()


def parse_price(text: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d{1,2})?", (text or "").replace(" ", " "))
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


@dataclass(slots=True)
class ListingData:
    """Lo que se va a publicar, EXACTAMENTE como está en la plantilla."""

    title: str
    description: str
    price: float
    price_text: str
    category: str = ""
    subcategory: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PublishReport:
    confirmed: bool
    url: str | None
    item_id: str | None
    steps: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    signal: str = ""


class ListingForm:
    def __init__(
        self,
        page: BrowserPage,
        site: BrowserSiteConfig,
        data: ListingData,
        *,
        account_ref: str,
        profile_dir: Path | None = None,
        shots_dir: Path | None = None,
        gate: UserGate | None = None,
        gate_timeout_s: float = 1800.0,
    ) -> None:
        self.page = page
        self.site = site
        self.form = site.form
        self.data = data
        self.account_ref = account_ref
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.shots_dir = shots_dir
        self.gate = gate
        self.gate_timeout_s = gate_timeout_s
        self.steps: list[str] = []
        self.skipped: list[str] = []
        self.attributes_filled: dict[str, str] = {}
        self._photos_before = 0

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    @property
    def timeout(self) -> int:
        return self.site.timeout_ms

    def save_error_context(self, step: str, error: str) -> str | None:
        """Captura + contexto en logs/navegador. Nunca cookies ni tokens."""
        if self.shots_dir is None:
            return None
        slug = re.sub(r"\W+", "_", step).strip("_") or "paso"
        base = self.shots_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{self.account_ref}-{slug}"
        shot: str | None = None
        try:
            self.page.screenshot(base.with_suffix(".png"))
            shot = str(base.with_suffix(".png"))
        except Exception:
            shot = None
        try:
            url = safe_url(self.page.current_url())
        except Exception:
            url = "desconocida"
        try:
            diagnostics = self.page.diagnostics()
        except Exception:
            diagnostics = {}
        context = {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "cuenta": self.account_ref,
            "paso": step,
            "error": error,
            "url": url,
            "pasos_completados": list(self.steps),
            "captura": Path(shot).name if shot else None,
            "configuracion": str(self.site.source) if self.site.source else None,
            "diagnostico": diagnostics,
            "nota": "Pasa esta captura y este fichero a Claude para actualizar los "
            "selectores de wallapop_browser.yaml.",
        }
        try:
            base.parent.mkdir(parents=True, exist_ok=True)
            base.with_suffix(".json").write_text(
                json.dumps(context, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        except OSError:
            pass
        logger.error("Publicación: fallo en «%s» (%s). Contexto: %s", step, error, base.with_suffix(".json"))
        return shot

    def _fail(self, step: str, detail: str) -> BrowserStepError:
        shot = self.save_error_context(step, detail)
        return BrowserStepError(step, detail, shot)

    def _verification_visible(self) -> bool:
        return bool(self.site.verification and self.page.first_visible(self.site.verification, 0))

    def guard(self, step: str) -> None:
        """Si Wallapop pide una verificación: esperar al usuario, NUNCA resolverla."""
        if not self._verification_visible():
            return
        self.save_error_context(f"verificacion-{step}", "Wallapop pide una verificación")
        deadline = time.monotonic() + self.gate_timeout_s
        while self._verification_visible():
            if self.gate is None or time.monotonic() > deadline:
                raise VerificationRequiredError(f"Verificación en el paso «{step}».")
            if not self.gate(self.account_ref, VerificationRequiredError.user_message):
                raise VerificationRequiredError(f"Verificación en el paso «{step}» (no completada).")
        logger.info("Verificación completada por el usuario; se sigue en «%s».", step)

    def _check_wallapop_error(self, step: str) -> None:
        if self.form.errors:
            found = self.page.first_visible(self.form.errors, 0)
            if found:
                try:
                    text = self.page.text_of(found)[:200]
                except Exception:
                    text = found
                raise self._fail(step, f"Wallapop muestra un error: {text}")

    def _find(self, step: str, spec: FormField, *, wait: bool = True) -> str | None:
        target = self.page.first_visible(spec.targets, self.timeout if wait else 0)
        if target is None:
            self.guard(step)  # ¿apareció una verificación mientras esperábamos?
            target = self.page.first_visible(spec.targets, 0)
        return target

    def _require(self, step: str, spec: FormField) -> str:
        target = self._find(step, spec)
        if target is None:
            raise self._fail(step, f"No aparece ningún elemento de: {spec.targets}")
        return target

    def _do(self, step: str, action: Callable[[], Any]) -> None:
        """Ejecuta un paso con control de verificación y errores."""
        self.guard(step)
        try:
            action()
        except WallapopError:
            raise
        except Exception as exc:
            raise self._fail(step, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}") from exc
        self._check_wallapop_error(step)
        self.steps.append(step)
        logger.info("Publicación [%s]: paso «%s» hecho.", self.account_ref, step)

    def _type(self, step: str, spec: FormField, text: str) -> None:
        def action() -> None:
            target = self._require(step, spec)
            self.page.fill(target, text)

        self._do(step, action)

    def _choose(self, step: str, spec: FormField, option: str) -> bool:
        """Abre un desplegable y elige la opción. False si el campo (opcional) no existe."""
        if not option:
            self.skipped.append(f"{step} (sin valor en la plantilla)")
            return False
        if spec.optional and self._find(step, spec, wait=False) is None:
            # Un campo opcional puede tardar un poco en aparecer tras elegir la categoría.
            if self.page.first_visible(spec.targets, min(self.timeout, 3000)) is None:
                self.skipped.append(f"{step} (el formulario no tiene este campo)")
                return False

        def action() -> None:
            target = self._require(step, spec)
            self.page.click(target)
            if not self.page.click_option(option, self.timeout):
                raise self._fail(step, f"No aparece la opción «{option}».")

        self._do(step, action)
        return True

    # ------------------------------------------------------------------
    # Pasos
    # ------------------------------------------------------------------
    def open_create_listing(self) -> None:
        self._do("Abrir crear anuncio", lambda: self.page.goto(self.site.url(self.form.open_url)))

    def choose_listing_type(self) -> None:
        spec = self.form.listing_type
        if not spec.targets:
            return
        target = self.page.first_visible(spec.targets, min(self.timeout, 5000))
        if target is None:
            if spec.optional:
                self.skipped.append("Tipo de anuncio (no se pregunta)")
                return
            raise self._fail("Tipo de anuncio", f"No aparece: {spec.targets}")
        self._do("Tipo de anuncio", lambda: self.page.click(target))

    def fill_title(self) -> None:
        self._type("Título", self.form.title, self.data.title)

    def select_category(self) -> None:
        if not self.data.category:
            raise self._fail("Categoría", "La plantilla no tiene categoría.")
        self._choose("Categoría", self.form.category, self.data.category)
        if self.data.subcategory:
            self._choose("Subcategoría", self.form.subcategory, self.data.subcategory)

    def fill_attributes(self) -> None:
        for key in ATTRIBUTE_KEYS:
            value = self.data.attributes.get(key, "")
            spec = self.form.attributes.get(key)
            if not value:
                continue
            label = f"Característica {ATTRIBUTE_LABELS.get(key, key)}"
            if spec is None or not spec.targets:
                self.skipped.append(f"{label} (sin selectores en el YAML)")
                continue
            if self._choose(label, spec, value):
                self.attributes_filled[key] = value

    def fill_description(self) -> None:
        self._type("Descripción", self.form.description, self.data.description)

    def fill_price(self) -> None:
        self._type("Precio", self.form.price, self.data.price_text)

    def upload_photos(self) -> None:
        step = "Fotos"
        images = [p for p in self.data.images if Path(p).is_file()]
        if not images:
            raise self._fail(step, "No hay ninguna foto preparada para este anuncio.")
        thumbs = self.form.photo_thumbnails

        def action() -> None:
            self._photos_before = sum(self.page.count(t) for t in thumbs) if thumbs else 0
            target = self.page.first_visible(self.form.photos.targets, 0)
            if target is None and self.form.photos.targets:
                target = self.form.photos.targets[0]  # input de archivos oculto
            if target is None:
                raise self._fail(step, "No hay selector del campo de fotos en el YAML.")
            self.page.set_files(target, images)

        self._do(step, action)
        # Comprobar que Wallapop HA CARGADO las fotos (aparece la miniatura).
        if not thumbs:
            raise self._fail(step, "El YAML no indica cómo reconocer una foto cargada (miniaturas).")
        deadline = time.monotonic() + self.form.photo_wait_ms / 1000
        while True:
            self.guard(step)
            if self.form.photo_rejected and self.page.first_visible(self.form.photo_rejected, 0):
                shot = self.save_error_context(step, "Wallapop ha rechazado la foto")
                raise ImageUploadError("Wallapop ha rechazado la foto.", shot)
            loaded = sum(self.page.count(t) for t in thumbs) - self._photos_before
            if loaded >= len(images):
                return
            if time.monotonic() > deadline:
                shot = self.save_error_context(step, f"Fotos cargadas {loaded} de {len(images)}")
                raise ImageUploadError(f"cargadas {max(loaded, 0)} de {len(images)}", shot)
            self.page.wait(500)

    # ------------------------------------------------------------------
    # Comprobación antes de publicar
    # ------------------------------------------------------------------
    def _read(self, spec: FormField) -> str | None:
        for target in (spec.readback or spec.targets):
            try:
                if self.page.first_visible([target], 0):
                    return self.page.value_of(target)
            except Exception:
                continue
        return None

    def form_problems(self) -> dict[str, str]:
        problems: dict[str, str] = {}
        title = self._read(self.form.title)
        if title is None or normalize(title) != normalize(self.data.title):
            problems["Título"] = f"se esperaba «{self.data.title}», hay «{title}»"
        description = self._read(self.form.description)
        if description is None or normalize(description) != normalize(self.data.description):
            problems["Descripción"] = "el texto del formulario no es el de la plantilla"
        price = self._read(self.form.price)
        value = parse_price(price or "")
        if value is None or abs(value - float(self.data.price)) > 0.001:
            expected = f"{self.data.price:.2f}".replace(".", ",")
            problems["Precio"] = f"se esperaba {expected} €, hay «{price}»"
        category = self._read(self.form.category)
        if category is not None and normalize(self.data.category) not in normalize(category):
            problems["Categoría"] = f"se esperaba «{self.data.category}», hay «{category}»"
        for key, expected in self.attributes_filled.items():
            spec = self.form.attributes[key]
            current = self._read(spec)
            if current is None or normalize(expected) not in normalize(current):
                problems[ATTRIBUTE_LABELS.get(key, key)] = f"se esperaba «{expected}», hay «{current}»"
        thumbs = self.form.photo_thumbnails
        loaded = sum(self.page.count(t) for t in thumbs) - self._photos_before if thumbs else 0
        if loaded < len(self.data.images):
            problems["Fotos"] = f"cargadas {max(loaded, 0)} de {len(self.data.images)}"
        if self.profile_dir is not None and self.profile_dir.name != self.account_ref:
            problems["Cuenta"] = f"el navegador usa el perfil «{self.profile_dir.name}»"
        return problems

    def verify_form(self) -> None:
        self.guard("Comprobar formulario")
        problems = self.form_problems()
        if problems:
            shot = self.save_error_context("comprobar-formulario", json.dumps(problems, ensure_ascii=False))
            raise FormMismatchError(problems, shot)
        self.steps.append("Comprobar formulario")

    # ------------------------------------------------------------------
    # Publicar y confirmar
    # ------------------------------------------------------------------
    def submit_listing(self) -> None:
        self._do("Publicar", lambda: self.page.click(self._require("Publicar", self.form.submit)))

    def wait_for_publish_confirmation(self) -> str:
        """Devuelve la señal de éxito ('url' o 'texto') o '' si no se confirma."""
        deadline = time.monotonic() + self.site.success_timeout_ms / 1000
        url_regex = re.compile(self.site.success_url_regex) if self.site.success_url_regex else None
        while True:
            self.guard("Confirmación")
            self._check_wallapop_error("Confirmación")
            if url_regex and url_regex.search(self.page.current_url()):
                return "url"
            if self.site.success_texts and self.page.first_visible(self.site.success_texts, 0):
                return "texto"
            if time.monotonic() > deadline:
                self.save_error_context("confirmacion", "Wallapop no ha confirmado la publicación")
                return ""
            self.page.wait(500)

    def get_published_listing_url(self) -> str | None:
        pattern = self.site.item_url_regex
        if not pattern:
            return None
        match = re.search(pattern, self.page.current_url())
        if match:
            return match.group(0)
        try:
            links = self.page.links_matching(pattern)
        except Exception:
            links = []
        return links[0] if links else None

    # ------------------------------------------------------------------
    def run(self) -> PublishReport:
        self.open_create_listing()
        self.choose_listing_type()
        self.fill_title()
        self.select_category()
        self.fill_attributes()
        self.fill_description()
        self.fill_price()
        self.upload_photos()
        self.verify_form()
        self.submit_listing()
        signal = self.wait_for_publish_confirmation()
        url = self.get_published_listing_url() if signal else None
        item_id = url.rstrip("/").rsplit("/", 1)[-1] if url else None
        if signal:
            self.steps.append("Confirmación de Wallapop")
        return PublishReport(
            confirmed=bool(signal),
            url=url,
            item_id=item_id,
            steps=list(self.steps),
            skipped=list(self.skipped),
            signal=signal,
        )
