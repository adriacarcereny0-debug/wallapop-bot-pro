"""Pantalla de configuracion."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lot_bot.config.secrets import mask
from lot_bot.config.settings import reload_settings
from lot_bot.database.models import Template
from lot_bot.templates_engine.defaults import TEMPLATE_VARIABLES
from lot_bot.ui import theme
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import Card, SectionTitle, info_box, show_error


class SettingsView(BaseView):
    title = "Configuración"
    subtitle = "Negocio, IA, conexión con Wallapop y plantillas"

    def build(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._business_tab(), "Negocio")
        self.tabs.addTab(self._templates_tab(), "Plantillas")
        self.tabs.addTab(self._ai_tab(), "IA")
        self.tabs.addTab(self._wallapop_tab(), "Wallapop")
        self.tabs.addTab(self._about_tab(), "Acerca de")
        self.body.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------
    def _business_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        card = Card()
        card.add(SectionTitle("Datos del negocio"))
        note = QLabel(
            "Estos datos se usan en las plantillas y en las respuestas a compradores. "
            "Lo que dejes vacío, el asistente NO se lo inventará: responderá «No dispongo "
            "de esa información»."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        card.add(note)

        form = QFormLayout()
        form.setSpacing(10)
        self.business_fields = {
            "name": QLineEdit(),
            "whatsapp": QLineEdit(),
            "delivery": QLineEdit(),
            "assembly": QLineEdit(),
            "payment": QLineEdit(),
            "location": QLineEdit(),
            "precio_90": QLineEdit(),
            "precio_135": QLineEdit(),
            "precio_150": QLineEdit(),
        }
        self.business_fields["whatsapp"].setPlaceholderText("Número de WhatsApp del negocio")
        self.business_fields["delivery"].setPlaceholderText(
            "Ej.: El transporte y el montaje son gratuitos."
        )
        self.business_fields["assembly"].setPlaceholderText("Ej.: Incluye montaje en domicilio.")
        self.business_fields["payment"].setPlaceholderText("Ej.: Aceptamos efectivo y Bizum.")
        self.business_fields["location"].setPlaceholderText("Ej.: Recogida en nuestra tienda de …")
        for key in ("precio_90", "precio_135", "precio_150"):
            self.business_fields[key].setPlaceholderText("Importe en € (solo el número)")

        labels = {
            "name": "Nombre del negocio",
            "whatsapp": "WhatsApp",
            "delivery": "Condiciones de envío",
            "assembly": "Condiciones de montaje",
            "payment": "Formas de pago",
            "location": "Recogida / tienda",
            "precio_90": "Precio oferta 90x190",
            "precio_135": "Precio oferta 135x190",
            "precio_150": "Precio oferta 150x190",
        }
        for key, field in self.business_fields.items():
            form.addRow(labels[key], field)
        card.body.addLayout(form)

        save = QPushButton("Guardar datos del negocio")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_business)
        card.add(save)
        layout.addWidget(card)
        layout.addStretch(1)
        return widget

    def _templates_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        left = Card()
        left.add(SectionTitle("Plantillas"))
        self.template_list = QListWidget()
        self.template_list.currentRowChanged.connect(self._load_template)
        left.add(self.template_list)
        layout.addWidget(left, 1)

        right = Card()
        right.add(SectionTitle("Editar plantilla"))
        form = QFormLayout()
        self.template_title = QLineEdit()
        self.template_description = QPlainTextEdit()
        self.template_description.setFixedHeight(160)
        form.addRow("Patrón del título", self.template_title)
        form.addRow("Patrón de la descripción", self.template_description)
        right.body.addLayout(form)

        variables = QLabel(
            "Variables disponibles:\n"
            + "\n".join(f"  {{{k}}} — {v}" for k, v in list(TEMPLATE_VARIABLES.items())[:14])
        )
        variables.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        right.add(variables)

        save = QPushButton("Guardar plantilla")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_template)
        right.add(save)
        layout.addWidget(right, 2)
        return widget

    def _ai_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        card = Card()
        card.add(SectionTitle("Asistente IA"))

        form = QFormLayout()
        self.ai_provider = QComboBox()
        self.ai_provider.addItem("Órdenes directas (sin IA externa)", "rules")
        self.ai_provider.addItem("Claude (lenguaje natural)", "anthropic")
        form.addRow("Modo del asistente", self.ai_provider)

        self.ai_key_label = QLabel()
        form.addRow("Clave de API", self.ai_key_label)
        self.ai_model_label = QLabel()
        form.addRow("Modelo", self.ai_model_label)
        card.body.addLayout(form)

        note = QLabel(
            "La clave de API se configura en el fichero .env (variable ANTHROPIC_API_KEY) "
            "y nunca se muestra completa ni se guarda en los registros.\n\n"
            "Con «Órdenes directas» el bot funciona sin conexión a ningún servicio de IA: "
            "entiende instrucciones concretas como «Cambia el precio de los canapés de "
            "135x190 a 269 €»."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        card.add(note)

        apply_button = QPushButton("Aplicar modo del asistente")
        apply_button.setObjectName("Primary")
        apply_button.clicked.connect(self._apply_ai)
        card.add(apply_button)
        layout.addWidget(card)
        layout.addStretch(1)
        return widget

    def _wallapop_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        card = Card()
        card.add(SectionTitle("Conexión con Wallapop"))
        self.wallapop_status = QLabel()
        self.wallapop_status.setWordWrap(True)
        card.add(self.wallapop_status)

        form = QFormLayout()
        self.client_id_label = QLabel()
        self.client_secret_label = QLabel()
        self.redirect_label = QLabel()
        self.endpoint_label = QLabel()
        form.addRow("Client ID", self.client_id_label)
        form.addRow("Client Secret", self.client_secret_label)
        form.addRow("Redirect URI", self.redirect_label)
        form.addRow("Fichero de endpoints", self.endpoint_label)
        card.body.addLayout(form)

        buttons = QHBoxLayout()
        select = QPushButton("Seleccionar fichero de endpoints…")
        select.clicked.connect(self._select_endpoint_map)
        buttons.addWidget(select)
        reload_button = QPushButton("Recargar configuración")
        reload_button.clicked.connect(self._reload_settings)
        buttons.addWidget(reload_button)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        layout.addWidget(card)

        capabilities_card = Card()
        capabilities_card.add(SectionTitle("Operaciones autorizadas"))
        self.capabilities_label = QPlainTextEdit()
        self.capabilities_label.setReadOnly(True)
        capabilities_card.add(self.capabilities_label)
        layout.addWidget(capabilities_card, 1)
        return widget

    def _about_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        card = Card()
        card.add(SectionTitle("LOT Bot"))
        self.about_label = QLabel()
        self.about_label.setWordWrap(True)
        self.about_label.setTextInteractionFlags(
            self.about_label.textInteractionFlags().TextSelectableByMouse
        )
        card.add(self.about_label)
        layout.addWidget(card)
        layout.addStretch(1)
        return widget

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        business = self.app.reload_business_settings()
        for key, field in self.business_fields.items():
            field.setText(str(business.get(key) or ""))

        self._refresh_templates()

        settings = self.app.settings
        index = self.ai_provider.findData(settings.ai_provider)
        if index >= 0:
            self.ai_provider.setCurrentIndex(index)
        self.ai_key_label.setText(mask(settings.anthropic_api_key))
        self.ai_model_label.setText(settings.ai_model)

        backend = self.app.backend
        color = theme.WARNING if backend.demo else theme.SUCCESS
        self.wallapop_status.setText(
            f"<b style='color:{color}'>{backend.label}</b><br>{backend.reason}"
        )
        self.client_id_label.setText(mask(settings.wallapop_client_id, visible=6))
        self.client_secret_label.setText(mask(settings.wallapop_client_secret))
        self.redirect_label.setText(settings.wallapop_redirect_uri or "(no configurada)")
        self.endpoint_label.setText(settings.wallapop_endpoint_map or "(no configurado)")

        from lot_bot.wallapop.capabilities import CAPABILITY_LABELS, Capability

        granted = self.app.wallapop.capabilities()
        lines = [
            f"{'✓' if c in granted else '✗'}  {CAPABILITY_LABELS[c]}  ({c.value})"
            for c in Capability
        ]
        lines.append("")
        lines.append(
            "Las operaciones marcadas con ✗ responden NOT_AVAILABLE_WITH_CURRENT_API. "
            "Para activarlas, declara su endpoint oficial en el fichero de endpoints."
        )
        self.capabilities_label.setPlainText("\n".join(lines))

        self.about_label.setText(
            f"<b>LOT Bot {self.app.version}</b><br><br>"
            f"Gestión y automatización multicuenta de Wallapop con asistente IA.<br><br>"
            f"Carpeta de datos: {self.app.paths.root}<br>"
            f"Base de datos: {self.app.paths.database}<br>"
            f"Registros: {self.app.paths.logs}<br><br>"
            f"Modo: {self.app.backend_label}<br>"
            f"Asistente: {self.app.agent.provider.describe()}<br><br>"
            f"Este programa debe usarse respetando los términos de Wallapop y la "
            f"autorización de automatización concedida al titular de las cuentas."
        )

    # ------------------------------------------------------------------
    def _refresh_templates(self) -> None:
        from sqlalchemy import select

        with self.app.db.session_scope() as session:
            templates = session.scalars(select(Template).order_by(Template.name)).all()
            self._templates = [
                {
                    "id": t.id,
                    "name": t.name,
                    "title_pattern": t.title_pattern,
                    "description_pattern": t.description_pattern,
                }
                for t in templates
            ]
        self.template_list.blockSignals(True)
        self.template_list.clear()
        for template in self._templates:
            self.template_list.addItem(template["name"])
        self.template_list.blockSignals(False)
        if self._templates:
            self.template_list.setCurrentRow(0)

    def _load_template(self, row: int) -> None:
        if row < 0 or row >= len(getattr(self, "_templates", [])):
            return
        template = self._templates[row]
        self.template_title.setText(template["title_pattern"])
        self.template_description.setPlainText(template["description_pattern"])

    def _save_template(self) -> None:
        row = self.template_list.currentRow()
        if row < 0 or row >= len(self._templates):
            return
        template_id = self._templates[row]["id"]
        with self.app.db.session_scope() as session:
            template = session.get(Template, template_id)
            if template is None:
                return
            template.title_pattern = self.template_title.text().strip()
            template.description_pattern = self.template_description.toPlainText()
        self.app.audit.record_success(
            "Modificación de plantilla", target=self._templates[row]["name"]
        )
        info_box(self, "Plantilla guardada", "Los cambios se aplicarán a las próximas publicaciones.")
        self._refresh_templates()

    def _save_business(self) -> None:
        values = {key: field.text().strip() for key, field in self.business_fields.items()}
        self.app.save_business_settings(values)
        info_box(
            self,
            "Datos guardados",
            "Los datos del negocio se usarán en las plantillas y en las respuestas a compradores.",
        )

    def _apply_ai(self) -> None:
        provider_key = self.ai_provider.currentData()
        settings = self.app.settings
        if provider_key == "anthropic" and not settings.anthropic_api_key:
            show_error(
                self,
                "No hay clave de API configurada.",
                "Añade ANTHROPIC_API_KEY en el fichero .env y reinicia LOT Bot.",
            )
            return
        from lot_bot.ai.anthropic_provider import AnthropicProvider
        from lot_bot.ai.rule_provider import RuleBasedProvider

        provider = (
            AnthropicProvider(settings.anthropic_api_key, settings.ai_model, settings.ai_max_tokens)
            if provider_key == "anthropic"
            else RuleBasedProvider()
        )
        self.app.set_ai_provider(provider)
        self.app.audit.record_success("Cambio de asistente IA", detail=provider.describe())
        info_box(self, "Asistente actualizado", f"Modo activo: {provider.describe()}")
        self.refresh()

    def _select_endpoint_map(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Fichero de endpoints oficiales de Wallapop", "", "YAML (*.yaml *.yml)"
        )
        if not path:
            return
        info_box(
            self,
            "Fichero seleccionado",
            f"Añade esta línea a tu fichero .env y reinicia LOT Bot:\n\n"
            f"WALLAPOP_ENDPOINT_MAP={Path(path)}\n\n"
            f"LOT Bot no modifica el .env por seguridad.",
        )

    def _reload_settings(self) -> None:
        settings = reload_settings()
        try:
            self.app.rebuild_backend(settings)
        except Exception as exc:
            show_error(self, "No se ha podido aplicar la nueva configuración.", str(exc))
            return
        info_box(self, "Configuración recargada", f"Modo activo: {self.app.backend_label}")
        self.refresh()
