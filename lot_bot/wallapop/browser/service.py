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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lot_bot.wallapop.browser.config import ATTRIBUTE_KEYS, BrowserSiteConfig, load_site_config
from lot_bot.wallapop.browser.driver import (
    BrowserLauncher,
    BrowserPage,
    BrowserUnavailable,
    PlaywrightLauncher,
)
from lot_bot.wallapop.browser.form import ListingData, ListingForm, PublishReport, UserGate
from lot_bot.wallapop.browser.pool import BrowserSessionPool
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
    ConfigurationError,
    NotAvailableWithCurrentAPIError,
    ProfileInUseError,
    VerificationRequiredError,
)
from lot_bot.wallapop.service import WallapopService

logger = logging.getLogger(__name__)

#: Wallapop pide volver a entrar. La cuenta sigue conectada en LOT Bot.
RELOGIN_MESSAGE = (
    "Wallapop pide volver a iniciar sesión en esta cuenta. Inicia sesión en la ventana "
    "del navegador que está abierta y pulsa «Continuar»: la publicación sigue sola. "
    "(La cuenta no se desconecta: solo se elimina si tú la eliminas.)"
)


@dataclass(slots=True)
class SessionCheck:
    """Resultado de comprobar de verdad si hay sesión iniciada."""

    ok: bool
    state: str
    message: str
    login: str = ""


def parse_count(pattern: str, text: str) -> int | None:
    """Número que acompaña a un texto («1.234 visualizaciones»). None si no está."""
    if not pattern or not text:
        return None
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1).replace(".", "").replace(",", ""))
    except (ValueError, IndexError):
        return None


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
        pool: BrowserSessionPool | None = None,
        normal_launcher=None,
    ) -> None:
        self.profiles = profiles
        self.launcher = launcher or PlaywrightLauncher()
        self.site = site or load_site_config()
        self._shots = screenshots_dir
        #: Callable(ref) -> bool: la cuenta está conectada por navegador.
        self._is_connected = is_account_connected or (lambda ref: profiles.exists(ref))
        #: Navegadores abiertos por cuenta, reutilizados entre publicaciones.
        self.pool = pool or BrowserSessionPool(self.launcher, self.site.keep_open_seconds)
        #: Chrome/Edge normal (sin automatización) para que el usuario inicie
        #: sesión a mano. None = se usa el navegador integrado.
        self.normal_launcher = normal_launcher
        #: gate(cuenta, mensaje) -> bool: espera a que el usuario pulse
        #: «Continuar» (verificaciones, ventana abierta). La pone la cola.
        self.user_gate: UserGate | None = None

    # ------------------------------------------------------------------
    def capabilities(self) -> set[Capability]:
        return {Capability.ACCOUNT_PROFILE, Capability.CREATE_ITEM, Capability.ITEM_STATS}

    def _unavailable(self, capability: Capability):
        raise NotAvailableWithCurrentAPIError(
            capability.value,
            "Con la integración por navegador solo se publica; esta operación no se hace.",
        )

    # ------------------------------------------------------------------
    # Sesión
    # ------------------------------------------------------------------
    def _browser_options(self) -> dict[str, Any]:
        return {
            "visible": self.site.visible,
            "channels": self.site.channels,
            "locale": self.site.locale,
        }

    def _in_browser(
        self, account_ref: str, fn, *, require_connected: bool = True, timeout: float | None = None
    ):
        """Ejecuta `fn(page)` en el navegador persistente de la cuenta."""
        if require_connected and not self._is_connected(account_ref):
            raise AuthenticationError(
                f"La cuenta {account_ref} no tiene sesión de navegador.",
                user_message="Esta cuenta no está conectada. Conéctala en Cuentas → "
                "«Añadir cuenta Wallapop».",
            )
        return self.pool.run(
            account_ref,
            self.profiles.profile_dir(account_ref),
            fn,
            timeout=timeout,
            **self._browser_options(),
        )

    def release(self, account_ref: str) -> None:
        """Cierra el navegador abierto de una cuenta (p. ej. antes de iniciar sesión)."""
        self.pool.close(account_ref)

    def shutdown(self) -> None:
        self.pool.close_all()

    def session_state(self, page: BrowserPage, timeout_ms: int = 8000) -> str:
        """Pista rápida: «verificacion», «iniciada», «sin_sesion» o «desconocido».

        NO basta para dar una cuenta por conectada: para eso está
        `verify_session`.
        """
        found = page.first_visible(
            self.site.verification + self.site.logged_out + self.site.logged_in, timeout_ms
        )
        if found is None:
            return "desconocido"
        if found in self.site.verification:
            return "verificacion"
        if found in self.site.logged_out:
            return "sin_sesion"
        return "iniciada"

    def verify_session(self, page: BrowserPage, *, navigate: bool = True) -> SessionCheck:
        """Comprobación REAL de que hay una sesión iniciada.

        Abre una página privada y exige, a la vez: que Wallapop no redirija
        fuera de ella, que no haya botón de acceso ni verificación y que se vea
        contenido privado. Si algo falla o no se puede confirmar, NO hay sesión.
        """
        site = self.site
        if site.verification and page.first_visible(site.verification, 0):
            return SessionCheck(False, "verificacion", "Wallapop pide una verificación.")
        if navigate:
            try:
                page.goto(site.url(site.check_url))
            except Exception as exc:
                return SessionCheck(
                    False, "error", f"No se ha podido abrir Wallapop ({type(exc).__name__})."
                )
            page.wait(site.check_wait_ms)
        if site.verification and page.first_visible(site.verification, 0):
            logger.info("Verificación de Wallapop. Diagnóstico: %s", page.diagnostics())
            return SessionCheck(False, "verificacion", "Wallapop pide una verificación.")
        current = page.current_url()
        if site.check_url_contains and site.check_url_contains not in current:
            logger.info("Sin sesión (redirección). Diagnóstico: %s", page.diagnostics())
            return SessionCheck(
                False, "sin_sesion", "Wallapop ha redirigido fuera de la zona privada: no hay sesión."
            )
        if site.logged_out and page.first_visible(site.logged_out, 0):
            return SessionCheck(False, "sin_sesion", "Wallapop muestra el botón de iniciar sesión.")
        proof = page.first_visible(site.check_private + site.logged_in, 2000)
        if proof is None:
            logger.info("Sesión no confirmada. Diagnóstico: %s", page.diagnostics())
            return SessionCheck(
                False,
                "desconocido",
                "No se ha podido confirmar la sesión (no se ve ninguna página privada).",
            )
        login = ""
        if site.user_name:
            found = page.first_visible(site.user_name, 0)
            if found:
                try:
                    login = page.text_of(found)[:120]
                except Exception:
                    login = ""
        return SessionCheck(True, "iniciada", "Sesión comprobada.", login=login)

    def check_session(self, account_ref: str) -> SessionCheck:
        """Comprueba la sesión guardada de una cuenta en su propio navegador."""
        if not self.profiles.exists(account_ref):
            return SessionCheck(False, "sin_sesion", "No hay sesión guardada para esta cuenta.")
        try:
            return self._in_browser(account_ref, self.verify_session, require_connected=False)
        except BrowserUnavailable as exc:
            return SessionCheck(False, "error", str(exc))

    def check_connection(self, account_ref: str) -> bool:
        return self.check_session(account_ref).ok

    def get_account_profile(self, account_ref: str) -> AccountProfile:
        return AccountProfile(user_id=account_ref, display_name=account_ref)

    # ------------------------------------------------------------------
    # Estadísticas (solo lo que se ve de verdad en la página del anuncio)
    # ------------------------------------------------------------------
    def get_item_stats(self, account_ref: str, item_url: str) -> dict[str, Any]:
        """Lee visualizaciones y favoritos de la página del anuncio.

        Devuelve `None` en cada dato que no aparezca: nunca se estima.
        """
        patterns = self.site.stats_patterns

        def read(page: BrowserPage) -> dict[str, Any]:
            page.goto(item_url)
            page.wait(1500)
            if self.site.verification and page.first_visible(self.site.verification, 0):
                raise VerificationRequiredError("Verificación al leer estadísticas.")
            text = page.body_text()
            return {key: parse_count(pattern, text) for key, pattern in patterns.items()}

        values = self._in_browser(account_ref, read)
        return {
            "views": values.get("visualizaciones"),
            "favorites": values.get("favoritos"),
            "source": "navegador",
        }

    # ------------------------------------------------------------------
    # Publicar
    # ------------------------------------------------------------------
    #: Código del resultado cuando se pulsó «Publicar» pero Wallapop no lo confirmó.
    UNCONFIRMED_CODE = "RESULTADO_NO_CONFIRMADO"
    #: Tiempo máximo de una publicación, contando la espera a que el usuario
    #: complete una verificación.
    PUBLISH_TIMEOUT_S = 3600.0

    def listing_data(self, draft: ItemDraft) -> ListingData:
        """Datos EXACTOS de la plantilla: no se inventa ni se cambia nada."""
        attributes = {
            key: str(value)
            for key, value in (draft.attributes or {}).items()
            if key in ATTRIBUTE_KEYS and value
        }
        if draft.condition and "estado" not in attributes:
            attributes["estado"] = draft.condition
        return ListingData(
            title=draft.title,
            description=draft.description,
            price=float(draft.price),
            price_text=format_price(float(draft.price), self.site.price_format),
            category=draft.category or "",
            subcategory=str((draft.attributes or {}).get("subcategoria") or ""),
            attributes=attributes,
            images=[str(Path(p)) for p in draft.image_paths if Path(p).is_file()],
        )

    def _screenshot(self, page: BrowserPage, account_ref: str, step: str) -> str | None:
        if self._shots is None:
            return None
        slug = re.sub(r"\W+", "_", step)
        path = self._shots / f"{datetime.now():%Y%m%d-%H%M%S}-{account_ref}-{slug}.png"
        try:
            page.screenshot(path)
            return str(path)
        except Exception:
            return None

    def create_item(self, account_ref: str, draft: ItemDraft) -> OperationResult:
        """Publica un anuncio COMPLETO en el navegador de la cuenta.

        Abre (o reutiliza) el perfil persistente de ESA cuenta, comprueba la
        sesión y rellena el formulario entero con `ListingForm`. Solo devuelve
        éxito si Wallapop confirma la publicación.
        """
        if not self.site.form.defined:
            raise ConfigurationError("wallapop_browser.yaml no define el formulario de publicación.")
        data = self.listing_data(draft)
        profile_dir = self.profiles.profile_dir(account_ref)

        def publish(page: BrowserPage) -> PublishReport:
            form = ListingForm(
                page,
                self.site,
                data,
                account_ref=account_ref,
                profile_dir=profile_dir,
                shots_dir=self._shots,
                gate=self.user_gate,
            )
            form.guard("Comprobar sesión")
            check = self.verify_session(page)
            if check.state == "verificacion":
                # El usuario completa la verificación; se vuelve a comprobar
                # en la MISMA página, sin recargarla.
                form.guard("Comprobar sesión")
                check = self.verify_session(page, navigate=False)
            if not check.ok and check.state in ("desconocido", "error"):
                # Carga lenta o pestaña cerrada: no es una sesión caducada.
                page.wait(1500)
                check = self.verify_session(page)
            while not check.ok and self.user_gate is not None:
                # La cuenta NO se da por caducada: se deja la MISMA ventana en
                # la portada para que el usuario vuelva a entrar y se sigue.
                form.save_error_context("sesion", check.message)
                try:
                    page.goto(self.site.url("inicio"))
                except Exception:
                    pass
                if not self.user_gate(account_ref, RELOGIN_MESSAGE):
                    break
                check = self.verify_session(page)
            if not check.ok:
                form.save_error_context("sesion", check.message)
                raise AuthenticationError(
                    f"Sesión de navegador no confirmada: {check.message}",
                    user_message=RELOGIN_MESSAGE,
                )
            form.steps.append("Comprobar sesión")
            return form.run()

        while True:
            try:
                report = self._in_browser(account_ref, publish, timeout=self.PUBLISH_TIMEOUT_S)
                break
            except ProfileInUseError:
                # La ventana normal de la cuenta sigue abierta: hay que cerrarla.
                if self.user_gate is None or not self.user_gate(
                    account_ref, ProfileInUseError.user_message
                ):
                    raise

        detail = {
            "url": report.url,
            "id_confirmado": bool(report.item_id),
            "confirmado": report.confirmed,
            "pasos": report.steps,
            "omitidos": report.skipped,
        }
        if not report.confirmed:
            return OperationResult(
                success=False,
                message="Resultado no confirmado: se pulsó «Publicar» pero Wallapop no ha "
                "confirmado la publicación. Revisa la cuenta en Wallapop antes de reintentar "
                "(podría estar publicado). Captura en logs/navegador.",
                item_id=None,
                data={**detail, "codigo": self.UNCONFIRMED_CODE},
            )
        return OperationResult(
            success=True,
            message="Publicado en Wallapop y confirmado."
            + ("" if report.url else " Wallapop no ha mostrado la dirección del anuncio."),
            item_id=report.item_id or f"navegador-{int(time.time())}",
            data=detail,
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
