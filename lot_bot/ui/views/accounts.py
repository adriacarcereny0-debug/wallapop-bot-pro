"""Pantalla de cuentas de Wallapop."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QPushButton

from lot_bot.ui import theme
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import (
    Card,
    SectionTitle,
    build_table,
    fill_table,
    info_box,
    selected_row_data,
    show_error,
)
from lot_bot.ui.widgets.common import ask_confirmation


class AccountsView(BaseView):
    title = "Cuentas Wallapop"
    subtitle = "Cada cuenta está aislada: nunca se mezclan anuncios ni mensajes"

    def build(self) -> None:
        self.add_header_button("Añadir cuenta", self._add_account, primary=True)
        self.add_header_button("Actualizar", self.refresh)

        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.body.addWidget(self.notice)

        card = Card()
        card.add(SectionTitle("Cuentas configuradas"))
        self.table = build_table(
            ["Cuenta", "Referencia", "Estado", "Usuario", "Última sincronización", "Permisos"]
        )
        self.table.itemSelectionChanged.connect(self._update_buttons)
        card.add(self.table)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.connect_button = QPushButton("Conectar")
        self.connect_button.setObjectName("Primary")
        self.connect_button.clicked.connect(self._connect)
        actions.addWidget(self.connect_button)

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
        if backend.demo:
            self.notice.setText(
                f"<b style='color:{theme.WARNING}'>MODO DEMO.</b> {backend.reason} "
                f"Las cuentas que ves son simuladas."
            )
        else:
            self.notice.setText(
                f"<b style='color:{theme.SUCCESS}'>Integración real activa.</b> "
                f"Al conectar una cuenta se abrirá el navegador en Wallapop. "
                f"LOT Bot no guarda tu contraseña: solo un token cifrado."
            )

        accounts = self.app.accounts.list_accounts()
        self._accounts = accounts
        fill_table(
            self.table,
            [
                [
                    a.alias,
                    a.internal_ref,
                    a.status_label,
                    a.wallapop_login or "—",
                    a.last_sync_at.strftime("%d/%m/%Y %H:%M") if a.last_sync_at else "nunca",
                    ", ".join(a.scopes) if a.scopes else ("DEMO" if a.is_demo else "—"),
                ]
                for a in accounts
            ],
            row_data=[a.internal_ref for a in accounts],
            colorizer=lambda row, col, value: (
                theme.STATUS_COLORS.get(accounts[row].status.value)
                if col == 2 and row < len(accounts)
                else None
            ),
        )
        self._update_buttons()

    # ------------------------------------------------------------------
    def _selected_ref(self) -> str | None:
        refs = selected_row_data(self.table)
        return refs[0] if refs else None

    def _update_buttons(self) -> None:
        ref = self._selected_ref()
        has_selection = ref is not None
        for button in (
            self.connect_button,
            self.disconnect_button,
            self.sync_button,
            self.rename_button,
            self.remove_button,
        ):
            button.setEnabled(has_selection)
        if self.app.demo_mode:
            self.connect_button.setEnabled(False)
            self.connect_button.setToolTip(
                "En modo DEMO las cuentas ya están conectadas de forma simulada."
            )

    # ------------------------------------------------------------------
    def _add_account(self) -> None:
        alias, accepted = QInputDialog.getText(
            self, "Añadir cuenta", "Nombre con el que identificar la cuenta:"
        )
        if not accepted or not alias.strip():
            return
        try:
            account = self.app.accounts.add_account(alias.strip(), is_demo=self.app.demo_mode)
        except ValueError as exc:
            show_error(self, str(exc))
            return
        self.app.audit.record_success("Alta de cuenta", target=account.alias)
        self.refresh()
        info_box(
            self,
            "Cuenta añadida",
            f"«{account.alias}» creada con la referencia interna {account.internal_ref}.\n\n"
            + (
                "Estás en modo DEMO: la cuenta funciona con datos simulados."
                if self.app.demo_mode
                else "Selecciónala y pulsa «Conectar» para autorizarla en Wallapop."
            ),
        )

    def _connect(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        if self.app.demo_mode:
            info_box(
                self,
                "Modo DEMO",
                "En modo DEMO no hay conexión real con Wallapop.\n\n"
                "Para conectar de verdad, configura las credenciales oficiales y el "
                "fichero de endpoints en Ajustes.",
            )
            return

        self.connect_button.setEnabled(False)
        self.connect_button.setText("Esperando al navegador…")

        def done(_=None):
            self.connect_button.setText("Conectar")
            self.refresh()

        self.run_task(
            lambda: self.app.accounts.connect_interactive(ref),
            on_success=lambda account: self.app.audit.record_success(
                "Conexión de cuenta", account_ref=ref, target=account.alias
            ),
            on_done=done,
        )

    def _disconnect(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        if not ask_confirmation(
            self,
            "Desconectar cuenta",
            f"Se borrarán los tokens guardados de «{ref}».\n"
            f"Los anuncios seguirán en Wallapop; solo se corta el acceso de LOT Bot.",
        ):
            return
        self.app.accounts.disconnect(ref)
        self.app.audit.record_success("Desconexión de cuenta", account_ref=ref)
        self.refresh()

    def _sync(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        self.sync_button.setEnabled(False)
        self.sync_button.setText("Sincronizando…")

        def work():
            result = self.app.listings.sync_account(ref)
            if self.app.messages.messaging_available:
                self.app.messages.sync_account(ref)
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
        ref = self._selected_ref()
        if ref is None:
            return
        alias, accepted = QInputDialog.getText(self, "Renombrar cuenta", "Nuevo nombre:")
        if accepted and alias.strip():
            self.app.accounts.rename_account(ref, alias.strip())
            self.refresh()

    def _remove(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        if not ask_confirmation(
            self,
            "Eliminar cuenta",
            f"Se eliminará la cuenta «{ref}» de LOT Bot junto con sus anuncios y "
            f"mensajes guardados en local.\n\n"
            f"Los anuncios publicados en Wallapop NO se tocan.",
            destructive=True,
        ):
            return
        self.app.accounts.remove_account(ref)
        self.app.audit.record_success("Baja de cuenta", target=ref)
        self.refresh()
