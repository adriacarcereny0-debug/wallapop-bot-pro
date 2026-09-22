"""Ventana principal de LOT Bot: barra lateral y pantallas."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from lot_bot import APP_NAME
from lot_bot.ui import theme
from lot_bot.ui.views import (
    AccountsView,
    AssistantView,
    AutomationsView,
    DashboardView,
    HistoryView,
    InventoryView,
    ListingsView,
    LogsView,
    MessagesView,
    PricingView,
    ProductsView,
    SettingsView,
)
from lot_bot.ui.widgets.workers import TaskRunner

if TYPE_CHECKING:  # pragma: no cover
    from lot_bot.bootstrap import Application

logger = logging.getLogger(__name__)

#: (etiqueta, icono textual, clase de la vista)
NAVIGATION = [
    ("Panel", "▦", DashboardView),
    ("Asistente IA", "✦", AssistantView),
    ("Cuentas Wallapop", "◉", AccountsView),
    ("Productos", "▤", ProductsView),
    ("Anuncios", "◨", ListingsView),
    ("Inventario", "▩", InventoryView),
    ("Precios", "€", PricingView),
    ("Mensajes", "✉", MessagesView),
    ("Automatizaciones", "⟳", AutomationsView),
    ("Historial", "☰", HistoryView),
    ("Configuración", "⚙", SettingsView),
    ("Logs y errores", "⚠", LogsView),
]


class MainWindow(QMainWindow):
    """Ventana principal."""

    def __init__(self, app: "Application") -> None:
        super().__init__()
        self.app = app
        self.runner = TaskRunner()

        self.setWindowTitle(f"{APP_NAME} {app.version}")
        self.resize(1360, 860)
        self.setMinimumSize(1080, 700)
        self.setWindowIcon(_build_icon())

        central = QWidget()
        central.setObjectName("Content")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.views: list = []
        for index, (label, _icon, view_class) in enumerate(NAVIGATION):
            try:
                view = view_class(self.app, self.runner)
            except Exception:  # una vista rota no debe impedir abrir el programa
                logger.exception("No se ha podido crear la pantalla '%s'", label)
                view = _error_placeholder(label)
            self.views.append(view)
            self.stack.addWidget(view)

        status = QStatusBar()
        self.status_label = QLabel()
        status.addWidget(self.status_label)
        self.setStatusBar(status)
        self._update_status()

        self.nav_buttons[0].setChecked(True)
        self._go_to(0)

    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        brand = QLabel(APP_NAME)
        brand.setObjectName("Brand")
        layout.addWidget(brand)

        self.brand_sub = QLabel()
        self.brand_sub.setObjectName("BrandSub")
        layout.addWidget(self.brand_sub)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, (label, icon, _view) in enumerate(NAVIGATION):
            button = QPushButton(f"  {icon}   {label}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self._go_to(i))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch(1)

        self.mode_label = QLabel()
        self.mode_label.setWordWrap(True)
        self.mode_label.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px; padding: 10px 18px;"
        )
        layout.addWidget(self.mode_label)
        return sidebar

    # ------------------------------------------------------------------
    def _go_to(self, index: int) -> None:
        """Muestra una pantalla y recarga sus datos."""
        self.stack.setCurrentIndex(index)
        if index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        # Se refresca siempre de forma explicita: `currentChanged` no se emite
        # cuando se vuelve a seleccionar la pantalla que ya estaba activa.
        self._on_page_changed(index)

    def _on_page_changed(self, index: int) -> None:
        view = self.stack.widget(index)
        refresh = getattr(view, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                logger.exception("Error al refrescar la pantalla %s", type(view).__name__)
        self._update_status()

    def _update_status(self) -> None:
        backend = self.app.backend
        mode = "MODO DEMO — datos simulados" if backend.demo else "Wallapop Connect"
        accounts = self.app.accounts.list_accounts()
        connected = sum(1 for a in accounts if a.is_connected)
        self.status_label.setText(
            f"  {mode}   ·   {connected}/{len(accounts)} cuentas conectadas   ·   "
            f"Asistente: {self.app.agent.provider.describe()}"
        )
        self.brand_sub.setText(mode)
        self.mode_label.setText(
            f"Datos en:\n{self.app.paths.root}" if not backend.demo else
            f"MODO DEMO\nNada de lo que hagas afecta a Wallapop."
        )

    def refresh_current(self) -> None:
        self._on_page_changed(self.stack.currentIndex())

    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - firma de Qt
        logger.info("Cerrando la ventana principal.")
        self.runner.wait(2000)
        self.app.shutdown()
        super().closeEvent(event)


def _error_placeholder(label: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    message = QLabel(
        f"No se ha podido cargar la pantalla «{label}».\n"
        f"Consulta la pantalla de Logs para ver el detalle técnico."
    )
    message.setAlignment(Qt.AlignmentFlag.AlignCenter)
    message.setWordWrap(True)
    layout.addWidget(message)
    return widget


def _build_icon() -> QIcon:
    """Icono de la aplicacion.

    Usa el fichero empaquetado si esta disponible y, si no, lo dibuja en
    memoria para que el programa funcione igualmente.
    """
    from PySide6.QtGui import QColor, QPainter

    from lot_bot.config.paths import get_paths

    for candidate in (
        get_paths().resources / "lot_bot.ico",
        get_paths().resources / "lot_bot.png",
    ):
        if candidate.is_file():
            icon = QIcon(str(candidate))
            if not icon.isNull():
                return icon

    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(theme.BG_ELEVATED))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(theme.ACCENT))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(8, 8, 48, 48, 12, 12)
    painter.setPen(QColor("#05201b"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(22)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "L")
    painter.end()
    return QIcon(pixmap)
