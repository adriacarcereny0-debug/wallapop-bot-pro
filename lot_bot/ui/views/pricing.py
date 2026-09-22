"""Pantalla de precios: analisis y cambios en lote."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
)

from lot_bot.publishing.listings import ListingFilter
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import (
    Card,
    SectionTitle,
    StatCard,
    Toolbar,
    ask_confirmation,
    build_table,
    fill_table,
    info_box,
)


class PricingView(BaseView):
    title = "Precios"
    subtitle = "Analiza tus precios y cámbialos en lote con confirmación"

    def build(self) -> None:
        self.add_header_button("Actualizar", self.refresh)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.avg_card = StatCard("Precio medio")
        self.median_card = StatCard("Mediana")
        self.min_card = StatCard("Mínimo")
        self.max_card = StatCard("Máximo")
        for card in (self.avg_card, self.median_card, self.min_card, self.max_card):
            stats_row.addWidget(card)
        self.body.addLayout(stats_row)

        toolbar = Toolbar()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar anuncios por texto…")
        self.search.returnPressed.connect(self.refresh)
        toolbar.add(self.search, 1)
        self.size_filter = QLineEdit()
        self.size_filter.setPlaceholderText("Medida (135x190)")
        self.size_filter.setMaximumWidth(160)
        self.size_filter.returnPressed.connect(self.refresh)
        toolbar.add(self.size_filter)
        self.account_filter = QComboBox()
        self.account_filter.currentIndexChanged.connect(self.refresh)
        toolbar.add(self.account_filter)
        self.body.addWidget(toolbar)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        table_card = Card()
        table_card.add(SectionTitle("Anuncios afectados por el filtro"))
        self.table = build_table(["Cuenta", "Título", "Medida", "Precio"])
        table_card.add(self.table)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.01, 100000)
        self.price_spin.setDecimals(2)
        self.price_spin.setSuffix(" €")
        self.price_spin.setValue(269.00)
        actions.addWidget(QLabel("Nuevo precio:"))
        actions.addWidget(self.price_spin)
        self.apply_button = QPushButton("Aplicar a todos los del filtro")
        self.apply_button.setObjectName("Primary")
        self.apply_button.clicked.connect(self._apply_bulk)
        actions.addWidget(self.apply_button)
        actions.addStretch(1)
        table_card.body.addLayout(actions)
        columns.addWidget(table_card, 3)

        analysis_card = Card()
        analysis_card.add(SectionTitle("Análisis de mercado"))
        self.analysis = QTextEdit()
        self.analysis.setReadOnly(True)
        analysis_card.add(self.analysis)
        analyze_button = QPushButton("Analizar mercado")
        analyze_button.clicked.connect(self._analyze_market)
        analysis_card.add(analyze_button)
        columns.addWidget(analysis_card, 2)

        self.body.addLayout(columns, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        current = self.account_filter.currentData()
        self.account_filter.blockSignals(True)
        self.account_filter.clear()
        self.account_filter.addItem("Todas las cuentas", None)
        for account in self.app.accounts.list_accounts():
            self.account_filter.addItem(account.alias, account.internal_ref)
        index = self.account_filter.findData(current)
        if index >= 0:
            self.account_filter.setCurrentIndex(index)
        self.account_filter.blockSignals(False)

        listings = self.app.listings.search(self._criteria())
        self._listings = listings
        fill_table(
            self.table,
            [
                [
                    v.account_alias,
                    v.title,
                    v.attributes.get("medida", "—"),
                    f"{v.price:.2f} €" if v.price else "—",
                ]
                for v in listings
            ],
            row_data=[v.id for v in listings],
        )

        from lot_bot.market.service import PriceStats

        stats = PriceStats.from_prices([v.price for v in listings if v.price])
        if stats:
            self.avg_card.update_value(f"{stats.average:.2f} €", f"{stats.count} anuncios")
            self.median_card.update_value(f"{stats.median:.2f} €")
            self.min_card.update_value(f"{stats.minimum:.2f} €")
            self.max_card.update_value(f"{stats.maximum:.2f} €")
        else:
            for card in (self.avg_card, self.median_card, self.min_card, self.max_card):
                card.update_value("—")
        self.header.set_subtitle(f"{len(listings)} anuncio(s) coinciden con el filtro")
        self.apply_button.setEnabled(bool(listings))

    def _criteria(self) -> ListingFilter:
        return ListingFilter(
            text=self.search.text().strip() or None,
            size=self.size_filter.text().strip() or None,
            account_ref=self.account_filter.currentData(),
            limit=1000,
        )

    # ------------------------------------------------------------------
    def _apply_bulk(self) -> None:
        listings = getattr(self, "_listings", [])
        if not listings:
            return
        price = self.price_spin.value()
        by_account: dict[str, int] = {}
        for view in listings:
            by_account[view.account_alias] = by_account.get(view.account_alias, 0) + 1
        detail = "\n".join(f"• {alias}: {count} anuncio(s)" for alias, count in by_account.items())
        if not ask_confirmation(
            self,
            "Confirmar cambio de precio",
            f"Voy a modificar {len(listings)} anuncio(s):\n\n{detail}\n\n"
            f"Nuevo precio: {price:.2f} €",
        ):
            return

        ids = [v.id for v in listings]

        def success(outcomes):
            done = sum(1 for o in outcomes if o.success)
            failed = [o for o in outcomes if not o.success]
            message = f"Precio actualizado en {done} de {len(outcomes)} anuncio(s)."
            if failed:
                message += "\n\nErrores:\n" + "\n".join(f"• {o.account_ref}: {o.message}" for o in failed)
            info_box(self, "Resultado", message)

        self.run_task(
            lambda: self.app.publishing.update_prices(ids, price, confirmed=True, actor="usuario"),
            on_success=success,
            on_done=self.refresh,
        )

    def _analyze_market(self) -> None:
        query = self.search.text().strip() or "canapé"

        def success(analysis):
            text = analysis.summary()
            if not analysis.has_external_data:
                text += (
                    "\n\nNota: no hay ninguna fuente de mercado externa autorizada. "
                    "El análisis se basa solo en tus propios anuncios."
                )
            self.analysis.setPlainText(text)

        self.run_task(
            lambda: self.app.market.analyze(
                query,
                account_ref=self.account_filter.currentData(),
                size=self.size_filter.text().strip() or None,
            ),
            on_success=success,
        )
