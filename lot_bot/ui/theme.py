"""Tema visual de LOT Bot: paleta e hoja de estilos Qt."""

from __future__ import annotations

# --- Paleta ---
BG = "#0f1216"
BG_ELEVATED = "#151a20"
CARD = "#171c23"
CARD_HOVER = "#1d232b"
BORDER = "#232a33"
BORDER_STRONG = "#2e3742"
TEXT = "#e8edf2"
TEXT_MUTED = "#95a3b3"
TEXT_FAINT = "#6b7887"

ACCENT = "#18b49a"
ACCENT_HOVER = "#1ecfb1"
ACCENT_PRESSED = "#12907c"
ACCENT_SOFT = "#123b36"

DANGER = "#e05260"
DANGER_HOVER = "#f06472"
WARNING = "#e0a33a"
SUCCESS = "#3fb56a"
INFO = "#4a9ad4"

FONT_FAMILY = "'Segoe UI', 'Inter', 'Helvetica Neue', Arial, sans-serif"


def stylesheet() -> str:
    """Hoja de estilos completa de la aplicacion."""
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}

QMainWindow, QDialog {{ background: {BG}; }}
QWidget#Content {{ background: {BG}; }}

/* ---------- Barra lateral ---------- */
QFrame#Sidebar {{
    background: {BG_ELEVATED};
    border-right: 1px solid {BORDER};
}}
QLabel#Brand {{
    font-size: 19px;
    font-weight: 700;
    color: {TEXT};
    padding: 20px 18px 2px 18px;
}}
QLabel#BrandSub {{
    font-size: 11px;
    color: {TEXT_FAINT};
    padding: 0 18px 14px 18px;
}}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 14px;
    margin: 2px 10px;
    color: {TEXT_MUTED};
    font-size: 13px;
}}
QPushButton#NavButton:hover {{ background: {CARD_HOVER}; color: {TEXT}; }}
QPushButton#NavButton:checked {{
    background: {ACCENT_SOFT};
    color: {ACCENT_HOVER};
    font-weight: 600;
}}

/* ---------- Cabecera ---------- */
QLabel#PageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#PageSubtitle {{ font-size: 12px; color: {TEXT_MUTED}; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; padding: 4px 0; }}

/* ---------- Tarjetas ---------- */
QFrame#Card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#StatCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#StatValue {{ font-size: 26px; font-weight: 700; color: {TEXT}; }}
QLabel#StatLabel {{ font-size: 11px; color: {TEXT_MUTED}; text-transform: uppercase; letter-spacing: 1px; }}
QLabel#StatHint {{ font-size: 11px; color: {TEXT_FAINT}; }}

/* ---------- Botones ---------- */
QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 8px 16px;
    color: {TEXT};
}}
QPushButton:hover {{ background: {CARD_HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BG_ELEVATED}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; background: {BG_ELEVATED}; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #05201b;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#Primary:disabled {{ background: {BORDER}; border-color: {BORDER}; color: {TEXT_FAINT}; }}

QPushButton#Danger {{
    background: transparent;
    border: 1px solid {DANGER};
    color: {DANGER};
    font-weight: 600;
}}
QPushButton#Danger:hover {{ background: {DANGER}; color: white; }}

QPushButton#Ghost {{ background: transparent; border: 1px solid {BORDER_STRONG}; }}
QPushButton#Ghost:hover {{ border-color: {ACCENT}; }}

/* ---------- Campos ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {ACCENT};
    selection-color: #05201b;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit::placeholder {{ color: {TEXT_FAINT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT_SOFT};
}}

/* ---------- Tablas ---------- */
QTableWidget, QTableView {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    alternate-background-color: {BG_ELEVATED};
}}
QHeaderView::section {{
    background: {BG_ELEVATED};
    border: none;
    border-bottom: 1px solid {BORDER_STRONG};
    padding: 9px 8px;
    color: {TEXT_MUTED};
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}}
QTableWidget::item {{ padding: 7px 6px; border-bottom: 1px solid {BORDER}; }}
QTableCornerButton::section {{ background: {BG_ELEVATED}; border: none; }}

/* ---------- Listas ---------- */
QListWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 4px;
}}
QListWidget::item {{ padding: 9px 10px; border-radius: 7px; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QListWidget::item:hover {{ background: {CARD_HOVER}; }}

/* ---------- Pestanas ---------- */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    padding: 9px 18px;
    color: {TEXT_MUTED};
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}

/* ---------- Barras de desplazamiento ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

/* ---------- Otros ---------- */
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background: {BG_ELEVATED};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{
    background: {BG_ELEVATED};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QToolTip {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 8px;
    color: {TEXT};
}}
QSplitter::handle {{ background: {BORDER}; }}
QMenu {{ background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 24px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QStatusBar {{ background: {BG_ELEVATED}; border-top: 1px solid {BORDER}; color: {TEXT_MUTED}; }}
"""


#: Colores por estado, para las etiquetas de la interfaz.
STATUS_COLORS: dict[str, str] = {
    "connected": SUCCESS,
    "disconnected": TEXT_FAINT,
    "expired": WARNING,
    "error": DANGER,
    "active": SUCCESS,
    "draft": TEXT_FAINT,
    "ready": INFO,
    "published": SUCCESS,
    "paused": WARNING,
    "archived": TEXT_FAINT,
    "removed": DANGER,
    "sold": INFO,
    "ok": SUCCESS,
    "failed": DANGER,
    "running": INFO,
    "idle": TEXT_FAINT,
}
