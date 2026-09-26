"""«Publica 1 canapé» de principio a fin en modo navegador (Wallapop simulado).

Comprueba que, tras la confirmación, es LOT Bot quien rellena y publica el
anuncio completo, y cómo se comporta con CAPTCHA, sesión caducada, ventana
de la cuenta abierta y resultado no confirmado.
"""

from __future__ import annotations

import threading
import time

import pytest

from lot_bot.master_ad.defaults import CLIENT_ATTRIBUTES, CLIENT_PRICE, CLIENT_TITLE
from tests.test_browser_integration import FORM, SITE
from tests.test_guided_flow import real  # noqa: F401  (fixture)


@pytest.fixture()
def database(temp_paths, tmp_path):
    """Base de datos en fichero: la cola corre en otro hilo en estas pruebas."""
    from lot_bot.database.engine import Database, set_database

    db = Database(f"sqlite:///{tmp_path / 'lotbot.db'}")
    db.create_all()
    set_database(db)
    yield db


def textos(respuesta) -> str:
    return " ".join(m.text for m in respuesta.messages)


@pytest.fixture()
def listo(real, tmp_path):  # noqa: F811
    from PIL import Image

    from lot_bot.publishing.queue import FakeClock

    app, world, cuenta = real
    foto = tmp_path / "canape.jpg"
    Image.new("RGB", (1200, 900), (150, 150, 155)).save(foto)
    app.master_ads.add_images(
        None, [{"path": str(foto), "file_format": "JPEG", "width": 1200, "height": 900}]
    )
    app.publish_queue.save_settings(generate_images=False)
    app.publish_queue.clock = FakeClock()
    app.backend.service.is_mock = True  # solo para poder usar el reloj de pruebas
    yield app, world, cuenta
    app.backend.service.is_mock = False


def publicar_uno(app):
    r = app.agent.ask("Publica 1 canapé en la cuenta Mi tienda")
    assert r.needs_confirmation, textos(r)
    app.agent.confirm(r.pending.token)


def en_segundo_plano(fn):
    hilo = threading.Thread(target=fn, daemon=True)
    hilo.start()
    return hilo


def esperar(condicion, segundos=10.0):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def test_publica_1_canape_lo_hace_todo_lot_bot(listo):
    app, world, cuenta = listo
    publicar_uno(app)
    app.publish_queue.run_until_idle()
    progreso = app.publish_queue.progress()
    assert progreso.published == 1, progreso.tasks
    tarea = progreso.tasks[0]
    assert tarea["url"] == world["item_url"]
    assert tarea["id_wallapop"] == "canape-canape-1001"

    pagina = world["pages"][0]
    escritos = {e[1]: e[2] for e in pagina.log if e[0] == "fill"}
    assert escritos[FORM.title.targets[0]] == CLIENT_TITLE
    assert escritos[FORM.price.targets[0]] == "11,44"
    descripcion = escritos[FORM.description.targets[0]]
    assert descripcion.startswith("GRAN OFERTA LIMITADA!") and "603710542" in descripcion
    assert "Canapé + colchón 90x190 → 230€" in descripcion
    opciones = [e[1] for e in pagina.log if e[0] == "option"]
    assert opciones == ["Hogar y jardín", *CLIENT_ATTRIBUTES.values()]
    assert any(e[0] == "files" for e in pagina.log)
    # El anuncio queda guardado en la base de datos con su URL.
    fila = next(r for r in app.stats.table() if r.account_ref == cuenta.internal_ref)
    assert fila.url == world["item_url"]
    assert CLIENT_PRICE == 11.44


def test_resultado_no_confirmado_no_cuenta_como_publicado(listo):
    app, world, _ = listo
    world["no_confirm"] = True
    app.wallapop.site.success_timeout_ms = 0
    try:
        publicar_uno(app)
        app.publish_queue.run_until_idle()
    finally:
        app.wallapop.site.success_timeout_ms = SITE.success_timeout_ms
    progreso = app.publish_queue.progress()
    assert progreso.published == 0
    tarea = progreso.tasks[0]
    assert tarea["estado"] == "unconfirmed"
    assert tarea["codigo_error"] == "RESULTADO_NO_CONFIRMADO"
    assert world["submits"] == 1  # no se reintenta a ciegas: podría duplicarse
    assert progreso.status == "paused"


def test_captcha_pausa_mantiene_el_navegador_y_continuar_sigue(listo):
    app, world, _ = listo
    world["verification"] = True
    publicar_uno(app)
    cola = app.publish_queue
    hilo = en_segundo_plano(cola.run_until_idle)
    assert esperar(lambda: cola.progress().status == "paused")
    progreso = cola.progress()
    assert "Wallapop requiere una verificación" in progreso.pause_reason
    assert "pulsa Continuar" in progreso.pause_reason
    assert app.wallapop.pool.is_open(progreso.tasks[0]["cuenta_ref"])  # sigue abierto
    world["verification"] = False  # el usuario la completa a mano
    cola.resume(progreso.job_id)  # botón «Continuar»
    hilo.join(10)
    assert cola.progress().published == 1


def test_ventana_de_la_cuenta_abierta_pide_cerrarla_y_continua(listo):
    from lot_bot.wallapop.errors import ProfileInUseError

    app, world, _ = listo
    launcher = app.wallapop.launcher
    original = launcher.open
    intentos = []

    def open_bloqueado(profile_dir, **kw):
        intentos.append(profile_dir)
        if len(intentos) == 1:
            raise ProfileInUseError("perfil en uso")
        return original(profile_dir, **kw)

    launcher.open = open_bloqueado
    publicar_uno(app)
    cola = app.publish_queue
    hilo = en_segundo_plano(cola.run_until_idle)
    assert esperar(lambda: cola.progress().status == "paused")
    assert "ya está abierta" in cola.progress().pause_reason
    cola.resume(cola.progress().job_id)
    hilo.join(10)
    assert cola.progress().published == 1
    assert intentos[0] == intentos[1]  # mismo perfil, el de la cuenta


def test_sesion_caducada_pausa_y_tras_reconectar_continua_sola(listo):
    app, world, cuenta = listo
    world["logged_in"] = False
    publicar_uno(app)
    cola = app.publish_queue
    cola.run_until_idle()
    progreso = cola.progress()
    assert progreso.status == "paused" and "Sesión caducada" in progreso.pause_reason
    assert progreso.published == 0
    # El usuario pulsa «Reconectar» e inicia sesión; se comprueba de verdad.
    world["logged_in"] = True
    app.accounts.mark_session_checked(cuenta.internal_ref, True, "ok")
    assert cola.progress().status == "running"  # sin pulsar nada más
    cola.run_until_idle()
    assert cola.progress().published == 1
    assert app.wallapop.pool.open_count == {cuenta.internal_ref: 1}  # mismo navegador


def test_varios_anuncios_reutilizan_el_mismo_perfil_y_esperan_60_s(listo):
    app, world, cuenta = listo
    r = app.agent.ask("Empieza a subir 3 anuncios en la cuenta Mi tienda")
    app.agent.confirm(r.pending.token)
    cola = app.publish_queue
    inicio = cola.clock.now()
    cola.run_until_idle()
    progreso = cola.progress()
    assert progreso.published == 3
    assert app.wallapop.pool.open_count == {cuenta.internal_ref: 1}
    assert len(world["pages"]) == 1  # un único navegador / página para toda la cola
    assert cola.clock.now() - inicio >= 120  # 3 anuncios → al menos 2 esperas de 60 s
