"""Eleccion del backend de Wallapop segun el acceso autorizado disponible.

Es el UNICO punto del programa que decide entre DEMO y acceso real.

REGLA CENTRAL
-------------
LOT Bot pasa a modo real solo cuando estan las DOS piezas:

    1. AUTENTICACION: un mecanismo autorizado, listo para usarse.
    2. TRANSPORTE:    al menos una operacion declarada y una direccion base.

Si falta cualquiera de ellas, se mantiene el modo DEMO y se explica
EXACTAMENTE que falta y quien debe proporcionarlo. Nunca se finge una conexion
real, y nunca se supone un mecanismo o un endpoint que no este declarado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from lot_bot.config.settings import Settings
from lot_bot.wallapop.access_profile import AccessProfile, empty_profile
from lot_bot.wallapop.account_manager import AccountManager
from lot_bot.wallapop.auth import AuthMethod, DemoAuthMethod, build_auth_method
from lot_bot.wallapop.authorized_service import AuthorizedWallapopService
from lot_bot.wallapop.capabilities import Capability
from lot_bot.wallapop.mock_service import MockWallapopService
from lot_bot.wallapop.service import WallapopService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WallapopBackend:
    """Servicio activo mas el contexto que explica por que se ha elegido."""

    service: WallapopService
    profile: AccessProfile
    auth_method: AuthMethod
    demo: bool
    reason: str
    #: Lista concreta de lo que falta para poder conectar de verdad.
    missing: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return "MODO DEMO" if self.demo else "WALLAPOP REAL"

    @property
    def endpoint_map(self):
        """Compatibilidad: el transporte del perfil."""
        return self.profile.transport

    def describe_missing(self) -> str:
        if not self.missing:
            return ""
        return "\n".join(f"• {item}" for item in self.missing)


def _demo_backend(reason: str, missing: list[str] | None = None) -> WallapopBackend:
    return WallapopBackend(
        service=MockWallapopService(),
        profile=empty_profile(),
        auth_method=DemoAuthMethod(),
        demo=True,
        reason=reason,
        missing=missing or [],
    )


def build_backend(
    settings: Settings, account_manager: AccountManager | None = None
) -> WallapopBackend:
    """Construye el backend que corresponde a la configuracion actual."""

    # --- 1. DEMO explicito ---
    if settings.demo_mode:
        return _demo_backend("Modo DEMO activado en la configuración.")

    # --- 2. Perfil de acceso ---
    profile_path = settings.access_profile_path
    if profile_path is None:
        return _demo_backend(
            "No se ha indicado ningún perfil de acceso autorizado.",
            [
                "La variable WALLAPOP_ACCESS_PROFILE debe apuntar al fichero con el "
                "acceso que Wallapop te haya autorizado."
            ],
        )
    if not profile_path.is_file():
        return _demo_backend(
            f"No se encuentra el perfil de acceso en «{profile_path}».",
            [f"Crear el fichero {profile_path} a partir de config/access_profile.example.yaml."],
        )

    profile = AccessProfile.load(profile_path)

    # --- 3. Que falta: autenticacion y/o transporte ---
    missing = profile.missing_pieces()
    if missing:
        logger.warning("Perfil de acceso incompleto: se mantiene el modo DEMO.")
        return _demo_backend(
            "El perfil de acceso está incompleto: LOT Bot se mantiene en modo DEMO "
            "para no simular una conexión real.",
            missing,
        )

    # --- 4. El mecanismo de autenticacion debe estar listo ---
    auth_method = build_auth_method(profile.auth, redirect_uri=settings.wallapop_redirect_uri)
    pending = auth_method.missing_requirements()
    if pending:
        logger.warning(
            "El mecanismo '%s' no está listo: faltan %d dato(s).",
            auth_method.describe(),
            len(pending),
        )
        return _demo_backend(
            f"El mecanismo «{auth_method.describe()}» todavía no se puede usar: "
            f"faltan datos técnicos que debe facilitar Wallapop.",
            [f"{r.label} — {r.description} (se configura en: {r.where})" for r in pending],
        )

    # --- 5. Acceso real ---
    if account_manager is None:
        raise ValueError(
            "Se requiere AccountManager para el acceso real (proveedor de credenciales)."
        )
    account_manager.set_auth_method(auth_method)

    service = AuthorizedWallapopService(
        endpoint_map=profile.transport,
        credential_provider=account_manager.credential_provider(),
        auth_method_name=auth_method.describe(),
    )

    granted = service.capabilities()
    not_granted = sorted(c.value for c in Capability if c not in granted)
    if not_granted:
        logger.info(
            "Operaciones NO disponibles con el acceso actual: %s", ", ".join(not_granted)
        )

    return WallapopBackend(
        service=service,
        profile=profile,
        auth_method=auth_method,
        demo=False,
        reason=(
            f"Acceso autorizado activo mediante «{auth_method.describe()}» "
            f"({len(granted)} operaciones disponibles)."
        ),
        missing=[
            f"Operación no autorizada: {name}" for name in not_granted
        ],
    )
