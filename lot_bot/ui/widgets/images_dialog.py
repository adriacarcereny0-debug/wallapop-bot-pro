"""Gestor de fotografías: ver, añadir, ordenar, marcar principal y eliminar.

Sirve igual para un producto del catálogo que para el anuncio principal: la
pantalla que lo abre le pasa un «adaptador» con las operaciones concretas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from lot_bot.ui import theme
from lot_bot.ui.widgets.common import ask_confirmation, info_box


@dataclass
class ImageAdapter:
    """Operaciones sobre las fotografías de un elemento concreto."""

    title: str
    list_images: Callable[[], list[dict[str, Any]]]
    add_files: Callable[[list[str]], tuple[int, list[str]]]
    remove: Callable[[int], None]
    move: Callable[[int, int], None]
    set_primary: Callable[[int], None]
    #: Aviso opcional (p. ej. imágenes de demostración).
    note: str = ""


class ImagesDialog(QDialog):
    def __init__(self, adapter: ImageAdapter, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.setWindowTitle(f"Fotografías — {adapter.title}")
        self.resize(820, 560)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel(
            "La primera fotografía es la principal. Formatos admitidos: JPG, JPEG, PNG y "
            "WEBP. Las fotos repetidas se descartan solas."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(hint)
        if adapter.note:
            note = QLabel(adapter.note)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {theme.WARNING};")
            layout.addWidget(note)

        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.gallery.setIconSize(QSize(170, 130))
        self.gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.gallery.setMovement(QListWidget.Movement.Static)
        self.gallery.setSpacing(10)
        self.gallery.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.gallery, 1)

        row = QHBoxLayout()
        self.add_button = QPushButton("Añadir fotografías…")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self._add)
        row.addWidget(self.add_button)
        self.left_button = QPushButton("◀ Mover antes")
        self.left_button.clicked.connect(lambda: self._move(-1))
        row.addWidget(self.left_button)
        self.right_button = QPushButton("Mover después ▶")
        self.right_button.clicked.connect(lambda: self._move(1))
        row.addWidget(self.right_button)
        self.primary_button = QPushButton("Marcar como principal")
        self.primary_button.clicked.connect(self._primary)
        row.addWidget(self.primary_button)
        row.addStretch(1)
        self.remove_button = QPushButton("Quitar")
        self.remove_button.setObjectName("Danger")
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.remove_button)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self, select: int | None = None) -> None:
        self.gallery.clear()
        for index, image in enumerate(self.adapter.list_images()):
            path = Path(str(image.get("path", "")))
            pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
            label = f"{index + 1}. {image.get('original_name') or path.name}"
            if image.get("is_primary"):
                label = "★ " + label
            if image.get("source") == "demo":
                label += " (DEMO)"
            if pixmap.isNull():
                label += "\n(no se encuentra el fichero)"
            item = QListWidgetItem(QIcon(pixmap), label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.gallery.addItem(item)
        if select is not None and 0 <= select < self.gallery.count():
            self.gallery.setCurrentRow(select)
        self._update_buttons()

    def _selected(self) -> int | None:
        item = self.gallery.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self) -> None:
        index = self._selected()
        has = index is not None
        count = self.gallery.count()
        self.left_button.setEnabled(has and index > 0)
        self.right_button.setEnabled(has and index < count - 1)
        self.primary_button.setEnabled(has)
        self.remove_button.setEnabled(has)

    # ------------------------------------------------------------------
    def _add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecciona las fotografías", "", "Imágenes (*.jpg *.jpeg *.png *.webp)"
        )
        if not paths:
            return
        added, problems = self.adapter.add_files(paths)
        message = f"{added} fotografía(s) añadidas."
        if problems:
            message += "\n\nIncidencias:\n" + "\n".join(f"• {p}" for p in problems)
        info_box(self, "Fotografías", message)
        self.refresh()

    def _move(self, delta: int) -> None:
        index = self._selected()
        if index is None:
            return
        self.adapter.move(index, delta)
        self.refresh(select=index + delta)

    def _primary(self) -> None:
        index = self._selected()
        if index is None:
            return
        self.adapter.set_primary(index)
        self.refresh(select=index)

    def _remove(self) -> None:
        index = self._selected()
        if index is None:
            return
        if not ask_confirmation(
            self,
            "Quitar fotografía",
            "Se quitará la fotografía de este elemento. El fichero original de tu "
            "ordenador no se borra.",
        ):
            return
        self.adapter.remove(index)
        self.refresh()


# ---------------------------------------------------------------------------
# Adaptadores
# ---------------------------------------------------------------------------
def product_adapter(app, product_id: int) -> ImageAdapter:
    """Fotografías de un producto del catálogo."""

    def images() -> list[dict[str, Any]]:
        view = app.catalog.get_product(product_id)
        return sorted(view.images, key=lambda i: i["position"]) if view else []

    def add(paths: list[str]) -> tuple[int, list[str]]:
        view = app.catalog.get_product(product_id)
        known = {i.get("content_hash") for i in view.images}
        imported, problems = app.images.import_many(paths, view.sku)
        added = 0
        for info in imported:
            if info.content_hash in known:
                problems.append(f"«{info.original_name}» ya estaba en este producto.")
                continue
            data = info.to_dict()
            data["position"] = len(view.images) + added
            data["is_primary"] = not view.images and added == 0
            app.catalog.add_image(product_id, data)
            added += 1
        app.audit.record_success(
            "Importación de fotografías", target=view.sku, detail=f"{added} añadidas"
        )
        return added, problems

    def remove(index: int) -> None:
        current = images()
        if 0 <= index < len(current):
            app.catalog.remove_image(current[index]["id"])
            rest = [i["id"] for i in images()]
            app.catalog.reorder_images(product_id, rest)
            if rest and not any(i["is_primary"] for i in images()):
                app.catalog.set_primary_image(product_id, rest[0])

    def move(index: int, delta: int) -> None:
        ids = [i["id"] for i in images()]
        target = index + delta
        if 0 <= index < len(ids) and 0 <= target < len(ids):
            ids[index], ids[target] = ids[target], ids[index]
            app.catalog.reorder_images(product_id, ids)

    def primary(index: int) -> None:
        current = images()
        if 0 <= index < len(current):
            app.catalog.set_primary_image(product_id, current[index]["id"])

    view = app.catalog.get_product(product_id)
    return ImageAdapter(
        title=f"{view.sku} · {view.name}",
        list_images=images,
        add_files=add,
        remove=remove,
        move=move,
        set_primary=primary,
    )


def master_adapter(app, key: str) -> ImageAdapter:
    """Fotografías del anuncio principal."""
    service = app.master_ads

    def images() -> list[dict[str, Any]]:
        return service.get(key).images

    def add(paths: list[str]) -> tuple[int, list[str]]:
        before = len(images())
        imported, problems = app.images.import_many(paths, "anuncio-principal")
        service.add_images(key, [i.to_dict() for i in imported])
        added = len(images()) - before
        if added < len(imported):
            problems.append("Alguna fotografía ya estaba en el anuncio y se ha omitido.")
        app.audit.record_success(
            "Fotografías del anuncio principal", target=service.get(key).name,
            detail=f"{added} añadidas",
        )
        return added, problems

    note = ""
    if app.demo_mode and not images():
        note = (
            "Esta plantilla aún no tiene fotografías propias. En MODO DEMO se usan tres "
            "imágenes de demostración rotuladas como tales; en modo real hará falta "
            "añadir fotos reales para poder publicar."
        )
    return ImageAdapter(
        title=service.get(key).name,
        list_images=images,
        add_files=add,
        remove=lambda index: service.remove_image(key, index),
        move=lambda index, delta: service.move_image(key, index, delta),
        set_primary=lambda index: service.set_primary_image(key, index),
        note=note,
    )
