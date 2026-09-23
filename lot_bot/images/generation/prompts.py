"""Construcción del prompt a partir de los datos REALES del anuncio.

Regla: solo se describe lo que figura en el anuncio (tipo de producto, color,
material, medida...). Lo que varía entre imágenes es el ENCUADRE y la ESCENA
(ángulo, luz, decoración neutra del dormitorio), nunca el producto: así cada
anuncio tiene una foto distinta sin atribuir al producto características que
no tiene.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: Traducciones de palabras frecuentes. Traducir no es inventar; lo que no
#: está aquí se pasa literal, entre comillas.
_COLORS = {
    "gris": "grey",
    "blanco": "white",
    "negro": "black",
    "beige": "beige",
    "crema": "cream",
    "marron": "brown",
    "azul": "blue",
    "verde": "green",
    "rojo": "red",
    "roble": "oak-coloured",
    "nogal": "walnut-coloured",
    "antracita": "anthracite",
    "cerezo": "cherry-coloured",
}
_MATERIALS = {
    "madera": "wood",
    "tela": "fabric",
    "polipiel": "faux leather",
    "piel": "leather",
    "metal": "metal",
    "aglomerado": "particle board",
    "mdf": "MDF",
    "terciopelo": "velvet",
}
_CONDITIONS = {"nuevo", "como nuevo", "en buen estado", "en condiciones aceptables"}

#: Variaciones de escena (no del producto).
_ANGLES = [
    "three-quarter view from the foot of the bed",
    "front view at eye level",
    "slightly elevated view from the bedroom door",
    "side view showing the full length",
    "three-quarter view from the left corner of the room",
    "low angle view from the side",
]
_LIGHT = [
    "soft natural morning light from a window",
    "bright diffuse daylight",
    "warm late-afternoon sunlight through sheer curtains",
    "overcast daylight, even soft shadows",
]
_ROOMS = [
    "a tidy bedroom with white walls and light wooden floor",
    "a small apartment bedroom with neutral beige walls",
    "a bright bedroom with a plain rug and a simple nightstand",
    "a minimalist bedroom with light grey walls",
    "a cosy bedroom with a window and plain curtains",
]

BASE_STYLE = (
    "Photorealistic product photograph taken with a camera in a real home, "
    "natural colours, realistic materials and proportions, sharp focus on the product, "
    "the product clearly visible and centred."
)
NEGATIVE = (
    "No people. No text, no letters, no numbers, no watermarks, no logos, no brand names, "
    "no price tags, no labels. Not an illustration, not a 3D render, not a drawing."
)


def _plain(text: str) -> str:
    normalised = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in normalised if not unicodedata.combining(c)).strip()


@dataclass(slots=True)
class ProductImageSpec:
    """Lo que se sabe del producto, sacado del anuncio."""

    product_type: str
    colors: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    size: str | None = None
    with_mattress: bool = False
    #: Características que no se sabe clasificar: se pasan literalmente.
    other_features: list[str] = field(default_factory=list)

    def product_sentence(self) -> str:
        parts = [f'a "{self.product_type}"']
        if self.product_type and _plain(self.product_type).startswith("canape"):
            parts.append("(Spanish storage bed base)")
        if self.colors:
            parts.append("in " + " and ".join(self.colors))
        if self.materials:
            parts.append("made of " + " and ".join(self.materials))
        sentence = " ".join(parts)
        if self.size:
            sentence += f", size {self.size} cm"
        if self.with_mattress:
            sentence += ", with a mattress on top"
        if self.other_features:
            sentence += ". Listing features: " + ", ".join(f'"{f}"' for f in self.other_features)
        return sentence


def _translate_words(text: str, table: dict[str, str]) -> list[str]:
    found = []
    for word in re.split(r"[\s,/·]+|\by\b", _plain(text)):
        if word in table and table[word] not in found:
            found.append(table[word])
    return found


def spec_from_master(master: Any, size: str | None = None) -> ProductImageSpec:
    """Especificación a partir del anuncio principal (solo sus datos)."""
    title_words = [w for w in re.split(r"\s+", (master.title or "").strip()) if w]
    product_type = title_words[0] if title_words else (master.name or "producto")
    colors: list[str] = []
    materials: list[str] = []
    others: list[str] = []
    for feature in master.features or []:
        plain = _plain(feature)
        if plain in _CONDITIONS:
            continue
        feature_colors = _translate_words(feature, _COLORS)
        feature_materials = _translate_words(feature, _MATERIALS)
        if feature_colors and not feature_materials:
            colors += [c for c in feature_colors if c not in colors]
        elif feature_materials and not feature_colors and len(plain.split()) == 1:
            materials += [m for m in feature_materials if m not in materials]
        else:
            others.append(feature)
    description = _plain(master.description or "")
    return ProductImageSpec(
        product_type=product_type,
        colors=colors,
        materials=materials,
        size=size,
        with_mattress="colchon" in description,
        other_features=others,
    )


def build_prompt(spec: ProductImageSpec, variation: int) -> str:
    """Prompt completo. `variation` cambia solo encuadre, luz y escena."""
    angle = _ANGLES[variation % len(_ANGLES)]
    light = _LIGHT[(variation // len(_ANGLES)) % len(_LIGHT)]
    room = _ROOMS[(variation * 7 + 3) % len(_ROOMS)]
    return (
        f"{BASE_STYLE} The photo shows {spec.product_sentence()}, "
        f"placed in {room}, {light}, {angle}. {NEGATIVE}"
    )
