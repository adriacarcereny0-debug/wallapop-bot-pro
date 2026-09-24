"""Carga de la descripción de la web de Wallapop (`wallapop_browser.yaml`).

Todos los selectores y direcciones viven en ese fichero: el código no
contiene ninguno. Se puede sobrescribir con una copia local en la carpeta de
configuración del usuario (nunca en el repositorio).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from lot_bot.config.paths import get_paths

logger = logging.getLogger(__name__)

LOCAL_FILENAME = "wallapop_browser.local.yaml"


def default_config_path() -> Path:
    return get_paths().resources / "wallapop_browser.yaml"


def local_config_path() -> Path:
    return get_paths().config / LOCAL_FILENAME


@dataclass(slots=True)
class Step:
    name: str
    action: str
    targets: list[str] = field(default_factory=list)
    value: str = ""
    option: str = ""
    url: str = ""
    optional: bool = False
    optional_if_empty: bool = False


@dataclass(slots=True)
class BrowserSiteConfig:
    verified: bool
    visible: bool
    channels: list[str]
    locale: str
    timeout_ms: int
    urls: dict[str, str]
    logged_in: list[str]
    logged_out: list[str]
    verification: list[str]
    user_name: list[str]
    price_format: str
    steps: list[Step]
    success_url_regex: str
    success_texts: list[str]
    success_timeout_ms: int
    check_url: str = "subir"
    check_url_contains: str = "/app/"
    check_wait_ms: int = 4000
    check_private: list[str] = field(default_factory=list)
    keep_open_seconds: int = 900
    stats_patterns: dict[str, str] = field(default_factory=dict)
    source: Path | None = None

    def url(self, name: str) -> str:
        value = self.urls.get(name)
        if not value:
            raise KeyError(f"La dirección «{name}» no está en {self.source}.")
        return value

    @property
    def item_url_regex(self) -> str:
        return self.urls.get("anuncio_regex", "")

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: Path | None = None) -> BrowserSiteConfig:
        nav = data.get("navegador") or {}
        session = data.get("sesion") or {}
        publish = data.get("publicar") or {}
        success = publish.get("exito") or {}
        check = session.get("comprobacion") or {}
        steps = [
            Step(
                name=str(s.get("nombre", "")),
                action=str(s.get("accion", "")),
                targets=[str(t) for t in (s.get("objetivos") or [])],
                value=str(s.get("valor", "")),
                option=str(s.get("opcion", "")),
                url=str(s.get("url", "")),
                optional=bool(s.get("opcional", False)),
                optional_if_empty=bool(s.get("opcional_si_vacio", False)),
            )
            for s in (publish.get("pasos") or [])
        ]
        return cls(
            verified=bool(data.get("verificado", False)),
            visible=bool(nav.get("visible", True)),
            channels=[str(c) for c in (nav.get("canales") or ["chromium"])],
            locale=str(nav.get("idioma", "es-ES")),
            timeout_ms=int(nav.get("tiempo_espera_ms", 20000)),
            urls={str(k): str(v) for k, v in (data.get("urls") or {}).items()},
            logged_in=[str(x) for x in (session.get("iniciada") or [])],
            logged_out=[str(x) for x in (session.get("sin_sesion") or [])],
            verification=[str(x) for x in (session.get("verificacion") or [])],
            user_name=[str(x) for x in (session.get("nombre_usuario") or [])],
            price_format=str(publish.get("formato_precio", "coma")),
            steps=steps,
            success_url_regex=str(success.get("url_regex", "")),
            success_texts=[str(x) for x in (success.get("textos") or [])],
            success_timeout_ms=int(success.get("tiempo_espera_ms", 60000)),
            check_url=str(check.get("url", "subir")),
            check_url_contains=str(check.get("url_debe_contener", "/app/")),
            check_wait_ms=int(check.get("espera_ms", 4000)),
            check_private=[str(x) for x in (check.get("privada") or [])],
            keep_open_seconds=int(session.get("mantener_abierto_s", 900)),
            stats_patterns={
                str(k): str(v) for k, v in (data.get("estadisticas") or {}).items() if v
            },
            source=source,
        )


def load_site_config(path: Path | None = None) -> BrowserSiteConfig:
    """Usa la copia local si existe; si no, la incluida en el programa."""
    candidates = [path] if path else [local_config_path(), default_config_path()]
    for candidate in candidates:
        if candidate and candidate.is_file():
            with open(candidate, encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            return BrowserSiteConfig.from_dict(data, source=candidate)
    raise FileNotFoundError("No se encuentra wallapop_browser.yaml.")
