"""Pantallas: eliminar varios anuncios y opción de fotos que se guarda sola."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def _runner():
    from lot_bot.ui.widgets.workers import TaskRunner

    return TaskRunner(1)


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_seleccionar_todos_los_de_la_cuenta_y_eliminar_varios(qapp, app_with_data, monkeypatch):
    from lot_bot.ui.views import listings as pantalla

    view = pantalla.ListingsView(app_with_data, _runner())
    view.refresh()
    cuenta = app_with_data.accounts.list_accounts()[0]
    view.account_filter.setCurrentIndex(view.account_filter.findData(cuenta.internal_ref))
    view._select_all_active()
    activos = [v.id for v in view._listings if v.status == "active"]
    assert activos and sorted(view._selected_ids()) == sorted(activos)
    assert view.delete_button.isEnabled()

    preguntas, lanzado = [], []
    monkeypatch.setattr(pantalla, "ask_confirmation", lambda *a, **k: preguntas.append(a[2]) or True)
    monkeypatch.setattr(view, "run_task", lambda fn, **k: lanzado.append(fn))
    view._delete()
    assert f"ELIMINAR {len(activos)} anuncio(s)" in preguntas[0]
    assert cuenta.alias in preguntas[0] and "NO se puede deshacer" in preguntas[0]
    assert len(lanzado) == 1


def test_la_opcion_de_fotos_se_guarda_al_elegirla(qapp, app_with_data):
    from lot_bot.ui.views.settings import SettingsView

    view = SettingsView(app_with_data, _runner())
    view.refresh()
    view.publish_images.setCurrentIndex(view.publish_images.findData("rotar"))
    ajustes = app_with_data.publish_queue.settings()
    assert ajustes["rotate_photos"] is True and ajustes["generate_images"] is False
    view.publish_images.setCurrentIndex(0)
    assert app_with_data.publish_queue.settings()["rotate_photos"] is False
