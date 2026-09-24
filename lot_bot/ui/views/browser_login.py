"""Ventana que acompaña al usuario mientras inicia sesión en Wallapop.

El navegador permanece abierto todo el tiempo. La cuenta NO se conecta hasta
que el usuario pulsa «Ya he iniciado sesión» y LOT Bot comprueba de verdad
que hay una sesión válida.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from lot_bot.ui import theme
from lot_bot.wallapop.browser.auth import LoginSession

STATE_COLORS = {
    LoginSession.VERIFIED: theme.SUCCESS,
    LoginSession.NOT_LOGGED: theme.WARNING,
    LoginSession.VERIFICATION: theme.WARNING,
    LoginSession.UNKNOWN: theme.WARNING,
    LoginSession.ERROR: theme.DANGER,
    LoginSession.CLOSED: theme.DANGER,
}


class BrowserLoginDialog(QDialog):
    def __init__(self, session: LoginSession, alias: str, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(f"Conectar «{alias}»")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        steps = QLabel(
            "<b>1.</b> En la ventana del navegador que se ha abierto, inicia sesión en "
            "Wallapop con la cuenta que quieres conectar.<br>"
            "<b>2.</b> Si Wallapop te pide un código o una verificación, complétala allí.<br>"
            "<b>3.</b> Cuando veas tu cuenta en Wallapop, pulsa <b>«Ya he iniciado sesión»</b>.<br><br>"
            "LOT Bot no ve ni guarda tu contraseña. La cuenta solo se conecta si LOT Bot "
            "comprueba que la sesión es válida."
        )
        steps.setWordWrap(True)
        layout.addWidget(steps)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(48)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("Ya he iniciado sesión")
        self.check_button.setObjectName("Primary")
        self.check_button.setMinimumHeight(34)
        self.check_button.clicked.connect(self._check)
        buttons.addWidget(self.check_button)
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.setMinimumHeight(34)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._poll()

    def _check(self) -> None:
        self.check_button.setEnabled(False)
        self.session.request_check()

    def _poll(self) -> None:
        state = self.session.state
        color = STATE_COLORS.get(state, theme.TEXT_MUTED)
        self.status.setText(f"<span style='color:{color}'>{self.session.message}</span>")
        busy = state in (LoginSession.OPENING, LoginSession.CHECKING)
        finished = state in (LoginSession.CLOSED, LoginSession.ERROR)
        self.check_button.setEnabled(not busy and not finished)
        if state == LoginSession.VERIFIED:
            self._timer.stop()
            self.accept()

    def done(self, result: int) -> None:  # cierre del diálogo por cualquier vía
        self._timer.stop()
        super().done(result)
