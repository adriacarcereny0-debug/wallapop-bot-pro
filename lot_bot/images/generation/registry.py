"""Generación de imágenes únicas: registra cada imagen y evita repeticiones.

Por cada imagen se guarda: hash del fichero (SHA-256), hash perceptual (dHash
de 64 bits), prompt, semilla, fecha, anuncio y cuenta. Si una imagen nueva es
idéntica (mismo SHA-256) o casi idéntica (dHash a distancia ≤ umbral) a una ya
registrada, se descarta y se genera otra variación.
"""

from __future__ import annotations

import hashlib
import logging
import random
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from lot_bot.database.engine import Database
from lot_bot.database.models import GeneratedImage
from lot_bot.images.generation.base import GenerationError, ImageGenerator
from lot_bot.images.generation.prompts import ProductImageSpec, build_prompt

logger = logging.getLogger(__name__)

#: Distancia de Hamming (sobre 64 bits) por debajo de la cual dos imágenes se
#: consideran la misma.
DUPLICATE_THRESHOLD = 4


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash(path: Path) -> str:
    """Hash perceptual por diferencias (dHash) de 64 bits, en hexadecimal."""
    with Image.open(path) as image:
        small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


@dataclass(slots=True)
class GeneratedImageResult:
    path: Path
    prompt: str
    seed: int
    attempts: int
    provider: str
    is_demo: bool


class ImageGenerationService:
    def __init__(
        self,
        database: Database,
        generator: ImageGenerator,
        output_dir: Path,
        *,
        max_attempts: int = 3,
        rng: random.Random | None = None,
    ) -> None:
        self._db = database
        self.generator = generator
        self._dir = output_dir
        self._max_attempts = max_attempts
        self._rng = rng or random.Random()

    def set_generator(self, generator: ImageGenerator) -> None:
        self.generator = generator

    # ------------------------------------------------------------------
    def find_duplicate(self, sha: str, phash: str) -> GeneratedImage | None:
        with self._db.session_scope() as session:
            exact = session.scalars(
                select(GeneratedImage).where(GeneratedImage.file_hash == sha)
            ).first()
            if exact is not None:
                session.expunge(exact)
                return exact
            for row in session.scalars(select(GeneratedImage)).all():
                if hamming(row.perceptual_hash, phash) <= DUPLICATE_THRESHOLD:
                    session.expunge(row)
                    return row
        return None

    def generate_unique(
        self,
        spec: ProductImageSpec,
        *,
        variation: int,
        subject: str,
        account_ref: str | None = None,
        task_id: int | None = None,
    ) -> GeneratedImageResult:
        """Genera una imagen que no se repite con ninguna anterior."""
        last_error: str = ""
        for attempt in range(1, self._max_attempts + 1):
            prompt = build_prompt(spec, variation + (attempt - 1) * 5)
            seed = self._rng.randint(1, 2_000_000_000)
            destination = self._dir / f"gen-{uuid.uuid4().hex[:12]}"
            path = self.generator.generate(prompt, seed, destination)
            sha = file_sha256(path)
            phash = dhash(path)
            duplicate = self.find_duplicate(sha, phash)
            if duplicate is not None:
                last_error = f"repetida con la imagen #{duplicate.id}"
                logger.info(
                    "Imagen generada descartada por %s; se genera otra variación.", last_error
                )
                path.unlink(missing_ok=True)
                continue
            with self._db.session_scope() as session:
                session.add(
                    GeneratedImage(
                        path=str(path),
                        file_hash=sha,
                        perceptual_hash=phash,
                        prompt=prompt,
                        seed=seed,
                        provider=self.generator.name,
                        subject=subject[:200],
                        account_ref=account_ref,
                        task_id=task_id,
                    )
                )
            return GeneratedImageResult(
                path=path,
                prompt=prompt,
                seed=seed,
                attempts=attempt,
                provider=self.generator.name,
                is_demo=self.generator.is_demo,
            )
        raise GenerationError(
            f"No se ha conseguido una imagen distinta tras {self._max_attempts} intentos "
            f"({last_error}).",
            code="DUPLICATE",
        )

    def history(self, limit: int = 50) -> list[dict]:
        with self._db.session_scope() as session:
            rows = session.scalars(
                select(GeneratedImage).order_by(GeneratedImage.id.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": r.id,
                    "ruta": r.path,
                    "hash": r.file_hash,
                    "prompt": r.prompt,
                    "fecha": r.created_at,
                    "anuncio": r.subject,
                    "cuenta": r.account_ref,
                }
                for r in rows
            ]
