"""Pantalla «Imágenes / IA»: elegir una imagen y decidir qué hacer con ella.

Acciones: Generar, Mejorar, Cambiar estilo, Cambiar habitación y Usar como
referencia. Todas crean una imagen NUEVA (la original no se toca) y pasan por
la detección de imágenes repetidas. Lo que consume créditos de FLUX pide
confirmación.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from lot_bot.images.generation import GenerationError, spec_from_master
from lot_bot.images.generation.prompts import (
    LIGHT_LABELS,
    OPERATIONS,
    ROOM_LABELS,
    STYLE_LABELS,
    spec_from_text,
)
from lot_bot.ui import theme
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import Card, SectionTitle, ask_confirmation, info_box, show_error

OPERATION_NAMES = {**OPERATIONS, "propia": "Foto propia"}


def use_image_in_ads(app, path: str) -> bool:
    """Añade una imagen a las fotos del anuncio principal. True si se añadió."""
    master = app.master_ads.get(None)
    before = len(master.images)
    imported = app.images.import_image(path, "anuncio-principal", position=before)
    app.master_ads.add_images(master.key, [imported.to_dict()])
    added = len(app.master_ads.get(master.key).images) > before
    if added:
        app.audit.record_success(
            "Fotografías del anuncio principal", target=master.name, detail="1 añadida desde Imágenes"
        )
    return added


class ImageStudioView(BaseView):
    title = "Imágenes / IA"
    subtitle = "Elige una imagen y qué hacer con ella. La original nunca se modifica"

    def build(self) -> None:
        self.add_header_button("Subir foto propia…", self._upload)
        self.add_header_button("Actualizar", self.refresh)

        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.body.addWidget(self.notice)

        columns = QHBoxLayout()
        list_card = Card()
        list_card.add(SectionTitle("Imágenes"))
        self.images = QListWidget()
        self.images.currentItemChanged.connect(self._show_selected)
        list_card.add(self.images)
        columns.addWidget(list_card, 2)

        right = QVBoxLayout()
        preview_card = Card()
        self.preview = QLabel("Selecciona una imagen")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 300)
        preview_card.add(self.preview)
        self.info = QLabel()
        self.info.setWordWrap(True)
        preview_card.add(self.info)
        right.addWidget(preview_card, 3)

        actions = Card()
        actions.add(SectionTitle("¿Qué quieres hacer?"))
        form = QFormLayout()
        self.product = QLineEdit()
        self.product.setPlaceholderText(
            "Opcional: qué producto es (p. ej. «canapé abatible gris de madera»). "
            "Vacío = datos del anuncio principal"
        )
        self.room = QComboBox()
        self.light = QComboBox()
        self.style = QComboBox()
        for combo, labels in (
            (self.room, ROOM_LABELS),
            (self.light, LIGHT_LABELS),
            (self.style, STYLE_LABELS),
        ):
            combo.addItem("(sin indicar)", None)
            for key, label in labels.items():
                combo.addItem(label, key)
        for widget in (self.product, self.room, self.light, self.style):
            widget.setMinimumHeight(32)
        form.addRow("Producto", self.product)
        form.addRow("Habitación", self.room)
        form.addRow("Luz", self.light)
        form.addRow("Estilo", self.style)
        actions.body.addLayout(form)

        buttons = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for key in ("generar", "mejorar", "estilo", "habitacion", "referencia"):
            button = QPushButton(OPERATIONS[key])
            button.setMinimumHeight(34)
            if key == "generar":
                button.setObjectName("Primary")
            button.clicked.connect(lambda _=False, k=key: self._run(k))
            buttons.addWidget(button)
            self.buttons[key] = button
        actions.body.addLayout(buttons)
        use_row = QHBoxLayout()
        self.use_button = QPushButton("Usar en mis anuncios")
        self.use_button.setMinimumHeight(34)
        self.use_button.setToolTip(
            "Añade la imagen elegida a las fotos del anuncio principal: se publicará con ella "
            "(no hace falta clave de FLUX)."
        )
        self.use_button.clicked.connect(self._use_in_ads)
        use_row.addWidget(self.use_button)
        use_row.addStretch(1)
        actions.body.addLayout(use_row)
        hint = QLabel(
            "Generar: foto nueva desde cero · Mejorar: más resolución y nitidez (local, sin IA) · "
            "Cambiar estilo / habitación: misma imagen, otro ambiente · Usar como referencia: "
            "foto nueva basada en el producto de la imagen elegida."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        actions.add(hint)
        right.addWidget(actions, 2)
        columns.addLayout(right, 3)
        self.body.addLayout(columns, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        generator = self.app.image_generation.generator
        if generator.is_demo:
            self.notice.setText(
                "MODO DEMO: se crean imágenes de prueba locales, sin FLUX ni créditos."
            )
        else:
            self.notice.setText(
                f"Motor: {generator.name}. Generar, cambiar estilo, cambiar habitación y usar como "
                f"referencia consumen créditos; «Mejorar» es local y gratuito."
            )
        current = self._selected_id()
        self.images.clear()
        for info in self.app.image_generation.history(200):
            if not info["existe"]:
                continue
            scene = info["escena"] or {}
            label = f"#{info['id']} · {OPERATION_NAMES.get(info['operacion'], info['operacion'])}"
            if scene.get("habitacion"):
                label += f" · {ROOM_LABELS.get(scene['habitacion'], '')}"
            label += f" · {info['fecha']:%d/%m %H:%M}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, info)
            self.images.addItem(item)
            if info["id"] == current:
                self.images.setCurrentItem(item)
        self._show_selected()

    def _selected(self) -> dict | None:
        item = self.images.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_id(self) -> int | None:
        info = self._selected() if hasattr(self, "images") else None
        return info["id"] if info else None

    def _show_selected(self, *_):
        info = self._selected()
        needs_image = ("mejorar", "estilo", "habitacion", "referencia")
        for key in needs_image:
            self.buttons[key].setEnabled(info is not None)
        if hasattr(self, "use_button"):
            self.use_button.setEnabled(info is not None)
        if info is None:
            self.preview.setText("Selecciona una imagen o pulsa «Generar»")
            self.preview.setPixmap(QPixmap())
            self.info.setText("")
            return
        pixmap = QPixmap(info["ruta"])
        if not pixmap.isNull():
            self.preview.setPixmap(
                pixmap.scaled(
                    self.preview.width(),
                    self.preview.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.info.setText(
            f"Imagen #{info['id']} · {OPERATION_NAMES.get(info['operacion'], info['operacion'])} · "
            f"{info['proveedor']} · {Path(info['ruta']).name}"
        )

    # ------------------------------------------------------------------
    def _scene(self) -> dict:
        scene = {}
        for key, combo in (("habitacion", self.room), ("luz", self.light), ("estilo", self.style)):
            if combo.currentData():
                scene[key] = combo.currentData()
        return scene

    def _spec(self):
        text = self.product.text().strip()
        if text:
            return spec_from_text(text)
        master = self.app.master_ads.get(None)
        return spec_from_master(master) if master else None

    def _run(self, operation: str) -> None:
        info = self._selected()
        scene = self._scene()
        if operation == "estilo" and "estilo" not in scene:
            show_error(self, "Elige primero el estilo.")
            return
        if operation == "habitacion" and "habitacion" not in scene:
            show_error(self, "Elige primero la habitación.")
            return
        try:
            spec = self._spec() if operation in ("generar",) or self.product.text().strip() else None
        except ValueError as exc:
            show_error(self, str(exc))
            return
        generator = self.app.image_generation.generator
        if operation != "mejorar" and not generator.is_demo:
            if not ask_confirmation(
                self,
                OPERATIONS[operation],
                f"Se usará {generator.name} y se consumirán créditos de Black Forest Labs.\n\n"
                f"El producto se mantiene tal cual; sin texto, precios, teléfonos, logos ni marcas.",
            ):
                return
        service = self.app.image_generation

        def work():
            if operation == "generar":
                return service.generate_unique(
                    spec,
                    variation=self.images.count(),
                    subject=f"Imagen suelta: {spec.product_type}",
                    scene={"habitacion": "dormitorio_blanco", "luz": "dia_luminoso",
                           "angulo": "tres_cuartos_pie", "estilo": "natural", **scene}
                    if scene
                    else None,
                    preferred_rooms=self.app.optimizer.preferred_rooms(),
                )
            if operation == "mejorar":
                return service.enhance(Path(info["ruta"]))
            return service.edit(operation, Path(info["ruta"]), scene=scene, spec=spec)

        def success(result) -> None:
            self.app.audit.record_success(
                f"Imagen: {OPERATIONS[operation]}",
                detail=f"{result.provider}; imagen {result.image_id}",
            )
            self.refresh()
            for row in range(self.images.count()):
                data = self.images.item(row).data(Qt.ItemDataRole.UserRole)
                if data and data["id"] == result.image_id:
                    self.images.setCurrentRow(row)
                    break

        def failed(message: str, _detail: str) -> None:
            show_error(self, "No se ha podido crear la imagen.", message)

        for button in self.buttons.values():
            button.setEnabled(False)
        self.runner.run(
            work,
            on_success=success,
            on_error=failed,
            on_done=lambda: self._show_selected() or self.buttons["generar"].setEnabled(True),
        )

    def _use_in_ads(self) -> None:
        info = self._selected()
        if info is None:
            return
        try:
            added = use_image_in_ads(self.app, info["ruta"])
        except Exception as exc:
            show_error(self, "No se ha podido añadir la foto.", str(exc))
            return
        if added:
            info_box(
                self,
                "Foto añadida",
                "La imagen se usará en tus anuncios (Anuncio principal → Fotografías).",
            )
        else:
            info_box(self, "Ya estaba", "Esa imagen ya está entre las fotos de tus anuncios.")

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Subir foto propia", "", "Imágenes (*.jpg *.jpeg *.png *.webp)"
        )
        if not path:
            return
        try:
            result = self.app.image_generation.add_own_image(Path(path))
        except GenerationError as exc:
            show_error(self, exc.user_message)
            return
        except Exception as exc:
            show_error(self, "No es una imagen válida.", type(exc).__name__)
            return
        self.app.audit.record_success("Foto propia añadida", detail=f"imagen {result.image_id}")
        info_box(
            self,
            "Foto guardada",
            f"Imagen #{result.image_id} guardada. Pulsa «Usar en mis anuncios» para publicar con "
            f"ella, o úsala como referencia para crear otras.",
        )
        self.refresh()
