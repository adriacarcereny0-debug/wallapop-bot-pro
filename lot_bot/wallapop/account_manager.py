"""Gestion de cuentas de Wallapop y de sus tokens.

Garantias de aislamiento multicuenta:
  * Cada cuenta tiene un `internal_ref` unico que identifica todo lo suyo.
  * Los tokens se guardan cifrados y solo se descifran en el momento de usarse.
  * Ninguna consulta de anuncios, mensajes o inventario cruza cuentas: siempre
    se filtra por `account_id`.
  * Nunca se guarda la contrasena de Wallapop.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from lot_bot.config.secrets import SecretBox, SecretsError, get_secret_box
from lot_bot.database.engine import Database
from lot_bot.database.models import Account, AccountStatus
from lot_bot.logs.redaction import register_secret
from lot_bot.wallapop.dto import OAuthTokens
from lot_bot.wallapop.errors import AuthenticationError, ConfigurationError
from lot_bot.wallapop.oauth import (
    LocalCallbackServer,
    OAuthClient,
    generate_pkce_pair,
    new_state,
    open_browser,
)

logger = logging.getLogger(__name__)

#: Margen antes de la caducidad a partir del cual se refresca el token.
REFRESH_MARGIN = timedelta(minutes=5)


@dataclass(slots=True)
class AccountInfo:
    """Vista de solo lectura de una cuenta, apta para la interfaz.

    No contiene tokens: la interfaz nunca los necesita.
    """

    id: int
    internal_ref: str
    alias: str
    status: AccountStatus
    status_detail: str | None
    wallapop_login: str | None
    wallapop_user_id: str | None
    last_sync_at: datetime | None
    token_expires_at: datetime | None
    is_demo: bool
    scopes: list[str]

    @property
    def is_connected(self) -> bool:
        return self.status == AccountStatus.CONNECTED

    @property
    def status_label(self) -> str:
        return {
            AccountStatus.CONNECTED: "Conectada",
            AccountStatus.DISCONNECTED: "Desconectada",
            AccountStatus.EXPIRED: "Sesion caducada",
            AccountStatus.ERROR: "Error",
        }[self.status]


class AccountManager:
    """Alta, conexion y renovacion de credenciales de cuentas."""

    def __init__(
        self,
        database: Database,
        secret_box: SecretBox | None = None,
        oauth_client: OAuthClient | None = None,
    ) -> None:
        self._db = database
        self._box = secret_box or get_secret_box()
        self._oauth = oauth_client

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------
    def list_accounts(self, include_demo: bool = True) -> list[AccountInfo]:
        with self._db.session_scope() as session:
            stmt = select(Account).order_by(Account.id)
            accounts = session.scalars(stmt).all()
            return [
                self._to_info(a) for a in accounts if include_demo or not a.is_demo
            ]

    def get_account(self, internal_ref: str) -> AccountInfo | None:
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            return self._to_info(account) if account else None

    def get_account_by_id(self, account_id: int) -> AccountInfo | None:
        with self._db.session_scope() as session:
            account = session.get(Account, account_id)
            return self._to_info(account) if account else None

    def resolve_ref(self, identifier: str | int) -> str | None:
        """Acepta id numerico, internal_ref o alias y devuelve el internal_ref."""
        with self._db.session_scope() as session:
            if isinstance(identifier, int) or str(identifier).isdigit():
                account = session.get(Account, int(identifier))
                return account.internal_ref if account else None
            text = str(identifier).strip()
            account = session.scalar(select(Account).where(Account.internal_ref == text))
            if account:
                return account.internal_ref
            account = session.scalar(select(Account).where(Account.alias == text))
            if account:
                return account.internal_ref
            lowered = text.lower()
            for candidate in session.scalars(select(Account)).all():
                if candidate.alias.lower() == lowered or lowered in candidate.alias.lower():
                    return candidate.internal_ref
            return None

    @staticmethod
    def _find(session, internal_ref: str) -> Account | None:
        return session.scalar(select(Account).where(Account.internal_ref == internal_ref))

    @staticmethod
    def _to_info(account: Account) -> AccountInfo:
        return AccountInfo(
            id=account.id,
            internal_ref=account.internal_ref,
            alias=account.alias,
            status=account.status,
            status_detail=account.status_detail,
            wallapop_login=account.wallapop_login,
            wallapop_user_id=account.wallapop_user_id,
            last_sync_at=account.last_sync_at,
            token_expires_at=account.token_expires_at,
            is_demo=account.is_demo,
            scopes=(account.scopes or "").split(),
        )

    # ------------------------------------------------------------------
    # Alta y baja
    # ------------------------------------------------------------------
    def add_account(
        self, alias: str, *, is_demo: bool = False, internal_ref: str | None = None
    ) -> AccountInfo:
        ref = internal_ref or f"acc-{uuid.uuid4().hex[:10]}"
        with self._db.session_scope() as session:
            if self._find(session, ref):
                raise ValueError(f"Ya existe una cuenta con la referencia '{ref}'.")
            account = Account(
                internal_ref=ref,
                alias=alias.strip() or ref,
                is_demo=is_demo,
                status=AccountStatus.CONNECTED if is_demo else AccountStatus.DISCONNECTED,
                status_detail="Cuenta de demostracion" if is_demo else None,
            )
            session.add(account)
            session.flush()
            logger.info("Cuenta anadida: %s (%s)", account.alias, ref)
            return self._to_info(account)

    def rename_account(self, internal_ref: str, alias: str) -> AccountInfo | None:
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is None:
                return None
            account.alias = alias.strip() or account.alias
            session.flush()
            return self._to_info(account)

    def remove_account(self, internal_ref: str) -> bool:
        """Elimina la cuenta y TODO lo que le pertenece (anuncios, mensajes)."""
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is None:
                return False
            session.delete(account)
            logger.info("Cuenta eliminada: %s", internal_ref)
            return True

    # ------------------------------------------------------------------
    # Conexion
    # ------------------------------------------------------------------
    def set_oauth_client(self, client: OAuthClient | None) -> None:
        self._oauth = client

    def connect_interactive(self, internal_ref: str, timeout: float = 300.0) -> AccountInfo:
        """Lanza el flujo OAuth en el navegador y guarda los tokens cifrados.

        El usuario introduce sus credenciales en el dominio de Wallapop.
        LOT Bot nunca ve ni guarda la contrasena.
        """
        if self._oauth is None:
            raise ConfigurationError(
                "Cliente OAuth no configurado.",
                user_message=(
                    "No se puede conectar la cuenta: faltan las credenciales de Wallapop "
                    "o el fichero de endpoints oficial."
                ),
            )
        state = new_state()
        verifier, challenge = generate_pkce_pair()
        url = self._oauth.build_authorization_url(state, challenge)

        with LocalCallbackServer(self._oauth.redirect_uri) as server:
            open_browser(url)
            result = server.wait(timeout=timeout)

        if result.error or not result.code:
            self._mark_error(internal_ref, result.error or "Autorizacion cancelada.")
            raise AuthenticationError(
                f"Autorizacion no completada: {result.error or 'sin codigo'}",
                user_message="No se ha completado la autorizacion en el navegador.",
            )
        if result.state != state:
            self._mark_error(internal_ref, "Parametro 'state' no coincide.")
            raise AuthenticationError(
                "El parametro 'state' no coincide.",
                user_message="La respuesta de autorizacion no es valida. Intentalo de nuevo.",
            )

        tokens = self._oauth.exchange_code(result.code, verifier)
        return self.store_tokens(internal_ref, tokens)

    def store_tokens(self, internal_ref: str, tokens: OAuthTokens) -> AccountInfo:
        register_secret(tokens.access_token)
        if tokens.refresh_token:
            register_secret(tokens.refresh_token)
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is None:
                raise ValueError(f"Cuenta '{internal_ref}' no encontrada.")
            account.access_token_enc = self._box.encrypt(tokens.access_token)
            account.refresh_token_enc = self._box.encrypt(tokens.refresh_token)
            account.token_expires_at = _naive_utc(tokens.expires_at)
            account.scopes = " ".join(tokens.scopes)
            account.status = AccountStatus.CONNECTED
            account.status_detail = None
            session.flush()
            logger.info("Cuenta '%s' conectada correctamente.", internal_ref)
            return self._to_info(account)

    def disconnect(self, internal_ref: str, revoke: bool = True) -> bool:
        """Borra los tokens locales y, si se puede, los revoca en Wallapop."""
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is None:
                return False
            token = None
            if revoke and self._oauth is not None and account.access_token_enc:
                try:
                    token = self._box.decrypt(account.access_token_enc)
                except SecretsError:
                    token = None
            account.access_token_enc = None
            account.refresh_token_enc = None
            account.token_expires_at = None
            account.scopes = None
            account.status = AccountStatus.DISCONNECTED
            account.status_detail = "Desconectada por el usuario"
            session.flush()

        if token and self._oauth is not None:
            self._oauth.revoke(token)
        logger.info("Cuenta '%s' desconectada.", internal_ref)
        return True

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------
    def get_access_token(self, internal_ref: str) -> str:
        """Devuelve un access token valido, refrescandolo si esta a punto de caducar.

        Es el `TokenProvider` que consume `ConnectWallapopService`.
        """
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is None:
                raise AuthenticationError(f"Cuenta '{internal_ref}' no encontrada.")
            if not account.access_token_enc:
                account.status = AccountStatus.DISCONNECTED
                raise AuthenticationError(f"La cuenta '{internal_ref}' no esta conectada.")

            expires_at = account.token_expires_at
            needs_refresh = (
                expires_at is not None
                and expires_at <= datetime.now(UTC).replace(tzinfo=None) + REFRESH_MARGIN
            )
            refresh_enc = account.refresh_token_enc
            access = self._box.decrypt(account.access_token_enc)

        if not needs_refresh:
            return access or ""

        if not refresh_enc:
            self._mark_expired(internal_ref)
            raise AuthenticationError(
                f"El token de '{internal_ref}' ha caducado y no hay refresh token.",
                user_message="La sesion de la cuenta ha caducado. Vuelve a conectarla.",
            )
        if self._oauth is None:
            self._mark_expired(internal_ref)
            raise ConfigurationError("No hay cliente OAuth para refrescar el token.")

        refresh_token = self._box.decrypt(refresh_enc)
        logger.info("Refrescando token de la cuenta '%s'.", internal_ref)
        try:
            tokens = self._oauth.refresh(refresh_token or "")
        except AuthenticationError:
            self._mark_expired(internal_ref)
            raise
        self.store_tokens(internal_ref, tokens)
        return tokens.access_token

    def token_provider(self):
        """Callable listo para inyectar en `ConnectWallapopService`."""
        return self.get_access_token

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    def mark_synced(self, internal_ref: str) -> None:
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is not None:
                account.last_sync_at = datetime.now(UTC).replace(tzinfo=None)
                account.status = AccountStatus.CONNECTED
                account.status_detail = None

    def _mark_error(self, internal_ref: str, detail: str) -> None:
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is not None:
                account.status = AccountStatus.ERROR
                account.status_detail = detail[:500]

    def _mark_expired(self, internal_ref: str) -> None:
        with self._db.session_scope() as session:
            account = self._find(session, internal_ref)
            if account is not None:
                account.status = AccountStatus.EXPIRED
                account.status_detail = "La sesion ha caducado. Vuelve a conectar la cuenta."

    def ensure_demo_accounts(self, demo_refs: list[tuple[str, str]]) -> list[AccountInfo]:
        """Crea las cuentas de demostracion si no existen."""
        created: list[AccountInfo] = []
        for ref, alias in demo_refs:
            existing = self.get_account(ref)
            if existing is None:
                created.append(self.add_account(alias, is_demo=True, internal_ref=ref))
            else:
                created.append(existing)
        return created


def _naive_utc(value: datetime | None) -> datetime | None:
    """SQLite guarda datetimes sin zona: normalizamos a UTC naive."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
