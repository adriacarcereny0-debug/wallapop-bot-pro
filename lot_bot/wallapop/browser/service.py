"""`BrowserWallapopService`: Wallapop a través de un navegador controlado.

El usuario ha iniciado sesión él mismo en el perfil de navegador de cada
cuenta. Este servicio solo repite, en su lugar, los pasos que haría a mano en
la web pública de Wallapop, descritos en `wallapop_browser.yaml`.

Capacidades: solo lo que se hace de verdad en el navegador —comprobar la
sesión y publicar un anuncio (con sus fotos)—. Todo lo demás responde
NOT_AVAILABLE_WITH_CURRENT_WALLAPOP_ACCESS: no se simula nada.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from lot_bot.wallapop.browser.config import BrowserSiteConfig, Step, load_site_config
from lot_bot.wallapop.browser.driver import (
    BrowserLauncher,
    BrowserPage,
    BrowserUnavailable,
    PlaywrightLauncher,
)
from lot_bot.wallapop.browser.profiles import BrowserProfileStore
from lot_bot.wallapop.capabilities import Capability
from lot_bot.wallapop.dto import (
    AccountProfile,
    ChatMessage,
    ConversationSummary,
    Item,
    ItemDraft,
    ItemSearchQuery,
    MarketDataPoint,
    OperationResult,
)
from lot_bot.wallapop.errors import (
    AuthenticationError,
    BrowserStepError,
    ConfigurationError,
    NotAvailableWithCurrentAPIError,
    VerificationRequiredError,
)
from lot_bot.wallapop.service import WallapopService

logger = logging.getLogger(__name__)


def format_price(price: float, style: str) -> str:
    text = f"{price:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    return text.replace(".", ",") if style == "coma" else text


class BrowserWallapopService(WallapopService):
    backend_name = "WALLAPOP (NAVEGADOR)"
    is_mock = False

    def __init__(
        self,
        profiles: BrowserProfileStore,
        *,
        launcher: BrowserLauncher | None = None,
        site: BrowserSiteConfig | None = None,
        screenshots_dir: Path | None = None,
        is_account_connected=None,
    ) -> None:
        self.profiles = profiles
        self.launcher = launcher or PlaywrightLauncher()
        self.site = site or load_site_config()
        self._shots = screenshots_dir
        #: Callable(ref) -> bool: la cuenta está conectada por navegador.
        self._is_connected = is_account_connected or (lambda ref: profiles.exists(ref))

    # ------------------------------------------------------------------
    def capabilities(self) -> set[Capability]:
        return {Capability.ACCOUNT_PROFILE, Capability.CREATE_ITEM}

    def _unavailable(self, capability: Capability):
        raise NotAvailableWithCurrentAPIError(
            capability.value,
            "Con la integración por navegador solo se publica; esta operación no se hace.",
        )

    # ------------------------------------------------------------------
    # Sesión
    # ------------------------------------------------------------------
    def _open(self, account_ref: str):
        if not self._is_connected(account_ref):
            raise AuthenticationError(
                f"La cuenta {account_ref} no tiene sesión de navegador.",
                user_message="Esta cuenta no está conectada. Conéctala en Cuentas → "
                "«Añadir cuenta Wallapop».",
            )
        return self.launcher.open(
            self.profiles.profile_dir(account_ref),
            visible=self.site.visible,
            channels=self.site.channels,
            locale=self.site.locale,
        )

    def session_state(self, page: BrowserPage, timeout_ms: int = 8000) -> str:
        """«verificacion», «iniciada», «sin_sesion» o «desconocido»."""
        found = page.first_visible(
            self.site.verification + self.site.logged_in + self.site.logged_out, timeout_ms
        )
        if found is None:
            return "desconocido"
        if found in self.site.verification:
            return "verificacion"
        if found in self.site.logged_in:
            return "iniciada"
        return "sin_sesion"

    def check_connection(self, account_ref: str) -> bool:
        try:
            with self.profiles.lock(account_ref), self._open(account_ref) as page:
                page.goto(self.site.url("inicio"))
                return self.session_state(page) == "iniciada"
        except (AuthenticationError, BrowserUnavailable):
            return False

    def get_account_profile(self, account_ref: str) -> AccountProfile:
        return AccountProfile(user_id=account_ref, display_name=account_ref)

    # ------------------------------------------------------------------
    # Publicar
    # ------------------------------------------------------------------
    def _values(self, draft: ItemDraft) -> dict[str, str]:
        attributes = draft.attributes or {}
        return {
            "titulo": draft.title,
            "descripcion": draft.description,
            "precio": format_price(float(draft.price), self.site.price_format),
            "categoria": draft.category or "",
            "subcategoria": str(attributes.get("subcategoria") or ""),
            "estado": draft.condition or "",
        }

    @staticmethod
    def _render(template: str, values: dict[str, str]) -> str:
        return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), ""), template)

    def _screenshot(self, page: BrowserPage, account_ref: str, step: str) -> str | None:
        if self._shots is None:
            return None
        slug = re.sub(r"\W+", "_", step)
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{account_ref}-{slug}.png"
        path = self._shots / name
        try:
            page.screenshot(path)
            return str(path)
        except Exception:
            return None

    def _guard_verification(self, page: BrowserPage, account_ref: str, step: str) -> None:
        if self.site.verification and page.first_visible(self.site.verification, 0):
            self._screenshot(page, account_ref, f"verificacion-{step}")
            raise VerificationRequiredError(f"Verificación en el paso «{step}».")

    def _run_step(
        self, page: BrowserPage, step: Step, values: dict[str, str], images: list[str], ref: str
    ) -> None:
        timeout = self.site.timeout_ms
        self._guard_verification(page, ref, step.name)
        if step.action == "ir":
            page.goto(self.site.url(step.url))
            return

        value = self._render(step.value, values)
        option = self._render(step.option, values)
        if step.optional_if_empty and (
            (step.action == "elegir" and not option) or (step.action == "escribir" and not value)
        ):
            return
        if step.action == "subir_archivos" and not images:
            return

        target = page.first_visible(step.targets, 0 if step.optional else timeout)
        if target is None and step.action == "subir_archivos":
            # Los <input type=file> suelen estar ocultos: se usa el primero.
            target = step.targets[0] if step.targets else None
        if target is None:
            if step.optional:
                return
            self._guard_verification(page, ref, step.name)
            shot = self._screenshot(page, ref, step.name)
            raise BrowserStepError(step.name, f"No aparece ningún elemento de: {step.targets}", shot)

        try:
            if step.action == "escribir":
                page.fill(target, value)
            elif step.action == "pulsar":
                page.click(target)
            elif step.action == "subir_archivos":
                page.set_files(target, images)
            elif step.action == "elegir":
                page.click(target)
                if not page.click_option(option, timeout):
                    if step.optional:
                        return
                    raise BrowserStepError(step.name, f"No aparece la opción «{option}».")
            else:
                raise BrowserStepError(step.name, f"Acción desconocida «{step.action}».")
        except (BrowserStepError, VerificationRequiredError):
            raise
        except Exception as exc:
            if step.optional:
                return
            shot = self._screenshot(page, ref, step.name)
            raise BrowserStepError(step.name, type(exc).__name__, shot) from exc

    def _wait_success(self, page: BrowserPage, ref: str) -> str | None:
        """Espera la confirmación de Wallapop; devuelve la URL del anuncio si la hay."""
        deadline = time.monotonic() + self.site.success_timeout_ms / 1000
        url_regex = re.compile(self.site.success_url_regex) if self.site.success_url_regex else None
        while time.monotonic() < deadline:
            self._guard_verification(page, ref, "confirmación")
            current = page.current_url()
            if url_regex and url_regex.search(current):
                break
            if self.site.success_texts and page.first_visible(self.site.success_texts, 0):
                break
            page.wait(500)
        else:
            shot = self._screenshot(page, ref, "confirmacion")
            raise BrowserStepError(
                "Confirmación de publicación",
                "Wallapop no ha mostrado la confirmación a tiempo.",
                shot,
            )
        if self.site.item_url_regex:
            if re.search(self.site.item_url_regex, page.current_url()):
                return re.search(self.site.item_url_regex, page.current_url()).group(0)
            links = page.links_matching(self.site.item_url_regex)
            if links:
                return links[0]
        return None

    def create_item(self, account_ref: str, draft: ItemDraft) -> OperationResult:
        if not self.site.steps:
            raise ConfigurationError("wallapop_browser.yaml no define los pasos de publicación.")
        values = self._values(draft)
        images = [str(Path(p)) for p in draft.image_paths if Path(p).is_file()]
        with self.profiles.lock(account_ref), self._open(account_ref) as page:
            page.goto(self.site.url("inicio"))
            state = self.session_state(page)
            if state == "verificacion":
                raise VerificationRequiredError("Verificación al abrir Wallapop.")
            if state == "sin_sesion":
                raise AuthenticationError(
                    "Sesión de navegador no iniciada.",
                    user_message="La sesión de Wallapop de esta cuenta ha terminado. "
                    "Vuelve a autenticarla en Cuentas.",
                )
            for step in self.site.steps:
                self._run_step(page, step, values, images, account_ref)
            url = self._wait_success(page, account_ref)
        item_id = None
        if url:
            item_id = url.rstrip("/").rsplit("/", 1)[-1]
        return OperationResult(
            success=True,
            message="Publicado en Wallapop desde el navegador."
            + ("" if url else " Wallapop no ha mostrado la dirección del anuncio."),
            item_id=item_id or f"navegador-{int(time.time())}",
            data={"url": url, "id_confirmado": bool(url)},
        )

    # ------------------------------------------------------------------
    # Lo que la integración por navegador no hace
    # ------------------------------------------------------------------
    def list_items(self, account_ref: str, limit: int = 100, offset: int = 0) -> list[Item]:
        self._unavailable(Capability.LIST_ITEMS)

    def get_item(self, account_ref: str, item_id: str) -> Item:
        self._unavailable(Capability.GET_ITEM)

    def search_items(self, account_ref: str, query: ItemSearchQuery) -> list[Item]:
        self._unavailable(Capability.SEARCH_ITEMS)

    def update_item(self, account_ref: str, item_id: str, changes: dict[str, Any]) -> OperationResult:
        self._unavailable(Capability.UPDATE_ITEM)

    def delete_item(self, account_ref: str, item_id: str) -> OperationResult:
        self._unavailable(Capability.DELETE_ITEM)

    def update_item_price(self, account_ref: str, item_id: str, price: float) -> OperationResult:
        self._unavailable(Capability.UPDATE_ITEM_PRICE)

    def update_item_images(
        self, account_ref: str, item_id: str, image_urls: list[str]
    ) -> OperationResult:
        self._unavailable(Capability.UPDATE_ITEM_IMAGES)

    def upload_image(self, account_ref: str, image_path: str) -> str:
        # Las fotos se suben dentro del propio formulario de `create_item`.
        self._unavailable(Capability.UPLOAD_IMAGE)

    def list_categories(self, account_ref: str) -> list[dict[str, Any]]:
        self._unavailable(Capability.LIST_CATEGORIES)

    def list_conversations(self, account_ref: str, limit: int = 50) -> list[ConversationSummary]:
        self._unavailable(Capability.LIST_CONVERSATIONS)

    def get_conversation_messages(self, account_ref: str, conversation_id: str) -> list[ChatMessage]:
        self._unavailable(Capability.GET_CONVERSATION)

    def send_message(self, account_ref: str, conversation_id: str, body: str) -> OperationResult:
        self._unavailable(Capability.SEND_MESSAGE)

    def get_market_data(self, account_ref: str, query: str, limit: int = 50) -> list[MarketDataPoint]:
        self._unavailable(Capability.MARKET_DATA)
