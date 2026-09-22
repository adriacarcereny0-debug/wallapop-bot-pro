"""Pruebas de humo de la interfaz: todas las pantallas deben construirse y
refrescarse sin fallar, y el panel de confirmacion debe funcionar."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.ui

pytest.importorskip("PySide6", reason="PySide6 no está instalado")


@pytest.fixture(scope="module")
def qt_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from lot_bot.ui.theme import stylesheet

    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(stylesheet())
    return application


def test_la_ventana_principal_carga_todas_las_pantallas(qt_app, app_with_data):
    from lot_bot.ui.main_window import NAVIGATION, MainWindow

    ventana = MainWindow(app_with_data)
    assert len(ventana.views) == len(NAVIGATION)

    for indice, (etiqueta, _icono, clase) in enumerate(NAVIGATION):
        ventana._go_to(indice)
        qt_app.processEvents()
        actual = ventana.stack.currentWidget()
        assert isinstance(actual, clase), f"La pantalla «{etiqueta}» no se ha cargado"
    ventana.close()


def test_el_panel_de_confirmacion_emite_los_eventos(qt_app):
    from lot_bot.ui.widgets.common import ConfirmationPanel

    panel = ConfirmationPanel()
    recibidos: list[str] = []
    panel.confirmed.connect(recibidos.append)
    panel.show_request("tok-1", "Voy a modificar 8 anuncios", ["Cuenta 1: 3"], False)
    assert not panel.isHidden()
    panel._on_confirm()
    assert recibidos == ["tok-1"]
    assert panel.isHidden()


def test_el_panel_de_confirmacion_permite_cancelar(qt_app):
    from lot_bot.ui.widgets.common import ConfirmationPanel

    panel = ConfirmationPanel()
    cancelados: list[str] = []
    panel.cancelled.connect(cancelados.append)
    panel.show_request("tok-2", "Voy a ELIMINAR un anuncio", ["Anuncio X"], True)
    panel._on_cancel()
    assert cancelados == ["tok-2"]


def test_el_asistente_muestra_la_confirmacion(qt_app, app_with_data):
    from lot_bot.ui.views.assistant import AssistantView
    from lot_bot.ui.widgets.workers import TaskRunner

    vista = AssistantView(app_with_data, TaskRunner())
    vista.refresh()
    respuesta = app_with_data.agent.ask("Cambia el precio de los canapés de 135x190 a 269 €")
    vista._on_response(respuesta)
    qt_app.processEvents()
    # isVisibleTo: el panel esta mostrado dentro de su vista (que en la prueba
    # no esta dentro de una ventana abierta).
    assert vista.confirmation.isVisibleTo(vista)
    assert "modificar" in vista.confirmation.title.text().lower()
    # La ejecucion real tras confirmar se prueba en test_ai_agent.py, donde no
    # hace falta bombear el bucle de eventos de Qt.


def test_la_pantalla_de_cuentas_no_muestra_tokens(qt_app, app_with_data):
    from lot_bot.ui.views.accounts import AccountsView
    from lot_bot.ui.widgets.workers import TaskRunner

    vista = AccountsView(app_with_data, TaskRunner())
    vista.refresh()
    textos = []
    for fila in range(vista.table.rowCount()):
        for columna in range(vista.table.columnCount()):
            elemento = vista.table.item(fila, columna)
            if elemento is not None:
                textos.append(elemento.text())
    contenido = " ".join(textos).lower()
    for palabra in ("token", "secret", "bearer", "password"):
        assert palabra not in contenido
