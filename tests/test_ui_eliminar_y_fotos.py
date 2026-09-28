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


def test_subir_varias_fotos_propias_a_la_vez(qapp, app_with_data, tmp_path):
    """«Subir foto propia…» admite varias fotos; una rota no impide las demás."""
    from PIL import Image

    from lot_bot.ui.views.image_studio import ImageStudioView

    rutas = []
    for i in range(3):
        ruta = tmp_path / f"propia{i}.jpg"
        Image.effect_noise((1000, 800), 60 + 30 * i).convert("RGB").rotate(90 * i).save(ruta)
        rutas.append(str(ruta))
    rota = tmp_path / "rota.jpg"
    rota.write_bytes(b"no es una imagen")

    view = ImageStudioView(app_with_data, _runner())
    antes = len(app_with_data.master_ads.get(None).images)
    guardadas, usadas, problemas = view.upload_files([*rutas, str(rota)], use_in_ads=True)
    assert guardadas == 3 and usadas == 3, problemas
    assert len(problemas) == 1 and "rota.jpg" in problemas[0]
    assert len(app_with_data.master_ads.get(None).images) == antes + 3


def test_anadir_fotografias_admite_varias(qapp, app_with_data, tmp_path, monkeypatch):
    """«Anuncio principal → Fotografías… → Añadir fotografías…» también varias."""
    from PIL import Image
    from PySide6.QtWidgets import QFileDialog

    from lot_bot.ui.widgets import images_dialog

    rutas = []
    for i in range(4):
        ruta = tmp_path / f"anuncio{i}.jpg"
        Image.effect_noise((900, 700), 50 + 25 * i).convert("RGB").rotate(90 * i).save(ruta)
        rutas.append(str(ruta))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: (rutas, "")))
    monkeypatch.setattr(images_dialog, "info_box", lambda *a, **k: None)
    key = app_with_data.master_ads.get(None).key
    antes = len(app_with_data.master_ads.get(key).images)
    dialogo = images_dialog.ImagesDialog(images_dialog.master_adapter(app_with_data, key))
    dialogo._add()  # el usuario elige las 4 de golpe en la ventana
    assert len(app_with_data.master_ads.get(key).images) == antes + 4
