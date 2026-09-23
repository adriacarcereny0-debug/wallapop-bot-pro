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
        self.add_header_button("Añadir cuenta", self._add_account, primary=True)
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
    def _disconnect(self) -> None:
        account = self._selected()
        if account is None:
            return
        if not ask_confirmation(
            self,
            "Desconectar cuenta",
            f"Se borrará la credencial guardada de «{account.alias}».\n\n"
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
