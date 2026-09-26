"""Cola de publicación: intervalo mínimo de 60 s, pausa, reanudación,
cancelación, errores, reintentos y multicuenta.

Se usa un reloj simulado (FakeClock): la cola respeta el intervalo, pero las
pruebas no esperan de verdad. Nada sale del ordenador.
"""

from __future__ import annotations

import pytest

from lot_bot.database.models import PublishJobStatus, PublishTaskStatus
from lot_bot.publishing.queue import (
    MINIMUM_PUBLISH_INTERVAL_SECONDS,
    FakeClock,
    validate_interval,
)
from lot_bot.wallapop.errors import ValidationRejectedError, VerificationRequiredError


def refs(app, n=None):
    cuentas = [a.internal_ref for a in app.accounts.list_accounts() if a.is_connected]
    return cuentas[:n] if n else cuentas


def publicados(progress):
    return [t for t in progress.tasks if t["estado"] == "published"]


# ---------------------------------------------------------------------------
# Intervalo mínimo
# ---------------------------------------------------------------------------
def test_el_intervalo_minimo_por_defecto_es_60(app):
    assert MINIMUM_PUBLISH_INTERVAL_SECONDS == 60
    assert app.publish_queue.settings()["minimum_publish_interval_seconds"] == 60


@pytest.mark.parametrize("valor", [0, 1, 30, 59, -5, "10"])
def test_se_rechazan_intervalos_inferiores_a_60(app, valor):
    with pytest.raises(ValueError):
        validate_interval(valor)
    with pytest.raises(ValueError):
        app.publish_queue.save_settings(minimum_publish_interval_seconds=valor)
    assert app.publish_queue.interval == 60


def test_se_admiten_intervalos_mayores(app):
    app.publish_queue.save_settings(minimum_publish_interval_seconds=90)
    assert app.publish_queue.interval == 90


def test_un_valor_manipulado_en_la_base_de_datos_no_baja_de_60(app):
    from lot_bot.database.models import Setting

    with app.db.session_scope() as session:
        session.merge(Setting(key="publicacion", value={"minimum_publish_interval_seconds": 5}))
    assert app.publish_queue.interval == 60


def test_entre_publicaciones_pasan_al_menos_60_segundos_incluso_entre_cuentas(app):
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app), copies=4, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.status == "completed"
    horas = sorted(t["publicado"] for t in publicados(progress))
    assert len(horas) == 4
    # Las 4 van a cuentas distintas y aun así respetan el intervalo.
    assert len({t["cuenta_ref"] for t in progress.tasks}) == 4
    for anterior, siguiente in zip(horas, horas[1:], strict=False):
        assert (siguiente - anterior).total_seconds() >= 60
    assert sum(queue.clock.slept) >= 3 * 60


def test_el_intervalo_es_un_minimo_si_la_imagen_tarda_mas(app):
    """Si generar la imagen ya ha consumido más de 60 s, no se espera más."""
    queue = app.publish_queue
    original = app.image_generation.generate_unique

    def lenta(*args, **kwargs):
        queue.clock.t += 150  # la generación tarda 150 s
        return original(*args, **kwargs)

    app.image_generation.generate_unique = lenta
    job = queue.enqueue_master(None, refs(app, 1), copies=2, generate_images=True)
    queue.run_until_idle()
    horas = sorted(t["publicado"] for t in publicados(queue.progress(job)))
    assert (horas[1] - horas[0]).total_seconds() >= 150


def test_la_aceleracion_de_pruebas_no_se_admite_con_wallapop_real(app):
    app.publish_queue.enqueue_master(None, refs(app, 1), copies=1, generate_images=False)
    app.backend.service.is_mock = False  # simula un servicio real
    try:
        with pytest.raises(RuntimeError, match="DEMO"):
            app.publish_queue.run_once()
    finally:
        app.backend.service.is_mock = True


# ---------------------------------------------------------------------------
# Control: pausar, reanudar, cancelar
# ---------------------------------------------------------------------------
def test_pausar_y_reanudar(app):
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app), copies=3, generate_images=False)
    assert queue.run_once()  # publica el primero
    queue.pause(job)
    assert queue.run_until_idle() == 0  # en pausa no se publica nada
    progress = queue.progress(job)
    assert progress.status == "paused" and progress.published == 1 and progress.pending == 2
    queue.resume(job)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.status == "completed" and progress.published == 3


def test_cancelar_no_toca_lo_publicado(app):
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app), copies=4, generate_images=False)
    queue.run_once()
    assert queue.cancel(job) == 3
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.status == "cancelled"
    assert progress.published == 1 and progress.cancelled == 3
    assert len(app.master_ads.publications()) == 1


def test_la_cola_no_empieza_sin_iniciarla(app):
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app), copies=2, generate_images=False, start=False)
    assert queue.run_until_idle() == 0
    assert queue.progress(job).status == "pending"
    queue.start(job)
    queue.run_until_idle()
    assert queue.progress(job).published == 2


# ---------------------------------------------------------------------------
# Errores y reintentos
# ---------------------------------------------------------------------------
def test_error_de_publicacion_se_registra_y_se_reintenta_una_vez(app, monkeypatch):
    service = app.wallapop
    original = service.create_item
    llamadas = {"n": 0}

    def falla_una_vez(ref, draft):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise ValidationRejectedError("rechazado")
        return original(ref, draft)

    monkeypatch.setattr(service, "create_item", falla_una_vez)
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app, 1), copies=1, generate_images=False)
    queue.run_once()
    task = queue.progress(job).tasks[0]
    assert task["estado"] == "pending" and task["intentos"] == 1
    assert task["codigo_error"] == "ValidationRejectedError"
    inicio_fallo = queue.clock.now()
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.published == 1
    # El reintento espera más que el intervalo normal (el doble).
    assert queue.clock.now() - inicio_fallo >= 120
    errores = [e for e in app.audit.recent(limit=50) if e.result == "error"]
    assert any("Publicación en cola fallida" in e.action for e in errores)


def test_si_falla_el_reintento_queda_fallido_y_la_cola_se_pausa(app, monkeypatch):
    monkeypatch.setattr(
        app.wallapop,
        "create_item",
        lambda ref, draft: (_ for _ in ()).throw(ValidationRejectedError("no")),
    )
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app), copies=3, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.failed == 1
    assert progress.status == "paused"  # no sigue sin control
    assert progress.pending == 2
    assert "fallos seguidos" in progress.pause_reason


def test_una_verificacion_de_wallapop_pausa_la_cola_sin_reintentar(app, monkeypatch):
    llamadas = {"n": 0}

    def verificacion(ref, draft):
        llamadas["n"] += 1
        raise VerificationRequiredError("captcha")

    monkeypatch.setattr(app.wallapop, "create_item", verificacion)
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app), copies=3, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert llamadas["n"] == 1  # jamás se insiste ante una verificación
    assert progress.status == "paused"
    assert progress.tasks[0]["estado"] == "failed"
    assert "verificación" in progress.pause_reason.lower()


def test_reintentar_un_anuncio_fallido(app, monkeypatch):
    service = app.wallapop
    original = service.create_item
    estado = {"romper": True}

    def quizas(ref, draft):
        if estado["romper"]:
            raise VerificationRequiredError("captcha")
        return original(ref, draft)

    monkeypatch.setattr(service, "create_item", quizas)
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app, 1), copies=1, generate_images=False)
    queue.run_until_idle()
    fallido = queue.progress(job).tasks[0]
    assert fallido["estado"] == "failed"

    estado["romper"] = False  # el usuario ha completado la verificación
    queue.retry_task(fallido["id"])
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.published == 1 and progress.status == "completed"


def test_solo_se_reintentan_anuncios_fallidos(app):
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app, 1), copies=1, generate_images=False)
    with pytest.raises(ValueError):
        queue.retry_task(queue.progress(job).tasks[0]["id"])


# ---------------------------------------------------------------------------
# Multicuenta
# ---------------------------------------------------------------------------
def test_cada_anuncio_indica_que_cuenta_lo_publico(app):
    queue = app.publish_queue
    cuentas = refs(app, 2)
    job = queue.enqueue_master(None, cuentas, copies=4, generate_images=False)
    queue.run_until_idle()
    tasks = queue.progress(job).tasks
    assert [t["cuenta_ref"] for t in tasks] == [cuentas[0], cuentas[1], cuentas[0], cuentas[1]]
    por_cuenta = {}
    for anuncio in app.master_ads.publications():
        por_cuenta[anuncio.account_ref] = por_cuenta.get(anuncio.account_ref, 0) + 1
    assert por_cuenta == {cuentas[0]: 2, cuentas[1]: 2}
    publicados_por_id = {(a.account_ref, a.wallapop_item_id) for a in app.master_ads.publications()}
    for task in tasks:
        assert (task["cuenta_ref"], task["id_wallapop"]) in publicados_por_id


def test_publicaciones_quedan_en_el_historial_con_su_cuenta(app):
    queue = app.publish_queue
    queue.enqueue_master(None, refs(app, 2), copies=2, generate_images=False)
    queue.run_until_idle()
    entradas = [
        e for e in app.audit.recent(limit=100) if "Publicación del anuncio principal" in e.action
    ]
    assert {e.account_ref for e in entradas} == set(refs(app, 2))
    assert all(e.action.startswith("[DEMO]") for e in entradas)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
def test_publica_10_canapes_crea_la_cola_tras_confirmar(app):
    agente = app.agent
    respuesta = agente.ask("Publica 10 canapés")
    assert respuesta.needs_confirmation
    plan = respuesta.pending.request
    texto = " ".join(plan.lines)
    assert "60 segundos" in texto
    assert "imagen de DEMOSTRACIÓN distinta" in texto
    assert app.publish_queue.latest_job_id() is None  # nada antes de confirmar

    agente.confirm(plan.token)
    job = app.publish_queue.latest_job_id()
    assert app.publish_queue.progress(job).total == 10
    app.publish_queue.run_until_idle()
    assert app.publish_queue.progress(job).published == 10


@pytest.mark.parametrize(
    ("frase", "herramienta"),
    [
        ("¿Cómo va la cola?", "get_publish_queue"),
        ("Pausa la cola", "pause_publish_queue"),
        ("Reanuda la cola", "resume_publish_queue"),
        ("Cancela la cola", "cancel_publish_queue"),
        ("Reintenta los fallidos", "retry_failed_publications"),
    ],
)
def test_ordenes_de_la_cola(frase, herramienta):
    from lot_bot.ai.rule_provider import RuleBasedProvider

    llamada = RuleBasedProvider()._match(frase)
    assert llamada is not None and llamada.name == herramienta


def test_el_estado_de_la_cola_se_ve_en_el_chat(app):
    agente = app.agent
    agente.confirm(agente.ask("Publica 3 canapés").pending.token)
    app.publish_queue.run_once()
    texto = " ".join(m.text for m in agente.ask("¿Cómo va la cola?").messages)
    assert "1/3" in texto and "Próxima publicación permitida" in texto


def test_fake_clock_solo_avanza_el_tiempo():
    import threading

    reloj = FakeClock(start=0)
    reloj.sleep(61, threading.Event())
    assert reloj.now() == 61


def test_estado_de_trabajo_y_tarea_son_enumeraciones():
    assert PublishJobStatus.RUNNING.value == "running"
    assert PublishTaskStatus.PUBLISHED.value == "published"


def test_en_modo_real_las_cuentas_demo_no_publican(app):
    app.backend.demo = False
    try:
        with pytest.raises(ValueError, match="solo de demostración"):
            app.publish_queue.enqueue_master(None, refs(app, 1), copies=1, generate_images=False)
    finally:
        app.backend.demo = True


def test_si_wallapop_pide_entrar_la_cola_espera_y_la_cuenta_no_caduca(app, monkeypatch):
    from lot_bot.database.models import AccountStatus
    from lot_bot.wallapop.errors import AuthenticationError

    cuenta_a, cuenta_b = refs(app, 2)
    service = app.wallapop
    original = service.create_item
    caducada = {"b": True}

    def publicar(ref, draft):
        if ref == cuenta_b and caducada["b"]:
            raise AuthenticationError("sesión caducada")
        return original(ref, draft)

    monkeypatch.setattr(service, "create_item", publicar)
    queue = app.publish_queue
    job = queue.enqueue_master(None, [cuenta_a, cuenta_b], copies=4, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    por_cuenta = {}
    for t in progress.tasks:
        por_cuenta.setdefault(t["cuenta_ref"], []).append(t["estado"])
    assert por_cuenta[cuenta_a][0] == "published"
    assert por_cuenta[cuenta_b] == ["pending", "pending"]  # B espera
    assert progress.failed == 0
    assert progress.status == "paused" and "Continuar" in progress.pause_reason
    # La cuenta NO caduca: solo deja de funcionar si el usuario la elimina.
    assert app.accounts.get_account(cuenta_b).status == AccountStatus.CONNECTED

    # El usuario reconecta B y reanuda: se reutiliza su sesión y termina.
    caducada["b"] = False
    app.accounts.mark_session_checked(cuenta_b, True)
    queue.resume(job)
    queue.run_until_idle()
    assert queue.progress(job).published == 4
