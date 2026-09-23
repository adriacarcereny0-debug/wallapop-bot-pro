"""Herramientas del anuncio principal (plantilla maestra de canapés).

Permiten que el usuario hable del anuncio sin explicarlo cada vez:
«sube el canapé», «publica 10 canapés», «prepara el anuncio de canapé».

Garantías:
  * Publicar NUNCA modifica la plantilla.
  * Cambiar algo solo para una publicación («para este anuncio pon 12 €») se
    guarda en esa publicación.
  * La plantilla solo cambia con `update_master_ad`, que pide confirmación.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from lot_bot.ai.tools.base import (
    Tool,
    ToolCategory,
    ToolContext,
    ToolResult,
    confirm_first,
    fail,
    ok,
)
from lot_bot.master_ad.service import EDITABLE_FIELDS, OVERRIDABLE_FIELDS

#: Nombres en español que puede usar el usuario (o la IA) para cada campo.
FIELD_ALIASES = {
    "titulo": "title",
    "título": "title",
    "precio": "price",
    "descripcion": "description",
    "descripción": "description",
    "caracteristicas": "features",
    "características": "features",
    "categoria": "category",
    "categoría": "category",
    "subcategoria": "subcategory",
    "estado": "condition",
    "etiquetas": "tags",
    "palabras_clave": "keywords",
    "whatsapp": "contact_whatsapp",
    "contacto": "contact_whatsapp",
    "ofertas": "variants",
    "medidas": "variants",
    "nombre": "name",
}


def _normalize_changes(raw: dict[str, Any] | None) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        changes[FIELD_ALIASES.get(str(key).lower(), str(key))] = value
    return changes


def _target_accounts(context: ToolContext, requested: Any) -> tuple[list[str], list[str]]:
    """Cuentas donde publicar. Devuelve (referencias, no_encontradas)."""
    if requested:
        values = requested if isinstance(requested, list) else [requested]
        refs: list[str] = []
        missing: list[str] = []
        for value in values:
            ref = context.app.accounts.resolve_ref(str(value))
            (refs if ref else missing).append(ref or str(value))
        return refs, missing
    demo = context.app.demo_mode
    return (
        [
            a.internal_ref
            for a in context.app.accounts.list_accounts()
            if a.is_connected and (demo or not a.is_demo)
        ],
        [],
    )


def _price(value: float | None) -> str:
    return f"{value:.2f} €".replace(".", ",") if value is not None else "sin precio"


# ---------------------------------------------------------------------------
def _get_master_ad(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = context.app.master_ads.get(args.get("plantilla"))
    if view is None:
        return fail("No hay ningún anuncio principal configurado.")
    stats = context.app.master_ads.stats(view.key)
    result = ok(
        f"Anuncio principal «{view.name}»: {view.title} · {_price(view.price)} · "
        f"{stats['publicaciones']} publicación(es).",
        plantilla=view.to_dict(),
        estadisticas=stats,
        descripcion=view.description,
    )
    result.focus = {"master_key": view.key}
    return result


def _preview_master_ad(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    refs, missing = _target_accounts(context, args.get("cuentas"))
    if missing:
        return fail(f"No se encuentran estas cuentas: {', '.join(missing)}.")
    if not refs:
        return fail("No hay ninguna cuenta conectada en la que publicar.")
    try:
        overrides = _normalize_changes(args.get("cambios"))
        previews = context.app.master_ads.build_previews(
            args.get("plantilla"), refs, args.get("copias"), overrides
        )
    except ValueError as exc:
        return fail(str(exc))
    publicables = sum(1 for p in previews if p.can_publish)
    first = previews[0] if previews else None
    result = ok(
        f"Vista previa del anuncio principal: {len(previews)} publicación(es), "
        f"{publicables} lista(s) para publicar. No se ha publicado nada.",
        vistas_previas=[p.to_dict() for p in previews[:10]],
        titulo=first.title if first else "",
        descripcion=first.description if first else "",
    )
    result.focus = {"master_key": context.app.master_ads.get(args.get("plantilla")).key}
    return result


def _publish_master_ad(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    refs, missing = _target_accounts(context, args.get("cuentas"))
    if missing:
        return fail(f"No se encuentran estas cuentas: {', '.join(missing)}.")
    if not refs:
        return fail(
            "No hay ninguna cuenta conectada en la que publicar. Conecta una cuenta en "
            "«Cuentas de Wallapop»."
        )
    copies = args.get("copias")
    if copies is not None:
        try:
            copies = int(copies)
        except (TypeError, ValueError):
            return fail(f"«{copies}» no es un número de publicaciones válido.")
        if copies < 1 or copies > 100:
            return fail("El número de publicaciones debe estar entre 1 y 100.")

    overrides = _normalize_changes(args.get("cambios"))
    invalid = set(overrides) - OVERRIDABLE_FIELDS
    if invalid:
        return fail(
            f"En una publicación concreta solo se puede cambiar: "
            f"{', '.join(sorted(OVERRIDABLE_FIELDS))}. Para cambiar el resto, "
            f"actualiza la plantilla."
        )

    master = context.app.master_ads.get(args.get("plantilla"))
    if master is None:
        return fail("No hay ningún anuncio principal configurado.")
    try:
        previews = context.app.master_ads.build_previews(master.key, refs, copies, overrides)
    except ValueError as exc:
        return fail(str(exc))

    if not context.confirmed:
        distribution = Counter(p.account_ref for p in previews)
        aliases = {a.internal_ref: a.alias for a in context.app.accounts.list_accounts()}
        first = previews[0]
        lines = [
            f"Título: {first.title}",
            f"Precio: {_price(first.price)}",
            f"Características: {master.features_line}",
            f"Fotografías: {len(first.image_paths)}",
        ]
        lines += [
            f"{aliases.get(ref, ref)}: {count} publicación(es)"
            for ref, count in distribution.items()
        ]
        if overrides:
            lines.append(
                "Cambios solo para estas publicaciones (la plantilla NO cambia): "
                + ", ".join(f"{k}={v}" for k, v in overrides.items())
            )
        blocked = [p for p in previews if not p.can_publish]
        if blocked:
            reasons = sorted(
                {i.message for p in blocked for i in (p.quality.errors if p.quality else [])}
            )
            lines.append(
                f"NO se podrán publicar {len(blocked)} de {len(previews)}: " + "; ".join(reasons)
            )
        warnings = sorted({i.message for i in (first.quality.warnings if first.quality else [])})
        for warning in warnings:
            lines.append(f"Aviso (no bloquea): {warning}")
        queue = context.app.publish_queue
        images = _will_generate_images(context)
        lines.append(
            f"Se publicarán de uno en uno, con al menos {queue.interval} segundos entre "
            f"publicaciones (también entre cuentas distintas)."
        )
        lines.append(images[1])
        return confirm_first(
            "publish_master_ad",
            {**args, "cuentas": refs, "copias": copies},
            f"Voy a publicar {len(previews)} anuncio(s) de «{master.name}»",
            lines,
            affected=len(previews),
        )

    queue = context.app.publish_queue
    try:
        job_id = queue.enqueue_master(
            master.key,
            refs,
            copies,
            overrides,
            generate_images=_will_generate_images(context)[0],
            actor=context.actor,
        )
    except ValueError as exc:
        return fail(str(exc))
    progress = queue.progress(job_id)
    return ToolResult(
        focus={"publish_job": job_id, "master_key": master.key},
        ok=True,
        summary=(
            f"Cola de publicación creada: {progress.total} anuncio(s) de «{master.name}», "
            f"con un mínimo de {progress.interval_seconds} s entre cada uno. Puedes ver el "
            f"progreso en «Publicación automática» o preguntando «¿cómo va la cola?». "
            f"La plantilla no se ha modificado."
        ),
        data={"cola": progress.to_dict()},
    )


def _will_generate_images(context: ToolContext) -> tuple[bool, str]:
    """(generar, explicación) según la configuración y la clave de FLUX."""
    from lot_bot.config.api_keys import FLUX

    app = context.app
    if not app.publish_queue.settings()["generate_images"]:
        return False, "Fotografías: las del anuncio principal (generación automática desactivada)."
    if app.demo_mode:
        return True, (
            "Se generará una imagen de DEMOSTRACIÓN distinta para cada anuncio "
            "(sin FLUX ni créditos)."
        )
    if not app.api_keys.has(FLUX):
        return False, (
            "Sin clave de FLUX.2 Pro: se usarán las fotos del anuncio principal. "
            "Añade la clave en Configuración → IA / Imágenes para generar una por anuncio."
        )
    return True, (
        "Se generará con FLUX.2 Pro una imagen fotorrealista distinta para cada anuncio "
        "justo antes de publicarlo (consume créditos de Black Forest Labs)."
    )


def _queue_status(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    progress = context.app.publish_queue.progress(args.get("cola"))
    if progress is None:
        return ok("No hay ninguna cola de publicación.")
    lines = [
        f"{progress.name} — {progress.status}",
        f"{progress.bar()} {progress.published}/{progress.total}",
        f"✓ {progress.published} publicados · ⏳ {progress.in_progress} en curso · "
        f"○ {progress.pending} pendientes · ✗ {progress.failed} fallidos",
    ]
    if progress.current_account:
        lines.append(f"Cuenta: {progress.current_account}")
    if progress.last_publish_at:
        lines.append(f"Última publicación: {progress.last_publish_at:%H:%M:%S}")
    if progress.next_allowed_at:
        lines.append(f"Próxima publicación permitida: {progress.next_allowed_at:%H:%M:%S}")
    if progress.pause_reason and progress.status == "paused":
        lines.append(f"En pausa: {progress.pause_reason}")
    for task in progress.tasks:
        if task["estado"] == "failed":
            lines.append(f"Error en el anuncio {task['posicion']} ({task['cuenta']}): {task['error']}")
    return ToolResult(ok=True, summary="\n".join(lines), data={"cola": progress.to_dict()})


def _queue_control(action: str):
    def handler(context: ToolContext, args: dict[str, Any]) -> ToolResult:
        queue = context.app.publish_queue
        job_id = args.get("cola") or queue.latest_job_id()
        if job_id is None:
            return fail("No hay ninguna cola de publicación.")
        progress = queue.progress(job_id)
        if action == "cancel" and not context.confirmed:
            return confirm_first(
                "cancel_publish_queue",
                {"cola": job_id},
                f"Voy a cancelar la cola «{progress.name}»",
                [
                    f"Quedan {progress.pending + progress.in_progress} anuncio(s) sin publicar, "
                    "que no se publicarán.",
                    "Lo ya publicado no se toca.",
                ],
            )
        try:
            if action == "pause":
                queue.pause(job_id)
                return ok(f"Cola «{progress.name}» en pausa.")
            if action == "resume":
                queue.resume(job_id)
                return ok(f"Cola «{progress.name}» reanudada. Se respeta el intervalo mínimo.")
            count = queue.cancel(job_id)
            return ok(f"Cola «{progress.name}» cancelada: {count} anuncio(s) sin publicar.")
        except ValueError as exc:
            return fail(str(exc))

    return handler


def _retry_failed(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    queue = context.app.publish_queue
    progress = queue.progress(args.get("cola"))
    if progress is None:
        return fail("No hay ninguna cola de publicación.")
    failed = [t for t in progress.tasks if t["estado"] == "failed"]
    if not failed:
        return ok("No hay anuncios fallidos que reintentar.")
    for task in failed:
        queue.retry_task(task["id"])
    return ok(f"{len(failed)} anuncio(s) vuelven a la cola, respetando el intervalo mínimo.")


def _update_master_ad(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    changes = _normalize_changes(args.get("cambios"))
    if not changes:
        return fail("Indica qué quieres cambiar de la plantilla.")
    invalid = set(changes) - EDITABLE_FIELDS
    if invalid:
        return fail(f"Estos campos no se pueden editar: {', '.join(sorted(invalid))}.")
    master = context.app.master_ads.get(args.get("plantilla"))
    if master is None:
        return fail("No hay ningún anuncio principal configurado.")

    if not context.confirmed:
        current = {
            "title": master.title,
            "price": _price(master.price),
            "description": master.description_pattern,
            "features": master.features_line,
            "category": master.category or "(sin categoría)",
            "subcategory": master.subcategory or "—",
            "condition": master.condition,
            "tags": ", ".join(master.tags) or "—",
            "keywords": ", ".join(master.keywords) or "—",
            "contact_whatsapp": master.contact_whatsapp or "—",
            "variants": ", ".join(f"{v['medida']}={v['precio']}" for v in master.variants),
            "name": master.name,
            "delivery_note": master.delivery_note or "—",
            "aliases": ", ".join(master.aliases),
            "variables": str(master.variables),
        }
        lines = [
            f"{name}: {str(current.get(name, '—'))[:120]} → {str(value)[:120]}"
            for name, value in changes.items()
        ]
        lines.append(
            "Esto cambia la PLANTILLA MAESTRA. Los anuncios ya publicados no se modifican."
        )
        return confirm_first(
            "update_master_ad",
            args,
            f"Voy a actualizar la plantilla «{master.name}»",
            lines,
            affected=1,
        )
    try:
        view = context.app.master_ads.update(
            master.key, changes, confirmed=True, actor=context.actor
        )
    except ValueError as exc:
        return fail(str(exc))
    return ok(f"Plantilla «{view.name}» actualizada.", plantilla=view.to_dict())


def _list_master_publications(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    master = context.app.master_ads.get(args.get("plantilla"))
    if master is None:
        return fail("No hay ningún anuncio principal configurado.")
    publications = context.app.master_ads.publications(master.key)
    result = ok(
        f"{len(publications)} publicación(es) de «{master.name}».",
        anuncios=[p.to_dict() for p in publications[:80]],
        estadisticas=context.app.master_ads.stats(master.key),
    )
    if len(publications) == 1:
        result.focus = {"listing_ids": [publications[0].id]}
    return result


MASTER_AD_TOOLS: list[Tool] = [
    Tool(
        name="get_master_ad",
        description=(
            "Muestra el anuncio principal del negocio (la plantilla de canapés): título, "
            "características, precio, descripción, ofertas por medida y estadísticas. "
            "Úsala cuando el usuario hable de «el canapé», «los canapés» o «el anuncio "
            "de canapé» sin dar más detalles."
        ),
        parameters={"properties": {"plantilla": {"type": "string"}}, "required": []},
        handler=_get_master_ad,
        category=ToolCategory.LISTINGS,
    ),
    Tool(
        name="preview_master_ad",
        description=(
            "Prepara la vista previa de las publicaciones del anuncio principal, con su "
            "control de calidad. No publica nada."
        ),
        parameters={
            "properties": {
                "cuentas": {"type": "array", "items": {"type": "string"}},
                "copias": {"type": "integer", "description": "Número total de publicaciones."},
                "cambios": {
                    "type": "object",
                    "description": "Cambios solo para estas publicaciones (title, price, description, category, condition).",
                },
            },
            "required": [],
        },
        handler=_preview_master_ad,
        category=ToolCategory.LISTINGS,
    ),
    Tool(
        name="publish_master_ad",
        description=(
            "Publica el anuncio principal (canapés). Sin número de copias, publica una en "
            "cada cuenta conectada; con «copias», las reparte por turnos entre las cuentas. "
            "Se publica mediante la cola, de uno en uno y con un intervalo mínimo de 60 s; "
            "puede generar una imagen distinta por anuncio. "
            "La plantilla maestra NO se modifica. Requiere confirmación."
        ),
        parameters={
            "properties": {
                "cuentas": {"type": "array", "items": {"type": "string"}},
                "copias": {"type": "integer"},
                "cambios": {
                    "type": "object",
                    "description": "Cambios solo para estas publicaciones, no para la plantilla.",
                },
            },
            "required": [],
        },
        handler=_publish_master_ad,
        category=ToolCategory.LISTINGS,
        requires_confirmation=True,
        capability="create_item",
    ),
    Tool(
        name="get_publish_queue",
        description=(
            "Muestra el progreso de la cola de publicación automática: publicados, "
            "pendientes, errores, cuenta actual y próxima publicación permitida."
        ),
        parameters={"properties": {"cola": {"type": "integer"}}, "required": []},
        handler=_queue_status,
        category=ToolCategory.LISTINGS,
    ),
    Tool(
        name="pause_publish_queue",
        description="Pausa la cola de publicación automática.",
        parameters={"properties": {"cola": {"type": "integer"}}, "required": []},
        handler=_queue_control("pause"),
        category=ToolCategory.LISTINGS,
    ),
    Tool(
        name="resume_publish_queue",
        description="Reanuda la cola de publicación automática.",
        parameters={"properties": {"cola": {"type": "integer"}}, "required": []},
        handler=_queue_control("resume"),
        category=ToolCategory.LISTINGS,
    ),
    Tool(
        name="cancel_publish_queue",
        description="Cancela lo que queda de la cola de publicación. Requiere confirmación.",
        parameters={"properties": {"cola": {"type": "integer"}}, "required": []},
        handler=_queue_control("cancel"),
        category=ToolCategory.LISTINGS,
        requires_confirmation=True,
    ),
    Tool(
        name="retry_failed_publications",
        description="Vuelve a poner en la cola los anuncios cuya publicación falló.",
        parameters={"properties": {"cola": {"type": "integer"}}, "required": []},
        handler=_retry_failed,
        category=ToolCategory.LISTINGS,
    ),
    Tool(
        name="update_master_ad",
        description=(
            "Modifica la PLANTILLA MAESTRA del anuncio principal. Úsala SOLO cuando el "
            "usuario pida expresamente cambiar la plantilla («actualiza la plantilla»). "
            "Para cambiar un anuncio concreto usa update_price / update_title. "
            "Requiere confirmación."
        ),
        parameters={
            "properties": {
                "cambios": {
                    "type": "object",
                    "description": (
                        "Campos: title, features (lista), price, description, variants "
                        "(lista de {medida, precio}), contact_whatsapp, category, "
                        "subcategory, condition, tags, keywords."
                    ),
                }
            },
            "required": ["cambios"],
        },
        handler=_update_master_ad,
        category=ToolCategory.LISTINGS,
        requires_confirmation=True,
    ),
    Tool(
        name="list_master_publications",
        description="Lista los anuncios publicados a partir del anuncio principal.",
        parameters={"properties": {}, "required": []},
        handler=_list_master_publications,
        category=ToolCategory.LISTINGS,
    ),
]
