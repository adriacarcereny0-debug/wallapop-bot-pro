"""Flujo completo con un Chromium REAL contra una página LOCAL que imita
Wallapop (tests/fixtures/wallapop_simulado). No se conecta a Wallapop.

Se ejecuta si Playwright y un Chromium están disponibles. Para verlo en
pantalla: LOT_BOT_VISIBLE_TESTS=1 (con escritorio o xvfb-run).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lot_bot.master_ad.defaults import CLIENT_ATTRIBUTES, CLIENT_TITLE
from lot_bot.wallapop.dto import ItemDraft

playwright = pytest.importorskip("playwright.sync_api")

CHROMIUM = os.environ.get("LOT_BOT_BROWSER_EXECUTABLE") or next(
    (str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), ""
)
pytestmark = pytest.mark.skipif(not CHROMIUM, reason="No hay Chromium para la prueba real.")

DESCRIPCION = (
    "GRAN OFERTA LIMITADA! Renueva tu descanso hoy y paga menos ✨ Canapé + colchón 90x190 → "
    "230€ ✨ Canapé + colchón 135x190 → 270€ ✨ Canapé + colchón 150x190 → 290€ 🚚 Transporte y "
    "montaje GRATUITO 📲 Pide el tuyo ahora por WhatsApp: 603710542 🕒 Solo por tiempo limitado. "
    "¡No te quedes sin el tuyo"
)


@pytest.fixture()
def servicio(tmp_path, monkeypatch):
    from lot_bot.wallapop.browser import (
        BrowserProfileStore,
        BrowserWallapopService,
        PlaywrightLauncher,
        load_site_config,
    )
    from tests.wallapop_simulado import SimulatedWallapop

    monkeypatch.setenv("LOT_BOT_BROWSER_EXECUTABLE", CHROMIUM)
    monkeypatch.setenv("LOT_BOT_BROWSER_SANDBOX", "0")  # solo contenedor Linux de pruebas
    visible = os.environ.get("LOT_BOT_VISIBLE_TESTS") == "1"
    base = load_site_config(Path(__file__).resolve().parents[1] / "lot_bot/resources/wallapop_browser.yaml")
    with SimulatedWallapop() as web:
        site = web.site(base)
        site.visible = visible
        site.success_timeout_ms = 15000
        profiles = BrowserProfileStore(tmp_path / "perfiles")
        service = BrowserWallapopService(
            profiles,
            launcher=PlaywrightLauncher(10000),
            site=site,
            screenshots_dir=tmp_path / "logs" / "navegador",
            is_account_connected=lambda ref: True,
        )
        yield service, web, tmp_path
        service.shutdown()


def borrador(tmp_path) -> ItemDraft:
    from PIL import Image

    foto = tmp_path / "canape.jpg"
    Image.new("RGB", (800, 600), (140, 140, 150)).save(foto)
    return ItemDraft(
        title=CLIENT_TITLE,
        description=DESCRIPCION,
        price=11.44,
        category="Hogar y jardín",
        condition="Nuevo",
        attributes=dict(CLIENT_ATTRIBUTES),
        image_paths=[str(foto)],
    )


def test_navegador_real_publica_el_canape_completo(servicio):
    service, web, tmp_path = servicio
    resultado = service.create_item("cuenta-1", borrador(tmp_path))
    assert resultado.success, resultado.message
    assert resultado.data["confirmado"]
    assert resultado.item_id == "canape-canape-701"
    assert resultado.data["url"] == f"{web.base}/item/canape-canape-701"
    assert web.published == [{"titulo": CLIENT_TITLE, "precio": "11,44", "fotos": 1}]
    # Pulsa «Continuar» tras el título y NUNCA el menú «Categorías» de la cabecera.
    assert "Continuar tras el título" in resultado.data["pasos"]
    assert "/buscar-categorias" not in web.visited
    # Mismo perfil persistente en la segunda publicación (no se vuelve a abrir).
    assert service.create_item("cuenta-1", borrador(tmp_path)).success
    assert service.pool.open_count == {"cuenta-1": 1}
    assert len(web.published) == 2


def test_navegador_real_no_publica_si_el_precio_no_coincide(servicio):
    from lot_bot.wallapop.errors import FormMismatchError

    service, web, tmp_path = servicio
    # La web «reformatea» el precio: el formulario queda con otro valor.
    service.site.price_format = "punto"
    datos = borrador(tmp_path)
    original = service.listing_data

    def con_precio_cambiado(draft):
        data = original(draft)
        data.price_text = "12.00"
        return data

    service.listing_data = con_precio_cambiado
    with pytest.raises(FormMismatchError) as info:
        service.create_item("cuenta-1", datos)
    assert "Precio" in info.value.fields
    assert web.published == []  # no se pulsó «Publicar»
    assert list((tmp_path / "logs" / "navegador").glob("*comprobar_formulario*.png"))


def test_navegador_real_sin_sesion_no_publica(servicio):
    from lot_bot.wallapop.errors import AuthenticationError

    service, web, tmp_path = servicio
    service.site.check_private = ["#no-existe"]
    service.site.logged_in = ["#no-existe"]
    with pytest.raises(AuthenticationError):
        service.create_item("cuenta-1", borrador(tmp_path))
    assert web.published == []


def test_navegador_real_captcha_espera_al_usuario_y_continua(servicio):
    """Wallapop (simulado) muestra un CAPTCHA: LOT Bot no lo toca, espera a
    «Continuar» y sigue. Aquí el «usuario» es la prueba, que pulsa el botón de
    la verificación simulada como lo haría una persona."""
    service, web, tmp_path = servicio
    paginas = []
    original_open = service.launcher.open

    def open_y_guardar(profile_dir, **kw):
        cm = original_open(profile_dir, **kw)

        class Envoltorio:
            def __enter__(self_inner):
                page = cm.__enter__()
                paginas.append(page)
                return page

            def __exit__(self_inner, *exc):
                return cm.__exit__(*exc)

        return Envoltorio()

    service.launcher.open = open_y_guardar
    service.site.urls["subir"] += "?captcha=1"
    avisos = []

    def gate(ref, mensaje):
        avisos.append(mensaje)
        paginas[0].click("text=He completado la verificación")  # la persona
        return True

    service.user_gate = gate
    resultado = service.create_item("cuenta-1", borrador(tmp_path))
    assert resultado.success, resultado.message
    assert avisos and "Wallapop requiere una verificación" in avisos[0]
    assert len(web.published) == 1
    assert list((tmp_path / "logs" / "navegador").glob("*verificacion*.png"))
