"""El repositorio debe contener todo el código fuente que importa la aplicación.

Protege contra reglas de .gitignore demasiado amplias (p. ej. `logs/` ignoraba el
paquete `lot_bot/logs/`, y un clon limpio fallaba con ModuleNotFoundError).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="sin git")
def test_ningun_fichero_de_codigo_esta_ignorado_por_git():
    sources = [
        str(p.relative_to(ROOT))
        for folder in ("lot_bot", "tests", "build", "scripts")
        for p in (ROOT / folder).rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in {".py", ".yaml", ".ps1", ".sh", ".spec", ".qss", ".svg", ".ico", ".png"}
    ]
    sources += [p.name for p in ROOT.glob("*.py")]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        input="\n".join(sources),
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.stdout.strip() == "", (
        f"Ficheros de código ignorados por .gitignore:\n{result.stdout}"
    )
