"""Pantallas: eliminar varios anuncios y opción de fotos que se guarda sola."""

from __future__ import annotations

import os

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


def _fotos_distintas(carpeta, n, prefijo):
    from PIL import Image

    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for i in range(n):
        ruta = carpeta / f"{prefijo}{i}.jpg"
        # Contenido al azar: nunca coincide con fotos de otras pruebas.
        pequena = Image.frombytes("RGB", (12, 9), os.urandom(12 * 9 * 3))
        pequena.resize((900, 700), Image.Resampling.NEAREST).save(ruta)
        rutas.append(ruta)
    (carpeta / "nota.txt").write_text("no es una foto")
    return rutas


def _soltar(widget, rutas):
    """Arrastrar y soltar desde el Explorador de Windows (evento real de Qt)."""
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(r)) for r in rutas])
    evento = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(evento)


def test_arrastrar_fotos_y_carpetas_a_fotografias(qapp, app_with_data, tmp_path, monkeypatch):
    from lot_bot.ui.widgets import images_dialog

    monkeypatch.setattr(images_dialog, "info_box", lambda *a, **k: None)
    key = app_with_data.master_ads.get(None).key
    dialogo = images_dialog.ImagesDialog(images_dialog.master_adapter(app_with_data, key))
    assert dialogo.acceptDrops()
    antes = len(app_with_data.master_ads.get(key).images)

    sueltas = _fotos_distintas(tmp_path / "sueltas", 3, "s")
    _soltar(dialogo, sueltas)  # 3 fotos sueltas
    carpeta = tmp_path / "carpeta"
    _fotos_distintas(carpeta, 4, "c")
    _soltar(dialogo, [carpeta])  # una carpeta entera (el .txt se ignora)
    assert len(app_with_data.master_ads.get(key).images) == antes + 7


def test_anadir_carpeta_completa(qapp, app_with_data, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from lot_bot.ui.widgets import images_dialog

    carpeta = tmp_path / "fotos"
    _fotos_distintas(carpeta, 5, "f")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(carpeta)))
    monkeypatch.setattr(images_dialog, "info_box", lambda *a, **k: None)
    key = app_with_data.master_ads.get(None).key
    antes = len(app_with_data.master_ads.get(key).images)
    dialogo = images_dialog.ImagesDialog(images_dialog.master_adapter(app_with_data, key))
    dialogo._add_folder()
    assert len(app_with_data.master_ads.get(key).images) == antes + 5


def test_imagenes_ia_carpeta_y_arrastrar(qapp, app_with_data, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from lot_bot.ui.views import image_studio

    monkeypatch.setattr(image_studio, "ask_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(image_studio, "info_box", lambda *a, **k: None)
    view = image_studio.ImageStudioView(app_with_data, _runner())
    assert view.acceptDrops()
    antes = len(app_with_data.master_ads.get(None).images)
    carpeta = tmp_path / "estudio"
    _fotos_distintas(carpeta, 3, "e")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(carpeta)))
    view._upload_folder()
    _soltar(view, _fotos_distintas(tmp_path / "mas", 2, "m"))
    assert len(app_with_data.master_ads.get(None).images) == antes + 5


def _dialogo_con_fotos(app_with_data, tmp_path, monkeypatch, n):
    from lot_bot.ui.widgets import images_dialog

    monkeypatch.setattr(images_dialog, "info_box", lambda *a, **k: None)
    monkeypatch.setattr(images_dialog, "ask_confirmation", lambda *a, **k: True)
    key = app_with_data.master_ads.get(None).key
    dialogo = images_dialog.ImagesDialog(images_dialog.master_adapter(app_with_data, key))
    dialogo.add_paths([str(r) for r in _fotos_distintas(tmp_path / "g", n, "g")])
    return dialogo, key


def test_fotografias_arrastrar_el_raton_selecciona_varias(qapp, app_with_data, tmp_path, monkeypatch):
    """Mantener el clic y arrastrar sobre las fotos las selecciona todas."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    dialogo, _ = _dialogo_con_fotos(app_with_data, tmp_path, monkeypatch, 4)
    dialogo.resize(1100, 700)
    dialogo.show()
    qapp.processEvents()
    vista = dialogo.gallery.viewport()
    rects = [dialogo.gallery.visualItemRect(dialogo.gallery.item(i)) for i in range(4)]
    desde = QPoint(2, 2)
    hasta = QPoint(max(r.right() for r in rects) + 4, max(r.bottom() for r in rects) + 4)
    QTest.mousePress(vista, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, desde)
    for paso in range(1, 11):  # movimiento real, poco a poco
        punto = desde + (hasta - desde) * paso / 10
        QTest.mouseMove(vista, punto)
        qapp.processEvents()
    QTest.mouseRelease(vista, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, hasta)
    assert len(dialogo.selected_indexes()) == 4
    assert dialogo.remove_button.isEnabled() and "(4)" in dialogo.remove_button.text()
    dialogo.close()


def test_fotografias_quitar_varias_de_golpe(qapp, app_with_data, tmp_path, monkeypatch):
    dialogo, key = _dialogo_con_fotos(app_with_data, tmp_path, monkeypatch, 5)
    total = len(app_with_data.master_ads.get(key).images)
    for fila in (0, 2, 4):
        dialogo.gallery.item(fila).setSelected(True)
    dialogo._remove()
    assert len(app_with_data.master_ads.get(key).images) == total - 3

    dialogo.select_all_button.click()
    assert len(dialogo.selected_indexes()) == total - 3
    dialogo._toggle_use()  # todas «no usar» (o «usar») de una vez
    estados = {i.get("enabled", True) for i in app_with_data.master_ads.get(key).images}
    assert len(estados) == 1


def test_imagenes_ia_borrar_varias(qapp, app_with_data, tmp_path, monkeypatch):
    from lot_bot.ui.views import image_studio

    monkeypatch.setattr(image_studio, "ask_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(image_studio, "info_box", lambda *a, **k: None)
    view = image_studio.ImageStudioView(app_with_data, _runner())
    view.upload_files([str(r) for r in _fotos_distintas(tmp_path / "b", 4, "b")], use_in_ads=False)
    view.refresh()
    antes = view.images.count()
    view.select_all_button.click()
    assert len(view.selected_ids()) == antes >= 4
    assert "(" in view.delete_button.text()
    view._delete_selected()
    assert view.images.count() == 0
    # Los originales de tu ordenador siguen ahí.
    assert all(p.exists() for p in (tmp_path / "b").glob("*.jpg"))
