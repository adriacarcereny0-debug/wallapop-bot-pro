"""Construccion del servicio de Wallapop adecuado segun la configuracion.

Es el unico punto del programa que decide entre DEMO y produccion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lot_bot.config.settings import Settings
from lot_bot.wallapop.account_manager import AccountManager
from lot_bot.wallapop.capabilities import Capability
from lot_bot.wallapop.connect_service import ConnectWallapopService
from lot_bot.wallapop.endpoint_map import EndpointMap, empty_map
from lot_bot.wallapop.errors import ConfigurationError
from lot_bot.wallapop.mock_service import MockWallapopService
from lot_bot.wallapop.oauth import OAuthClient
from lot_bot.wallapop.service import WallapopService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WallapopBackend:
    """Servicio activo mas el contexto que explica por que se ha elegido."""

    service: WallapopService
    endpoint_map: EndpointMap
    oauth_client: OAuthClient | None
    demo: bool
    reason: str

    @property
    def label(self) -> str:
        return "MODO DEMO" if self.demo else "Wallapop Connect"


def build_backend(
    settings: Settings, account_manager: AccountManager | None = None
) -> WallapopBackend:
    """Devuelve el backend de Wallapop que corresponde a la configuracion actual.

    Reglas:
      * DEMO explicito                       -> MockWallapopService
      * Faltan credenciales                  -> MockWallapopService (avisando)
      * Falta el mapa de endpoints oficial   -> MockWallapopService (avisando)
      * Todo configurado                     -> ConnectWallapopService
    """
    if settings.demo_mode:
        return WallapopBackend(
            service=MockWallapopService(),
            endpoint_map=empty_map(),
            oauth_client=None,
            demo=True,
            reason="Modo DEMO activado en la configuración.",
        )

    if not settings.has_wallapop_credentials:
        logger.warning("Sin credenciales de Wallapop: se mantiene el modo DEMO.")
        return WallapopBackend(
            service=MockWallapopService(),
            endpoint_map=empty_map(),
            oauth_client=None,
            demo=True,
            reason=(
                "Faltan WALLAPOP_CLIENT_ID, WALLAPOP_CLIENT_SECRET o WALLAPOP_REDIRECT_URI. "
                "La aplicación sigue en modo DEMO para no simular una conexión real."
            ),
        )

    map_path = settings.endpoint_map_path
    if map_path is None or not map_path.is_file():
        logger.warning("Sin mapa de endpoints oficial: se mantiene el modo DEMO.")
        return WallapopBackend(
            service=MockWallapopService(),
            endpoint_map=empty_map(),
            oauth_client=None,
            demo=True,
            reason=(
                "No se ha encontrado el fichero de endpoints oficiales "
                "(WALLAPOP_ENDPOINT_MAP). Sin él, LOT Bot no conoce ninguna ruta de "
                "Wallapop y no inventa ninguna: se mantiene el modo DEMO."
            ),
        )

    endpoint_map = EndpointMap.load(map_path)
    oauth_client = OAuthClient(
        config=endpoint_map.oauth,
        client_id=settings.wallapop_client_id,
        client_secret=settings.wallapop_client_secret,
        redirect_uri=settings.wallapop_redirect_uri,
        scopes=settings.scopes or endpoint_map.oauth.scopes,
    )
    if account_manager is not None:
        account_manager.set_oauth_client(oauth_client)

    if not endpoint_map.is_usable:
        raise ConfigurationError(
            f"El mapa '{map_path}' no declara base_url u operaciones.",
            user_message=(
                "El fichero de endpoints de Wallapop esta vacio o incompleto. "
                "Completa 'api.base_url' y al menos una operacion."
            ),
        )

    if account_manager is None:
        raise ConfigurationError(
            "Se requiere AccountManager para la integracion real (proveedor de tokens)."
        )

    service = ConnectWallapopService(
        endpoint_map=endpoint_map,
        token_provider=account_manager.token_provider(),
    )
    granted = service.capabilities()
    missing = sorted(c.value for c in Capability if c not in granted)
    if missing:
        logger.info(
            "Operaciones NO disponibles con los permisos actuales: %s", ", ".join(missing)
        )
    return WallapopBackend(
        service=service,
        endpoint_map=endpoint_map,
        oauth_client=oauth_client,
        demo=False,
        reason=f"Integración real activa ({len(granted)} operaciones autorizadas).",
    )
