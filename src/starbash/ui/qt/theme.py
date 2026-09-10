"""A dark "observatory" theme for the Starbash GUI.

The styling is a single Qt stylesheet string plus a matching palette.  Keeping it
in one place makes the look consistent across every page and easy to tweak.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

__all__ = ["apply_theme", "STYLESHEET", "ACCENT"]

ACCENT = "#4aa3df"

STYLESHEET = f"""
* {{
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}}

QMainWindow, QWidget#CentralArea, QStackedWidget {{
    background-color: #1b1f24;
    color: #d7dde3;
}}

/* Left navigation rail ------------------------------------------------- */
QListWidget#NavRail {{
    background-color: #12161a;
    border: none;
    outline: 0;
    padding: 6px 4px;
}}
QListWidget#NavRail::item {{
    color: #9aa7b4;
    padding: 9px 12px;
    border-radius: 6px;
    margin: 2px 4px;
}}
QListWidget#NavRail::item:selected {{
    background-color: {ACCENT};
    color: #0b0e11;
    font-weight: 600;
}}
QListWidget#NavRail::item:hover:!selected {{
    background-color: #1e252b;
    color: #e6edf3;
}}

/* Headers and labels ---------------------------------------------------- */
QLabel#PageTitle {{
    font-size: 20px;
    font-weight: 600;
    color: #f2f6fa;
    padding: 6px 0;
}}
QLabel#PageSubtitle {{
    color: #8b98a5;
}}
QLabel#StatValue {{
    font-size: 26px;
    font-weight: 700;
    color: {ACCENT};
}}
QLabel#StatCaption {{
    color: #8b98a5;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 1px;
}}
QFrame#StatCard, QFrame#Card {{
    background-color: #222930;
    border: 1px solid #2c353d;
    border-radius: 10px;
}}
QFrame#Card > QLabel {{
    color: #d7dde3;
}}

/* Inputs ---------------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background-color: #141a1f;
    border: 1px solid #313b44;
    border-radius: 6px;
    padding: 5px 8px;
    color: #e6edf3;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QDateEdit:focus {{
    border: 1px solid {ACCENT};
}}
QPushButton {{
    background-color: #2b343d;
    border: 1px solid #37424c;
    border-radius: 6px;
    padding: 6px 14px;
    color: #e6edf3;
}}
QPushButton:hover {{ background-color: #354049; }}
QPushButton:pressed {{ background-color: #232b33; }}
QPushButton:disabled {{ color: #6a7681; background-color: #22282e; }}
QPushButton#Primary {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #0b0e11;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background-color: #61b2e8; }}
QPushButton#Danger {{ background-color: #8f3b3b; border-color: #8f3b3b; color: #fff; }}

/* Tables ---------------------------------------------------------------- */
QTableView, QTreeView, QListView {{
    background-color: #171d22;
    alternate-background-color: #1c2329;
    gridline-color: #262e36;
    border: 1px solid #2c353d;
    border-radius: 8px;
    selection-background-color: #29506b;
    selection-color: #ffffff;
}}
QHeaderView::section {{
    background-color: #222930;
    color: #9aa7b4;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #2c353d;
    border-bottom: 1px solid #2c353d;
}}
QTableView::item {{ padding: 3px 6px; }}

/* Progress + status ------------------------------------------------------ */
QProgressBar {{
    background-color: #141a1f;
    border: 1px solid #313b44;
    border-radius: 7px;
    text-align: center;
    color: #d7dde3;
    height: 14px;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 6px; }}
QStatusBar {{ background-color: #12161a; color: #8b98a5; }}
QToolTip {{
    background-color: #222930;
    color: #e6edf3;
    border: 1px solid {ACCENT};
}}

/* Log pane -------------------------------------------------------------- */
QPlainTextEdit#LogView {{
    background-color: #0f1317;
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 12px;
}}

/* Splitter -------------------------------------------------------------- */
QSplitter::handle {{ background-color: #2c353d; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the dark palette and stylesheet to ``app``."""
    app.setStyle("Fusion")

    palette = QPalette()
    window = QColor("#1b1f24")
    base = QColor("#171d22")
    text = QColor("#d7dde3")
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1c2329"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor("#2b343d"))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0b0e11"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#222930"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    app.setPalette(palette)

    app.setStyleSheet(STYLESHEET)
