"""Pantalla «Cuentas de Wallapop».

Alta, conexion, reautenticacion y baja de cuentas. El mecanismo de conexion es
el que Wallapop haya autorizado; esta pantalla no asume ninguno y, cuando falta
algun dato tecnico, lo dice en lugar de pedir una credencial inexistente.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QPushButton

from lot_bot.ui import theme
from lot_bot.ui.views.account_wizard import (
    AddAccountDialog,
    DelegatedCredentialDialog,
    MissingAccessDialog,
)
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import (
    Card,
    SectionTitle,
    ask_confirmation,
    build_table,
    fill_table,
    info_box,
    selected_row_data,
    show_error,
)
from lot_bot.wallapop.auth.base import AuthKind


class AccountsView(BaseView):
    title = "Cuentas de Wallapop"
    subtitle = "Cada cuenta está aislada: nunca se mezclan anuncios ni mensajes"

    def build(self) -> None:
        self.add_header_button("Añadir cuenta Wallapop", self._add_browser_account, primary=True)
        self.add_header_button("Añadir cuenta", self._add_account)
        self.add_header_button("Actualizar", self.refresh)

        # --- Estado del acceso ---
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.body.addWidget(self.notice)

        self.details_button = QPushButton("Ver qué falta para conectar con Wallapop")
        self.details_button.setObjectName("Ghost")
        self.details_button.clicked.connect(self._show_missing)
        self.body.addWidget(self.details_button)

        # --- Tabla ---
        card = Card()
        card.add(SectionTitle("Cuentas configuradas"))
        self.table = build_table(
            [
                "Cuenta",
                "Referencia",
                "Estado",
                "Mecanismo",
                "Usuario",
                "Última sincronización",
            ]
        )
        self.table.itemSelectionChanged.connect(self._update_buttons)
        card.add(self.table)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.connect_button = QPushButton("Conectar")
        self.connect_button.setObjectName("Primary")
        self.connect_button.clicked.connect(self._connect)
        actions.addWidget(self.connect_button)

        self.reauth_button = QPushButton("Volver a autenticar")
        self.reauth_button.clicked.connect(self._reauthenticate)
        actions.addWidget(self.reauth_button)

        self.disconnect_button = QPushButton("Desconectar")
        self.disconnect_button.clicked.connect(self._disconnect)
        actions.addWidget(self.disconnect_button)

        self.sync_button = QPushButton("Sincronizar")
        self.sync_button.clicked.connect(self._sync)
        actions.addWidget(self.sync_button)

        self.browser_button = QPushButton("Abrir navegador")
        self.browser_button.setToolTip(
            "Abre el navegador de esta cuenta para completar a mano una verificación "
            "que pida Wallapop."
        )
        self.browser_button.clicked.connect(self._open_browser)
        actions.addWidget(self.browser_button)

        self.rename_button = QPushButton("Renombrar")
        self.rename_button.clicked.connect(self._rename)
        actions.addWidget(self.rename_button)

        actions.addStretch(1)
        self.remove_button = QPushButton("Eliminar cuenta")
        self.remove_button.setObjectName("Danger")
        self.remove_button.clicked.connect(self._remove)
        actions.addWidget(self.remove_button)
        card.body.addLayout(actions)

        self.body.addWidget(card, 1)
        self._update_buttons()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        backend = self.app.backend
        method = self.app.auth_method

        if backend.demo:
            self.notice.setText(
                f"<b style='color:{theme.WARNING}'>MODO DEMO</b> — {backend.reason} "
                f"Las cuentas que ves son simuladas y nada afecta a Wallapop."
            )
            self.details_button.setVisible(True)
        elif self.app.browser_auth is not None:
            self.notice.setText(
                f"<b style='color:{theme.SUCCESS}'>WALLAPOP (NAVEGADOR)</b> — las cuentas "
                f"conectadas aquí son cuentas autorizadas para el uso personal del titular de "
                f"LOT Bot. No es una integración oficial de Wallapop. Tú inicias sesión en el "
                f"navegador; LOT Bot no ve ni guarda tu contraseña y cada cuenta tiene su "
                f"propio perfil de navegador aislado."
            )
            self.details_button.setVisible(False)
        else:
            self.notice.setText(
                f"<b style='color:{theme.SUCCESS}'>WALLAPOP REAL</b> — acceso mediante "
                f"«{method.describe()}». LOT Bot no guarda tu contraseña: solo la "
                f"credencial de acceso, cifrada."
            )
            self.details_button.setVisible(bool(backend.missing))

        accounts = self.app.accounts.list_accounts()
        self._accounts = accounts
        demo_mode = self.app.demo_mode

        fill_table(
            self.table,
            [
                [
                    a.alias,
                    a.internal_ref,
                    self._status_text(a, demo_mode),
                    a.auth_method_label,
                    a.wallapop_login or "—",
                    a.last_sync_at.strftime("%d/%m/%Y %H:%M") if a.last_sync_at else "nunca",
                ]
                for a in accounts
            ],
            row_data=[a.internal_ref for a in accounts],
            colorizer=lambda row, col, value: (
                self._status_color(accounts[row], demo_mode)
                if col == 2 and row < len(accounts)
                else None
            ),
        )
        connected = sum(1 for a in accounts if self._really_connected(a, demo_mode))
        self.header.set_subtitle(
            f"{len(accounts)} cuenta(s) · {connected} conectada(s) · "
            f"cada una con sus propios anuncios, mensajes y automatizaciones"
        )
        self._update_buttons()

    # ------------------------------------------------------------------
    @staticmethod
    def _really_connected(account, demo_mode: bool) -> bool:
        """En modo real, una cuenta de demostración NO está conectada.

        Es la regla de no mostrar jamás algo DEMO como si fuera Wallapop real.
        """
        if account.is_demo and not demo_mode:
            return False
        return account.is_connected

    @staticmethod
    def _status_text(account, demo_mode: bool) -> str:
        if account.is_demo and not demo_mode:
            return "Solo demostración"
        return account.status_label

    @staticmethod
    def _status_color(account, demo_mode: bool) -> str:
        if account.is_demo and not demo_mode:
            return theme.WARNING
        return theme.STATUS_COLORS.get(account.status.value, theme.TEXT_MUTED)

    # ------------------------------------------------------------------
    def _selected(self):
        refs = selected_row_data(self.table)
        if not refs:
            return None
        return next((a for a in self._accounts if a.internal_ref == refs[0]), None)

    def _update_buttons(self) -> None:
        account = self._selected()
        has = account is not None
        for button in (
            self.disconnect_button,
            self.sync_button,
            self.rename_button,
            self.remove_button,
        ):
            button.setEnabled(has)

        self.browser_button.setEnabled(
            has
            and self.app.browser_auth is not None
            and account.auth_method == AuthKind.BROWSER_SESSION.value
        )
        method_ready = self.app.auth_method.is_ready
        conectada = bool(account) and self._really_connected(account, self.app.demo_mode)
        self.connect_button.setEnabled(has and method_ready and not conectada)
        self.reauth_button.setEnabled(has and method_ready and conectada)

        if not method_ready:
            tip = (
                "El mecanismo de acceso autorizado todavía no tiene todos los datos "
                "técnicos. Pulsa «Ver qué falta para conectar con Wallapop»."
            )
            self.connect_button.setToolTip(tip)
            self.reauth_button.setToolTip(tip)
        else:
            self.connect_button.setToolTip("")
            self.reauth_button.setToolTip("")

    # ------------------------------------------------------------------
    def _add_account(self) -> None:
        dialog = AddAccountDialog(self.app, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        alias = dialog.account_alias()
        if not alias:
            show_error(self, "La cuenta necesita un nombre.")
            return
        try:
            account = self.app.accounts.add_account(alias, is_demo=self.app.demo_mode)
        except ValueError as exc:
            show_error(self, str(exc))
            return
        self.app.audit.record_success("Alta de cuenta", target=account.alias)
        self.refresh()

        if self.app.demo_mode:
            info_box(
                self,
                "Cuenta añadida",
                f"«{account.alias}» creada en modo demostración.\n\n"
                f"Funciona con datos simulados: no afecta a Wallapop.",
            )
        elif self.app.auth_method.is_ready:
            self._connect_account(account)
        else:
            self._show_missing()

    # ------------------------------------------------------------------
    def _connect(self) -> None:
        account = self._selected()
        if account is not None:
            self._connect_account(account)

    def _reauthenticate(self) -> None:
        account = self._selected()
        if account is None:
            return
        if not ask_confirmation(
            self,
            "Volver a autenticar",
            f"Se sustituirá la sesión guardada de «{account.alias}» por una nueva.\n\n"
            f"Tendrás que iniciar sesión otra vez en Wallapop.",
        ):
            return
        self._connect_account(account, reauth=True)

    def _connect_account(self, account, reauth: bool = False) -> None:
        """Lanza el mecanismo de acceso que corresponda."""
        method = self.app.auth_method
        if self.app.browser_auth is not None and not account.is_demo:
            self._browser_login(account, new=False)
            return

        if method.kind is AuthKind.DEMO and not self.app.demo_mode:
            self._show_missing()
            return

        context: dict = {}
        if method.kind is AuthKind.DELEGATED_CREDENTIAL:
            dialog = DelegatedCredentialDialog(
                account.alias,
                instructions=self.app.access_profile.auth.delegated.instructions,
                parent=self,
            )
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            context["credential"] = dialog.value()
        elif method.interactive:
            info_box(
                self,
                "Autenticación en Wallapop",
                "Se abrirá tu navegador en Wallapop.\n\n"
                "Inicia sesión con esta cuenta, completa los pasos de seguridad que "
                "Wallapop te pida y autoriza el acceso.\n\n"
                "LOT Bot no ve ni guarda tu contraseña.",
            )

        self.connect_button.setEnabled(False)
        self.connect_button.setText("Autenticando…")

        def work():
            if reauth:
                return self.app.accounts.reauthenticate(account.internal_ref, **context)
            return self.app.accounts.connect(account.internal_ref, **context)

        def success(outcome) -> None:
            if outcome.success:
                self.app.audit.record_success(
                    "Conexión de cuenta",
                    account_ref=account.internal_ref,
                    target=account.alias,
                    detail=method.describe(),
                )
                info_box(self, "Cuenta conectada", outcome.message)
            else:
                self.app.audit.record_error(
                    "Conexión de cuenta",
                    error=outcome.message,
                    account_ref=account.internal_ref,
                    target=account.alias,
                )
                if outcome.blocked_by_missing_data:
                    self._show_missing()
                else:
                    show_error(self, outcome.message)

        def done(_=None) -> None:
            self.connect_button.setText("Conectar")
            self.refresh()

        self.run_task(work, on_success=success, on_done=done)

    # ------------------------------------------------------------------
    # Integración por navegador
    # ------------------------------------------------------------------
    def _add_browser_account(self) -> None:
        if self.app.browser_auth is None:
            info_box(
                self,
                "Integración por navegador desactivada",
                "Para conectar tus cuentas de Wallapop, activa primero la integración en "
                "Configuración → Wallapop → «Integración mediante navegador».\n\n"
                "Mientras tanto LOT Bot funciona en modo demostración.",
            )
            return
        alias, accepted = QInputDialog.getText(
            self, "Añadir cuenta Wallapop", "Nombre para reconocer esta cuenta en LOT Bot:"
        )
        if not accepted or not alias.strip():
            return
        if not ask_confirmation(
            self,
            "Iniciar sesión en Wallapop",
            "Se abrirá una ventana del navegador con Wallapop.\n\n"
            "1. Inicia sesión tú mismo con la cuenta que quieras conectar.\n"
            "2. Si Wallapop te pide una verificación, complétala en esa ventana.\n"
            "3. Cuando LOT Bot detecte la sesión, te pedirá confirmación.\n\n"
            "LOT Bot no ve ni guarda tu contraseña. Esta conexión es para tu uso "
            "personal autorizado; no es una integración oficial de Wallapop.",
        ):
            return
        try:
            account = self.app.accounts.add_account(alias.strip(), is_demo=False)
        except ValueError as exc:
            show_error(self, str(exc))
            return
        self.app.audit.record_success("Alta de cuenta", target=account.alias, detail="navegador")
        self.refresh()
        self._browser_login(account, new=True)

    def _browser_login(self, account, *, new: bool) -> None:
        method = self.app.browser_auth
        self.connect_button.setEnabled(False)
        self.connect_button.setText("Esperando inicio de sesión…")

        def work():
            return method.wait_for_login(account.internal_ref)

        def success(result) -> None:
            if not result.ok:
                self.app.audit.record_error(
                    "Conexión de cuenta por navegador",
                    error=result.message,
                    account_ref=account.internal_ref,
                    target=account.alias,
                )
                if new:
                    self.app.accounts.remove_account(account.internal_ref)
                show_error(self, "No se ha conectado la cuenta.", result.message)
                return
            shown = f"«{result.login}»" if result.login else "la cuenta con la que has iniciado sesión"
            if not ask_confirmation(
                self,
                "Confirmar cuenta",
                f"Se ha detectado la sesión de {shown}.\n\n"
                f"¿Quieres conectarla a LOT Bot como «{account.alias}»?\n\n"
                f"Quedará guardada en un perfil de navegador exclusivo de esta cuenta, "
                f"en tu ordenador, para reutilizarla. Puedes borrarla con «Desconectar».",
            ):
                if new:
                    self.app.accounts.remove_account(account.internal_ref)
                else:
                    self.app.accounts.disconnect(account.internal_ref)
                self.app.audit.record_cancelled(
                    "Conexión de cuenta por navegador", target=account.alias
                )
                return
            outcome = self.app.accounts.connect(
                account.internal_ref, method=method, login_detected=True, login=result.login
            )
            if outcome.success:
                self.app.audit.record_success(
                    "Conexión de cuenta",
                    account_ref=account.internal_ref,
                    target=account.alias,
                    detail=method.describe(),
                )
                info_box(self, "Cuenta conectada", f"«{account.alias}» está conectada.")
            else:
                show_error(self, outcome.message)

        def done(_=None) -> None:
            self.connect_button.setText("Conectar")
            self.refresh()

        self.run_task(work, on_success=success, on_done=done)

    def _open_browser(self) -> None:
        account = self._selected()
        method = self.app.browser_auth
        if account is None or method is None:
            return
        info_box(
            self,
            "Abrir navegador",
            f"Se abrirá el navegador de «{account.alias}». Haz lo que Wallapop te pida "
            f"(por ejemplo, una verificación) y cierra la ventana al terminar.",
        )
        self.run_task(
            method.open_for_user,
            account.internal_ref,
            on_done=lambda *_: self.refresh(),
        )

    # ------------------------------------------------------------------
    def _disconnect(self) -> None:
        account = self._selected()
        if account is None:
            return
        if not ask_confirmation(
            self,
            "Desconectar cuenta",
            f"Se borrará la credencial guardada de «{account.alias}» (y, si se conectó "
            f"por navegador, su sesión y cookies guardadas).\n\n"
            f"Los anuncios seguirán en Wallapop; solo se corta el acceso de LOT Bot.",
        ):
            return
        self.app.accounts.disconnect(account.internal_ref)
        self.app.audit.record_success(
            "Desconexión de cuenta", account_ref=account.internal_ref, target=account.alias
        )
        self.refresh()

    def _sync(self) -> None:
        account = self._selected()
        if account is None:
            return
        self.sync_button.setEnabled(False)
        self.sync_button.setText("Sincronizando…")

        def work():
            result = self.app.listings.sync_account(account.internal_ref)
            if self.app.messages.messaging_available:
                self.app.messages.sync_account(account.internal_ref)
            return result

        def success(result):
            info_box(
                self,
                "Sincronización terminada",
                f"Nuevos: {result.get('nuevos', 0)} · "
                f"Actualizados: {result.get('actualizados', 0)} · "
                f"Retirados: {result.get('retirados', 0)}",
            )

        def done(_=None):
            self.sync_button.setText("Sincronizar")
            self.refresh()

        self.run_task(work, on_success=success, on_done=done)

    def _rename(self) -> None:
        account = self._selected()
        if account is None:
            return
        alias, accepted = QInputDialog.getText(
            self, "Renombrar cuenta", "Nuevo nombre:", text=account.alias
        )
        if accepted and alias.strip():
            self.app.accounts.rename_account(account.internal_ref, alias.strip())
            self.refresh()

    def _remove(self) -> None:
        account = self._selected()
        if account is None:
            return
        if not ask_confirmation(
            self,
            "Eliminar cuenta",
            f"Se eliminará «{account.alias}» de LOT Bot junto con sus anuncios y "
            f"mensajes guardados en local.\n\n"
            f"Los anuncios publicados en Wallapop NO se tocan.",
            destructive=True,
        ):
            return
        self.app.accounts.remove_account(account.internal_ref)
        self.app.audit.record_success("Baja de cuenta", target=account.alias)
        self.refresh()

    def _show_missing(self) -> None:
        MissingAccessDialog(self.app, self).exec()
