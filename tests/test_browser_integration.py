"""Integración por navegador, con un navegador SIMULADO.

Ninguna prueba abre Wallapop ni un navegador real: se usa `FakeLauncher`, que
imita las páginas según lo que declara `wallapop_browser.yaml`.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from lot_bot.wallapop.browser import (
    BrowserLauncher,
    BrowserPage,
    BrowserProfileStore,
    BrowserSessionAuthMethod,
    BrowserWallapopService,
    UnsafeProfileLocation,
    load_site_config,
)
from lot_bot.wallapop.capabilities import Capability
from lot_bot.wallapop.dto import ItemDraft
from lot_bot.wallapop.errors import (
    AuthenticationError,
    BrowserStepError,
    NotAvailableWithCurrentAPIError,
    VerificationRequiredError,
)

SITE = load_site_config(Path(__file__).resolve().parents[1] / "lot_bot/resources/wallapop_browser.yaml")


class FakePage(BrowserPage):
    def __init__(self, world: dict) -> None:
        self.world = world
        self.url = ""
        self.log: list[tuple] = []

    def goto(self, url: str) -> None:
        self.url = url
        self.log.append(("goto", url))

    def current_url(self) -> str:
        if self.world.get("published") and self.world.get("item_url"):
            return self.world["item_url"]
        return self.url

    def first_visible(self, targets, timeout_ms=0):
        visible = set(self.world.get("visible", set()))
        if self.world.get("logged_in"):
            visible |= {SITE.logged_in[0]}
        else:
            visible |= {SITE.logged_out[0]}
        if self.world.get("verification"):
            visible |= {SITE.verification[0]}
        if self.world.get("published"):
            visible |= set(SITE.success_texts)
        for step in SITE.steps:
            if step.targets and step.name not in self.world.get("missing_steps", set()):
                visible.add(step.targets[0])
        for target in targets:
            if target in visible:
                return target
        return None

    def fill(self, target, text):
        self.log.append(("fill", target, text))

    def click(self, target):
        self.log.append(("click", target))
        publish_step = next(s for s in SITE.steps if s.name == "Publicar")
        if target == publish_step.targets[0]:
            self.world["published"] = True

    def click_option(self, text, timeout_ms):
        self.log.append(("option", text))
        return True

    def set_files(self, target, paths):
        self.log.append(("files", target, list(paths)))

    def text_of(self, target):
        return self.world.get("user_name", "")

    def links_matching(self, pattern):
        return []

    def wait(self, ms):
        self.world["waited"] = self.world.get("waited", 0) + ms

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")


class FakeLauncher(BrowserLauncher):
    def __init__(self, world: dict) -> None:
        self.world = world
        self.opened: list[Path] = []
        self.pages: list[FakePage] = []

    @contextmanager
    def open(self, profile_dir, *, visible, channels, locale):
        profile_dir = Path(profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        # Un navegador real deja ficheros en el perfil (cookies, etc.).
        (profile_dir / "Cookies").write_text("cifradas-por-el-navegador")
        self.opened.append(profile_dir)
        page = FakePage(self.world)
        self.pages.append(page)
        yield page


@pytest.fixture()
def profiles(tmp_path):
    return BrowserProfileStore(tmp_path / "browser_profiles")


def make_service(profiles, world, tmp_path, connected=True):
    launcher = FakeLauncher(world)
    service = BrowserWallapopService(
        profiles,
        launcher=launcher,
        site=SITE,
        screenshots_dir=tmp_path / "shots",
        is_account_connected=lambda ref: connected,
    )
    return service, launcher


def draft(tmp_path):
    image = tmp_path / "foto.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    return ItemDraft(
        title="Canapé canapé canapé canapé canapé canapé",
        description="GRAN OFERTA",
        price=11.44,
        category="Hogar y jardín",
        condition="Nuevo",
        image_paths=[str(image)],
    )


# ---------------------------------------------------------------------------
# Selectores centralizados
# ---------------------------------------------------------------------------
def test_los_selectores_viven_en_un_unico_fichero_y_no_estan_verificados():
    assert SITE.verified is False  # honestidad: no se han probado contra la web real
    assert SITE.url("inicio").startswith("https://es.wallapop.com")
    nombres = [s.name for s in SITE.steps]
    for paso in ("Título", "Descripción", "Precio", "Categoría", "Fotografías", "Publicar"):
        assert paso in nombres
    assert SITE.verification, "debe saber reconocer verificaciones para detenerse"


def test_el_codigo_no_contiene_selectores_de_wallapop():
    raiz = Path(__file__).resolve().parents[1] / "lot_bot" / "wallapop" / "browser"
    for fichero in raiz.glob("*.py"):
        texto = fichero.read_text(encoding="utf-8")
        assert "input[name=" not in texto and "sale_price" not in texto, fichero.name


def test_una_copia_local_sustituye_a_la_incluida(temp_paths):
    from lot_bot.wallapop.browser.config import local_config_path

    destino = local_config_path()
    destino.write_text("verificado: true\nurls: {inicio: 'https://es.wallapop.com/'}\n", encoding="utf-8")
    assert load_site_config().verified is True


# ---------------------------------------------------------------------------
# Publicación
# ---------------------------------------------------------------------------
def test_publicar_rellena_el_formulario_y_devuelve_la_url(profiles, tmp_path):
    world = {
        "logged_in": True,
        "item_url": "https://es.wallapop.com/item/canape-canape-123456789",
    }
    service, launcher = make_service(profiles, world, tmp_path)
    result = service.create_item("acc-1", draft(tmp_path))
    assert result.success
    assert result.data["url"] == world["item_url"]
    assert result.item_id == "canape-canape-123456789"
    log = launcher.pages[0].log
    escritos = {entry[2] for entry in log if entry[0] == "fill"}
    assert "Canapé canapé canapé canapé canapé canapé" in escritos
    assert "GRAN OFERTA" in escritos
    assert "11,44" in escritos  # formato de precio español
    assert any(entry[0] == "files" for entry in log)
    assert ("option", "Hogar y jardín") in log
    assert ("option", "Nuevo") in log


def test_si_wallapop_no_muestra_la_url_se_dice(profiles, tmp_path):
    service, _ = make_service(profiles, {"logged_in": True}, tmp_path)
    result = service.create_item("acc-1", draft(tmp_path))
    assert result.success and result.data["url"] is None
    assert "no ha mostrado la dirección" in result.message


def test_sin_sesion_no_se_publica(profiles, tmp_path):
    service, _ = make_service(profiles, {"logged_in": False}, tmp_path)
    with pytest.raises(AuthenticationError):
        service.create_item("acc-1", draft(tmp_path))


def test_cuenta_no_conectada_no_abre_el_navegador(profiles, tmp_path):
    service, launcher = make_service(profiles, {"logged_in": True}, tmp_path, connected=False)
    with pytest.raises(AuthenticationError):
        service.create_item("acc-1", draft(tmp_path))
    assert launcher.opened == []


def test_una_verificacion_detiene_la_publicacion(profiles, tmp_path):
    service, launcher = make_service(
        profiles, {"logged_in": True, "verification": True}, tmp_path
    )
    with pytest.raises(VerificationRequiredError):
        service.create_item("acc-1", draft(tmp_path))
    log = launcher.pages[0].log
    assert not any(entry[0] in ("fill", "click") for entry in log)  # nada automático


def test_si_la_web_cambia_se_indica_el_paso_y_se_guarda_captura(profiles, tmp_path):
    world = {"logged_in": True, "missing_steps": {"Precio"}}
    service, _ = make_service(profiles, world, tmp_path)
    service.site.timeout_ms = 0
    with pytest.raises(BrowserStepError) as info:
        service.create_item("acc-1", draft(tmp_path))
    assert info.value.step == "Precio"
    assert info.value.screenshot and Path(info.value.screenshot).is_file()
    assert "wallapop_browser.yaml" in info.value.user_message
    service.site.timeout_ms = SITE.timeout_ms


def test_solo_declara_lo_que_hace_de_verdad(profiles, tmp_path):
    service, _ = make_service(profiles, {"logged_in": True}, tmp_path)
    assert service.capabilities() == {Capability.ACCOUNT_PROFILE, Capability.CREATE_ITEM}
    for llamada in (
        lambda: service.list_items("acc-1"),
        lambda: service.update_item_price("acc-1", "x", 10),
        lambda: service.delete_item("acc-1", "x"),
        lambda: service.send_message("acc-1", "c", "hola"),
    ):
        with pytest.raises(NotAvailableWithCurrentAPIError):
            llamada()


# ---------------------------------------------------------------------------
# Aislamiento de sesiones
# ---------------------------------------------------------------------------
def test_cada_cuenta_usa_su_propio_perfil(profiles, tmp_path):
    service, launcher = make_service(profiles, {"logged_in": True}, tmp_path)
    service.create_item("acc-1", draft(tmp_path))
    service.create_item("acc-2", draft(tmp_path))
    assert launcher.opened[0] != launcher.opened[1]
    assert launcher.opened[0].name == "acc-1" and launcher.opened[1].name == "acc-2"
    assert launcher.opened[0].parent == launcher.opened[1].parent == profiles.root


def test_borrar_una_sesion_no_toca_las_demas(profiles):
    for ref in ("acc-1", "acc-2"):
        (profiles.profile_dir(ref) / "Cookies").write_text("x")
    assert profiles.delete("acc-1")
    assert not profiles.exists("acc-1")
    assert profiles.exists("acc-2")


@pytest.mark.parametrize("ref", ["../otra", "a/b", "", "x" * 80, "..", "c:\\temp"])
def test_referencias_de_cuenta_peligrosas_se_rechazan(profiles, ref):
    with pytest.raises(ValueError):
        profiles.profile_dir(ref)


def test_no_se_guardan_sesiones_dentro_de_un_repositorio_git(tmp_path):
    repo = tmp_path / "proyecto"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(UnsafeProfileLocation):
        BrowserProfileStore(repo / "datos" / "browser_profiles")


def test_desconectar_y_eliminar_borran_la_sesion_guardada(database, profiles, secret_box):
    from lot_bot.wallapop.account_manager import AccountManager
    from lot_bot.wallapop.auth.base import AuthCredential, AuthKind

    manager = AccountManager(database, secret_box)
    manager.set_browser_profiles(profiles)
    for alias in ("Uno", "Dos"):
        info = manager.add_account(alias, internal_ref=f"acc-{alias.lower()}")
        (profiles.profile_dir(info.internal_ref) / "Cookies").write_text("x")
        manager.store_credential(
            info.internal_ref,
            AuthCredential(kind=AuthKind.BROWSER_SESSION, metadata={"account_ref": info.internal_ref}),
        )
    manager.disconnect("acc-uno")
    assert not profiles.exists("acc-uno") and profiles.exists("acc-dos")
    manager.remove_account("acc-dos")
    assert not profiles.exists("acc-dos")


# ---------------------------------------------------------------------------
# Conexión de la cuenta
# ---------------------------------------------------------------------------
def test_conectar_espera_al_usuario_y_no_guarda_contrasena(profiles, tmp_path):
    world = {"logged_in": True, "user_name": "Ana"}
    service, _ = make_service(profiles, world, tmp_path)
    service.site.user_name = ["#nombre"]
    world["visible"] = {"#nombre"}
    method = BrowserSessionAuthMethod(service, login_timeout=5)
    result = method.wait_for_login("acc-1")
    assert result.ok and result.login == "Ana"
    outcome = method.authenticate("acc-1", login_detected=True, login=result.login)
    assert outcome.success
    credential = outcome.credential
    assert credential.kind.value == "browser_session"
    assert credential.headers == {} and credential.cookies == {}  # nada sensible
    assert "password" not in str(credential.to_storage()).lower()
    assert "uso personal autorizado" in credential.metadata["uso"]
    service.site.user_name = []


def test_si_no_inicia_sesion_no_se_conecta(profiles, tmp_path):
    service, _ = make_service(profiles, {"logged_in": False}, tmp_path)
    method = BrowserSessionAuthMethod(service, login_timeout=0.01)
    assert not method.wait_for_login("acc-1").ok


def test_backend_navegador_desde_la_configuracion(database, temp_paths):
    from lot_bot.config.settings import Settings
    from lot_bot.wallapop.account_manager import AccountManager
    from lot_bot.wallapop.factory import build_backend

    manager = AccountManager(database)
    backend = build_backend(Settings(), manager, "navegador", launcher=FakeLauncher({}))
    assert not backend.demo
    assert isinstance(backend.service, BrowserWallapopService)
    assert "uso personal autorizado" in backend.reason
    # La elección de la pantalla manda sobre LOT_BOT_DEMO_MODE=true del .env
    # (el .env de ejemplo lo trae así).
    elegido = build_backend(
        Settings(LOT_BOT_DEMO_MODE=True), manager, "navegador", launcher=FakeLauncher({})
    )
    assert not elegido.demo
    assert build_backend(Settings(LOT_BOT_DEMO_MODE=True), manager, "demo").demo


def test_sin_eleccion_se_queda_en_demo(database, temp_paths):
    from lot_bot.config.settings import Settings
    from lot_bot.wallapop.account_manager import AccountManager
    from lot_bot.wallapop.factory import build_backend

    assert build_backend(Settings(), AccountManager(database), "").demo
