"""Datos del anuncio principal del negocio, tal y como los ha dado el cliente.

REGLA: estos valores se conservan EXACTAMENTE. No se corrigen ni se
reinterpretan, aunque parezcan raros (el titulo repetido, «Dormitorio Y
Madera», el precio de 11,44 €...). Son decisiones del cliente y solo cambian
cuando el usuario los edita.

Los precios de las ofertas y el WhatsApp NO van escritos dentro del texto de
la descripcion: son variables ({precio_135x190}, {whatsapp}) que se rellenan
con las ofertas y el contacto configurados. Al renderizarse, la descripcion
queda identica a la original del cliente.
"""

from __future__ import annotations

from typing import Any

#: Clave interna del anuncio principal.
MASTER_KEY = "canape-principal"
MASTER_NAME = "Canapés — Anuncio principal"

#: Descripcion exacta del cliente, una vez renderizada. Se usa en las pruebas
#: para garantizar que la plantilla produce este texto letra por letra.
CLIENT_DESCRIPTION_RENDERED = (
    "GRAN OFERTA LIMITADA! Renueva tu descanso hoy y paga menos ✨\n"
    "✨ Canapé + colchón 90x190 → 230€\n"
    "✨ Canapé + colchón 135x190 → 270€\n"
    "✨ Canapé + colchón 150x190 → 290€\n"
    "🚚 Transporte y montaje GRATUITO\n"
    "📲 Pide el tuyo ahora por WhatsApp: 603710542\n"
    "🕒 Solo por tiempo limitado. ¡No te quedes sin el tuyo!"
)

#: La misma descripcion, con los datos comerciales convertidos en variables.
CLIENT_DESCRIPTION_PATTERN = (
    "GRAN OFERTA LIMITADA! Renueva tu descanso hoy y paga menos ✨\n"
    "✨ Canapé + colchón 90x190 → {precio_90x190}€\n"
    "✨ Canapé + colchón 135x190 → {precio_135x190}€\n"
    "✨ Canapé + colchón 150x190 → {precio_150x190}€\n"
    "🚚 Transporte y montaje GRATUITO\n"
    "📲 Pide el tuyo ahora por WhatsApp: {whatsapp}\n"
    "🕒 Solo por tiempo limitado. ¡No te quedes sin el tuyo!"
)

CLIENT_MASTER_AD: dict[str, Any] = {
    "key": MASTER_KEY,
    "name": MASTER_NAME,
    "title": "Canapé canapé canapé canapé canapé canapé",
    "features": ["Nuevo", "Dormitorio Y Madera", "Gris y Blanco", "Madera"],
    "price": 11.44,
    "description": CLIENT_DESCRIPTION_PATTERN,
    "variants": [
        {"medida": "90x190", "precio": 230},
        {"medida": "135x190", "precio": 270},
        {"medida": "150x190", "precio": 290},
    ],
    "contact_whatsapp": "603710542",
    "delivery_note": "Transporte y montaje GRATUITO",
    # El cliente no ha indicado categoría: se deja vacía hasta que la elija.
    # (En DEMO se usa una categoría de demostración, sin guardarla aquí.)
    "category": "",
    "subcategory": "",
    "condition": "Nuevo",
    "tags": [],
    "keywords": [],
    "images": [],
    # Como se refiere el usuario a este anuncio en el chat.
    "aliases": [
        "canape",
        "canapes",
        "anuncio de canape",
        "anuncio del canape",
        "anuncio principal",
    ],
    "variables": {},
    "is_default": True,
}
