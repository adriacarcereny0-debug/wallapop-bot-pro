"""Perfiles de navegador aislados, uno por cuenta.

Cada cuenta tiene su propia carpeta de perfil de Chromium: cookies, almacenamiento
local, historial y caché NUNCA se comparten entre cuentas. El navegador cifra
sus cookies con el mecanismo del sistema (DPAPI en Windows).

Las carpetas viven en la carpeta de datos del usuario (en Windows,
%LOCALAPPDATA%\\LOT Bot\\browser_profiles), fuera del proyecto. Se rechaza
expresamente cualquier ubicación dentro de un repositorio Git para que una
sesión no pueda acabar subida por accidente.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_REF = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class UnsafeProfileLocation(RuntimeError):
    pass


def inside_git_repository(path: Path) -> bool:
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return True
    return False


class BrowserProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        if inside_git_repository(self.root):
            raise UnsafeProfileLocation(
                f"La carpeta de sesiones ({self.root}) está dentro de un repositorio Git. "
                "Por seguridad, las sesiones de Wallapop no se guardan ahí: usa la carpeta "
                "de datos del usuario (LOT_BOT_DATA_DIR fuera del proyecto)."
            )
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _check(self, account_ref: str) -> None:
        if not _SAFE_REF.match(account_ref or ""):
            raise ValueError(f"Referencia de cuenta no válida: {account_ref!r}")

    def profile_dir(self, account_ref: str, create: bool = True) -> Path:
        self._check(account_ref)
        path = self.root / account_ref
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def exists(self, account_ref: str) -> bool:
        self._check(account_ref)
        path = self.root / account_ref
        return path.is_dir() and any(path.iterdir())

    def lock(self, account_ref: str) -> threading.Lock:
        """Un único navegador por cuenta a la vez."""
        with self._guard:
            return self._locks.setdefault(account_ref, threading.Lock())

    def delete(self, account_ref: str) -> bool:
        """Borra la sesión guardada de la cuenta (cookies incluidas)."""
        self._check(account_ref)
        path = self.root / account_ref
        if not path.exists():
            return False
        with self.lock(account_ref):
            shutil.rmtree(path, ignore_errors=True)
        logger.info("Sesión de navegador borrada para la cuenta %s.", account_ref)
        return True
