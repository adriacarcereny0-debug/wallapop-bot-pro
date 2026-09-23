"""Pantalla de inventario."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPushButton, QSpinBox

from lot_bot.catalog.service import ProductFilter
from lot_bot.ui import theme
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import (
    Card,
    StatCard,
    Toolbar,
    ask_confirmation,
    build_table,
    fill_table,
    info_box,
    selected_row_data,
)


class InventoryView(BaseView):
    title = "Inventario"
    subtitle = "Unidades disponibles y productos publicados sin stock"

    def build(self) -> None:
        self.add_header_button("Actualizar", self.refresh)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.total_card = StatCard("Referencias")
        self.units_card = StatCard("Unidades totales")
        self.out_card = StatCard("Sin stock")
        self.risk_card = StatCard("Publicados sin stock")
        for card in (self.total_card, self.units_card, self.out_card, self.risk_card):
            stats_row.addWidget(card)
        self.body.addLayout(stats_row)

        toolbar = Toolbar()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar producto…")
        self.search.returnPressed.connect(self.refresh)
        toolbar.add(self.search, 1)
        self.only_stock = QCheckBox("Solo con stock")
        self.only_stock.stateChanged.connect(self.refresh)
        toolbar.add(self.only_stock)
        self.body.addWidget(toolbar)

        card = Card()
        self.table = build_table(["SKU", "Producto", "Medida", "Stock", "Estado", "Cuentas"])
        self.table.itemSelectionChanged.connect(self._on_selection)
        card.add(self.table)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.stock_spin = QSpinBox()
        self.stock_spin.setRange(0, 10000)
        self.stock_spin.setPrefix("Stock: ")
        actions.addWidget(self.stock_spin)
        self.apply_button = QPushButton("Aplicar a la selección")
        self.apply_button.setObjectName("Primary")
        self.apply_button.clicked.connect(self._apply_stock)
        self.apply_button.setEnabled(False)
        actions.addWidget(self.apply_button)
        actions.addStretch(1)
        card.body.addLayout(actions)
        self.body.addWidget(card, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        criteria = ProductFilter(
            text=self.search.text().strip() or None,
            only_in_stock=self.only_stock.isChecked(),
            limit=1000,
        )
        products = self.app.catalog.list_products(criteria)
        self._products = products
        fill_table(
            self.table,
            [
                [p.sku, p.name, p.size or "—", p.stock, p.status, len(p.accounts)]
                for p in products
            ],
            row_data=[p.id for p in products],
            colorizer=lambda row, col, value: (
                theme.DANGER if col == 3 and isinstance(value, int) and value <= 0 else None
            ),
        )

        all_products = self.app.catalog.list_products(ProductFilter(limit=5000))
        units = sum(p.stock for p in all_products)
        out_of_stock = [p for p in all_products if p.stock <= 0]
        published_without_stock = [p for p in out_of_stock if p.status == "published"]
        self.total_card.update_value(len(all_products))
        self.units_card.update_value(units)
        self.out_card.update_value(len(out_of_stock))
        self.risk_card.update_value(
            len(published_without_stock),
            "revisa estos anuncios" if published_without_stock else "todo correcto",
        )
        self._on_selection()

    def _on_selection(self) -> None:
        self.apply_button.setEnabled(bool(selected_row_data(self.table)))

    def _apply_stock(self) -> None:
        ids = [int(v) for v in selected_row_data(self.table)]
        if not ids:
            return
        value = self.stock_spin.value()
        names = [p.sku for p in self._products if p.id in ids]
        if not ask_confirmation(
            self,
            "Cambiar inventario",
            f"Voy a poner el stock de {len(ids)} producto(s) a {value} unidades:\n\n"
            + "\n".join(f"• {n}" for n in names[:20])
            + ("\n…" if len(names) > 20 else ""),
        ):
            return
        for product_id in ids:
            self.app.catalog.update_stock(product_id, value)
        self.app.audit.record_success(
            "Actualización de inventario", detail=f"{len(ids)} producto(s) a {value} unidades"
        )
        info_box(self, "Inventario", f"{len(ids)} producto(s) actualizados a {value} unidades.")
        self.refresh()
