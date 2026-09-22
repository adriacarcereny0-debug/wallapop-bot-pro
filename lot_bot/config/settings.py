"""Ajustes de la aplicacion, leidos de variables de entorno y del fichero .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from lot_bot.config.paths import get_paths, is_frozen, resource_root


def _env_file_candidates() -> list[Path]:
    """Ficheros .env a cargar, de menor a mayor prioridad."""
    candidates = [Path.cwd() / ".env"]
    if is_frozen():
        # Junto al ejecutable, para que el cliente pueda editarlo sin recompilar.
        candidates.append(resource_root() / ".env")
        candidates.append(Path(__file__).resolve().parents[2] / ".env")
    else:
        candidates.append(Path(__file__).resolve().parents[2] / ".env")
    try:
        candidates.append(get_paths().config / ".env")
    except Exception:  # pragma: no cover - solo en entornos muy restringidos
        pass
    return candidates


def load_env_files() -> None:
    for candidate in _env_file_candidates():
        if candidate.is_file():
            load_dotenv(candidate, override=False)


class Settings(BaseSettings):
    """Configuracion tipada de LOT Bot.

    Ningun secreto se escribe jamas en el repositorio: todos los campos
    sensibles se leen de variables de entorno o del almacen cifrado local.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # --- Modo de funcionamiento ---
    demo_mode: bool = Field(default=True, alias="LOT_BOT_DEMO_MODE")
    environment: Literal["development", "production"] = Field(
        default="development", alias="LOT_BOT_ENV"
    )
    log_level: str = Field(default="INFO", alias="LOT_BOT_LOG_LEVEL")
    language: Literal["es", "en"] = Field(default="es", alias="LOT_BOT_LANGUAGE")

    # --- Wallapop ---
    wallapop_client_id: str = Field(default="", alias="WALLAPOP_CLIENT_ID")
    wallapop_client_secret: str = Field(default="", alias="WALLAPOP_CLIENT_SECRET")
    wallapop_redirect_uri: str = Field(
        default="http://127.0.0.1:8723/callback", alias="WALLAPOP_REDIRECT_URI"
    )
    wallapop_endpoint_map: str = Field(default="", alias="WALLAPOP_ENDPOINT_MAP")
    wallapop_scopes: str = Field(default="", alias="WALLAPOP_SCOPES")

    # --- IA ---
    ai_provider: Literal["anthropic", "rules"] = Field(default="rules", alias="LOT_BOT_AI_PROVIDER")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    ai_model: str = Field(default="claude-sonnet-5", alias="LOT_BOT_AI_MODEL")
    ai_max_tokens: int = Field(default=4096, alias="LOT_BOT_AI_MAX_TOKENS")

    # --- Seguridad ---
    master_key: str = Field(default="", alias="LOT_BOT_MASTER_KEY")

    # --- Negocio ---
    business_whatsapp: str = Field(default="", alias="LOT_BOT_BUSINESS_WHATSAPP")
    business_name: str = Field(default="", alias="LOT_BOT_BUSINESS_NAME")

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            return "INFO"
        return value

    # ------------------------------------------------------------------
    # Propiedades derivadas
    # ------------------------------------------------------------------
    @property
    def scopes(self) -> list[str]:
        return [s for s in self.wallapop_scopes.replace(",", " ").split() if s]

    @property
    def endpoint_map_path(self) -> Path | None:
        if not self.wallapop_endpoint_map:
            return None
        return Path(self.wallapop_endpoint_map).expanduser()

    @property
    def has_wallapop_credentials(self) -> bool:
        """True solo si estan las tres piezas necesarias para OAuth."""
        return bool(
            self.wallapop_client_id
            and self.wallapop_client_secret
            and self.wallapop_redirect_uri
        )

    @property
    def can_use_real_wallapop(self) -> bool:
        """La integracion real requiere credenciales Y mapa de endpoints oficial."""
        path = self.endpoint_map_path
        return self.has_wallapop_credentials and path is not None and path.is_file()

    @property
    def effective_demo_mode(self) -> bool:
        """Modo DEMO efectivo.

        Si el usuario desactiva DEMO pero faltan credenciales o el mapa de
        endpoints oficial, seguimos en DEMO: nunca simulamos una conexion real.
        """
        if self.demo_mode:
            return True
        return not self.can_use_real_wallapop

    @property
    def ai_available(self) -> bool:
        if self.ai_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return True

    def describe_redactions(self) -> dict[str, str]:
        """Valores que jamas deben aparecer en logs ni en pantalla."""
        secrets = {
            "wallapop_client_secret": self.wallapop_client_secret,
            "anthropic_api_key": self.anthropic_api_key,
            "master_key": self.master_key,
        }
        return {k: v for k, v in secrets.items() if v}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_env_files()
    return Settings()  # type: ignore[call-arg]


def reload_settings() -> Settings:
    """Vuelve a leer la configuracion (tras editarla desde la pantalla de ajustes)."""
    get_settings.cache_clear()
    return get_settings()
