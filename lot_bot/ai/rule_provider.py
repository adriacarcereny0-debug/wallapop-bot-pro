"""Proveedor de ordenes directas, sin conexion a ningun servicio de IA.

Reconoce las ordenes habituales del cliente en espanol y las traduce a llamadas
a herramientas. Es 100% local y determinista: util cuando no hay clave de API,
no hay internet, o el cliente prefiere no usar un servicio externo.

No pretende entender lenguaje libre: cuando no reconoce una orden lo dice y
ofrece lo que si sabe hacer, en vez de improvisar.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from lot_bot.ai.provider import AIProvider, ProviderReply, ToolCall

logger = logging.getLogger(__name__)

_SIZE_RE = re.compile(r"(\d{2,3})\s*[x×]\s*(\d{2,3})", re.IGNORECASE)
_PRICE_RE = re.compile(r"(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:€|eur|euros)", re.IGNORECASE)
_BARE_NUMBER_RE = re.compile(r"\b(\d{2,6}(?:[.,]\d{1,2})?)\b")


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def _extract_size(text: str) -> str | None:
    match = _SIZE_RE.search(text)
    return f"{match.group(1)}x{match.group(2)}" if match else None


def _extract_price(text: str) -> float | None:
    match = _PRICE_RE.search(text)
    if not match:
        # "ponlo a 269" sin simbolo de moneda
        candidates = [m for m in _BARE_NUMBER_RE.finditer(text)]
        size = _SIZE_RE.search(text)
        for candidate in candidates:
            if size and size.start() <= candidate.start() < size.end():
                continue
            match = candidate
            break
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _extract_quoted(text: str) -> str | None:
    match = re.search(r"[\"'«]([^\"'»]{2,})[\"'»]", text)
    return match.group(1).strip() if match else None


def _extract_product_term(normalized: str) -> str | None:
    """Extrae el tipo de producto mencionado ('canape', 'colchon'...)."""
    for term in ("canape", "colchon", "sofa", "cabecero", "somier", "almohada"):
        if term in normalized:
            return term
    return None


class RuleBasedProvider(AIProvider):
    """Traduce ordenes escritas a llamadas de herramientas, sin IA externa."""

    name = "Órdenes directas (sin IA externa)"
    natural_language = False

    def describe(self) -> str:
        return self.name

    # ------------------------------------------------------------------
    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderReply:
        # Si la ultima vuelta ya trajo resultados de herramientas, resumimos.
        last = messages[-1] if messages else {}
        if last.get("role") == "user" and isinstance(last.get("content"), list):
            return ProviderReply(text=self._summarize_tool_results(last["content"]))

        text = _last_user_text(messages)
        if not text:
            return ProviderReply(text=self._help())

        call = self._match(text)
        if call is None:
            return ProviderReply(text=self._help(text))
        return ProviderReply(text="", tool_calls=[call], finished=False)

    # ------------------------------------------------------------------
    def _match(self, text: str) -> ToolCall | None:
        normalized = _normalize(text)
        size = _extract_size(normalized)
        term = _extract_product_term(normalized)

        def call(name: str, **args: Any) -> ToolCall:
            return ToolCall(id=f"rule-{name}", name=name, arguments={k: v for k, v in args.items() if v is not None})

        # --- Precio ---
        if re.search(r"\b(cambia|cambiar|pon|poner|actualiza|sube|baja|modifica)\b.*\bprecio\b", normalized) or (
            re.search(r"\bprecio\b", normalized) and re.search(r"\ba\s+\d", normalized)
        ):
            price = _extract_price(normalized)
            if price is None:
                return None
            return call("update_price", precio=price, medida=size, texto=term)

        # --- Analisis de precios / mercado ---
        if re.search(r"\b(analiza|analizar|compara|comparar)\b.*\b(precio|precios|mercado)\b", normalized):
            if "mercado" in normalized:
                return call("get_market_data", consulta=term or "", medida=size)
            return call("analyze_prices", texto=term, medida=size)

        # --- Duplicados ---
        if "duplicad" in normalized or "repetid" in normalized:
            if "imagen" in normalized or "foto" in normalized:
                return call("find_duplicate_images")
            ambito = "anuncios" if "anuncio" in normalized else ("productos" if "producto" in normalized else "todo")
            return call("detect_duplicates", ambito=ambito, texto=term)

        # --- Revision de calidad ---
        if re.search(r"\b(revisa|revisar|comprueba|comprobar|dime)\b", normalized) and re.search(
            r"\b(incomplet|incorrect|falta|error|mal)\w*", normalized
        ):
            if "producto" in normalized or "catalogo" in normalized:
                return call("validate_products", texto=term, medida=size)
            return call("validate_listings", texto=term)

        # --- Busqueda de anuncios ---
        if re.search(r"\b(busca|buscar|encuentra|muestra|ensename|lista|listar|dame)\b", normalized) and (
            "anuncio" in normalized or "publicad" in normalized
        ):
            return call("search_listings", texto=term, medida=size)

        # --- Busqueda de productos ---
        if re.search(r"\b(busca|buscar|encuentra|muestra|lista|listar|dame)\b", normalized) and (
            "producto" in normalized or "catalogo" in normalized
        ):
            return call("search_products", texto=term, medida=size)

        # --- Inventario / stock ---
        if "inventario" in normalized or "stock" in normalized:
            return call("get_inventory", texto=term, medida=size)

        # --- Cuentas ---
        if "cuenta" in normalized and re.search(r"\b(estado|conectad|cuantas|lista|ver)\b", normalized):
            return call("get_account_status")

        # --- Mensajes ---
        if "mensaje" in normalized or "comprador" in normalized or "conversacion" in normalized:
            if re.search(r"\b(responde|contesta|genera|prepara)\b", normalized):
                number = re.search(r"\b(\d+)\b", normalized)
                if number:
                    return call("prepare_message_response", conversacion=int(number.group(1)))
                return call("get_messages", solo_sin_leer=True)
            return call("get_messages")

        # --- Generacion de contenido ---
        if re.search(r"\b(genera|generar|crea|redacta)\b.*\b(titulo|descripcion|etiqueta)\w*", normalized):
            reference = _extract_quoted(text)
            if not reference:
                return None
            if "descripcion" in normalized:
                return call("generate_description", producto=reference)
            if "etiqueta" in normalized:
                return call("generate_tags", producto=reference)
            return call("generate_title", producto=reference)

        # --- Vista previa / preparar publicacion ---
        if re.search(r"\b(prepara|preparar|vista previa|previsualiza)\b", normalized):
            reference = _extract_quoted(text)
            return call("preview_listing", producto=reference) if reference else None

        # --- Publicar ---
        if re.search(r"\b(publica|publicar|sube|subir)\b", normalized):
            reference = _extract_quoted(text)
            return call("create_listing", producto=reference) if reference else None

        # --- Sincronizar ---
        if re.search(r"\b(sincroniza|sincronizar|actualiza los anuncios|descarga)\b", normalized):
            return call("sync_listings")

        # --- Operaciones disponibles ---
        if re.search(r"\b(que puedes hacer|ayuda|funciones|operaciones)\b", normalized):
            return call("get_available_operations")

        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _summarize_tool_results(content: list[Any]) -> str:
        """Convierte los resultados de las herramientas en texto legible."""
        import json

        lines: list[str] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            payload = block.get("content")
            if isinstance(payload, list):
                payload = " ".join(
                    str(p.get("text", "")) for p in payload if isinstance(p, dict)
                )
            try:
                data = json.loads(str(payload))
            except (ValueError, TypeError):
                lines.append(str(payload))
                continue
            lines.append(_format_tool_payload(data))
        return "\n\n".join(linea for linea in lines if linea) or "Hecho."

    @staticmethod
    def _help(attempted: str = "") -> str:
        prefix = ""
        if attempted:
            prefix = (
                f"No he entendido la orden «{attempted.strip()[:120]}».\n"
                f"Estoy funcionando en modo de órdenes directas (sin IA externa), "
                f"así que necesito instrucciones concretas.\n\n"
            )
        return prefix + (
            "Puedo hacer, por ejemplo:\n"
            "• «Cambia el precio de los canapés de 135x190 a 269 €»\n"
            "• «Busca todos los anuncios de canapés»\n"
            "• «Revisa qué anuncios tienen información incompleta»\n"
            "• «Comprueba si hay duplicados»\n"
            "• «Analiza los precios de los canapés»\n"
            "• «Muéstrame el inventario»\n"
            "• «Estado de las cuentas»\n"
            "• «Genera el título de \"CAN-135X190-GRI\"»\n"
            "• «Prepara la vista previa de \"CAN-135X190-GRI\"»\n"
            "• «Mensajes sin leer»\n\n"
            "Para entender lenguaje natural libre, configura una clave de IA en "
            "Ajustes → IA."
        )


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                return " ".join(texts)
    return ""


# ---------------------------------------------------------------------------
# Formateo legible de los resultados
# ---------------------------------------------------------------------------
#: Claves de listas que sabemos mostrar y el campo que las identifica.
_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "anuncios": ("cuenta", "titulo", "precio"),
    "productos": ("sku", "nombre", "precio", "stock"),
    "cuentas": ("nombre", "estado", "anuncios_locales"),
    "inventario": ("sku", "nombre", "stock"),
    "conversaciones": ("cuenta", "comprador", "anuncio"),
    "incompletos": ("subject", "score"),
    "incorrectos": ("subject", "score"),
    "vistas_previas": ("cuenta", "titulo", "precio", "publicable"),
}

MAX_ROWS = 15


def _format_tool_payload(data: Any) -> str:
    """Convierte la respuesta de una herramienta en texto para el usuario."""
    if not isinstance(data, dict):
        return str(data)

    lines: list[str] = []
    summary = data.get("resumen")
    if summary:
        lines.append(str(summary))

    if data.get("estado") == "PENDIENTE_DE_CONFIRMACION":
        for item in data.get("plan") or []:
            lines.append(f"  • {item}")
        return "\n".join(lines)

    payload = data.get("datos") or {}
    if not isinstance(payload, dict):
        return "\n".join(lines)

    for key, fields in _LIST_FIELDS.items():
        rows = payload.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        lines.append(f"\n{key.capitalize()}:")
        for row in rows[:MAX_ROWS]:
            if isinstance(row, dict):
                parts = [
                    f"{_pretty(row.get(field))}" for field in fields if row.get(field) is not None
                ]
                lines.append("  · " + " · ".join(parts) if parts else f"  · {row}")
            else:
                lines.append(f"  · {row}")
        if len(rows) > MAX_ROWS:
            lines.append(f"  … y {len(rows) - MAX_ROWS} más.")

    for key in ("por_cuenta", "estadisticas", "resumen_calidad"):
        value = payload.get(key)
        if isinstance(value, dict) and value:
            lines.append(f"\n{key.replace('_', ' ').capitalize()}:")
            for name, count in list(value.items())[:MAX_ROWS]:
                lines.append(f"  · {name}: {_pretty(count)}")

    for key in ("grupos", "etiquetas", "sin_stock", "faltan"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            lines.append(f"\n{key.capitalize()}: " + ", ".join(str(v) for v in value[:20]))

    for key in ("titulo", "descripcion", "respuesta"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            lines.append(f"\n{key.capitalize()}:\n{value}")

    return "\n".join(lines)


def _pretty(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in list(value.items())[:5])
    return str(value)
