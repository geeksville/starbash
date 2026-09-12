"""A dark "observatory" theme for the Starbash GUI.

The styling is a single Qt stylesheet string plus a matching palette.  Keeping it
in one place makes the look consistent across every page and easy to tweak.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

__all__ = [
    "apply_theme",
    "checkmark_path",
    "load_app_icon",
    "STYLESHEET",
    "ACCENT",
    "APP_ICON_NAME",
    "CHECKMARK_NAME",
]

ACCENT = "#4aa3df"

#: Application icon, shipped inside the package (``src/starbash/assets/``).
APP_ICON_NAME = "icon.png"
#: Tick glyph drawn inside a checked box, shipped alongside the icon.
CHECKMARK_NAME = "check.png"


def checkmark_path() -> str | None:
    """Filesystem path to the packaged tick glyph, or ``None`` if it is unavailable.

    Qt stylesheets can only reference an image by path, so this is best-effort: an
    install where the asset has no real path (a zipped wheel) simply falls back to
    the solid accent fill for a checked box.
    """
    try:
        asset = resources.files("starbash.assets").joinpath(CHECKMARK_NAME)
        path = Path(str(asset))
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None
    return path.as_posix() if path.is_file() else None


_checkmark = checkmark_path()
#: ``image:`` declaration for a checked box, empty when the glyph cannot be found.
_CHECK_IMAGE = "" if _checkmark is None else f'image: url("{_checkmark}");'


def load_app_icon() -> QIcon:
    """Return the Starbash application icon from the packaged assets.

    The bytes are read through :mod:`importlib.resources` and decoded with
    :class:`QPixmap`, so this works even for an installed wheel/zip where the asset
    has no real filesystem path.  A missing or unreadable asset yields a null
    ``QIcon`` (i.e. no icon) rather than an exception - a packaging mistake must
    never stop the app from starting.
    """
    try:
        data = resources.files("starbash.assets").joinpath(APP_ICON_NAME).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return QIcon()

    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        return QIcon()
    return QIcon(pixmap)


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
/* A selected target's output directory, shown in a subtle inset box so the long
   path gets breathing room instead of sitting flush against the pane edges. */
QLabel#PathLabel {{
    color: #8b98a5;
    background-color: #141a1f;
    border: 1px solid #2c353d;
    border-radius: 6px;
    padding: 6px 10px;
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
/* Tree rows need their own vertical padding.  The stage checkbox indicator is
   16px tall (see *Checkboxes* below) while an unpadded tree row is only about
   that tall, so in the Targets page's stage list the boxes of consecutive
   stages ended up visually touching.  Horizontal padding stays 0 so the
   indentation and the checkbox inset are exactly as before. */
QTreeView::item {{ padding: 4px 0; }}

/* The per-parameter option editor on the Targets page --------------------- */
QGroupBox#OptionEditor {{
    border: 1px solid #2c353d;
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px;
}}
QGroupBox#OptionEditor::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
    color: #9aa7b4;
}}
QTabWidget::pane {{
    border: 1px solid #2c353d;
    border-radius: 6px;
    top: -1px;
    background-color: #171d22;
    padding: 8px;
}}
QTabBar::tab {{
    background-color: #222930;
    color: #9aa7b4;
    border: 1px solid #2c353d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 14px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {ACCENT};
    color: #0b0e11;
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background-color: #2b343d;
    color: #e6edf3;
}}

/* Checkboxes ------------------------------------------------------------- */
/* The dark palette makes Fusion's native indicator a dark box on a dark panel,
   i.e. nearly invisible, so it is drawn explicitly: a visible outline when off,
   the accent with a tick when on. */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QTreeView::indicator, QListView::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #5b6a78;
    border-radius: 4px;
    background-color: #10161b;
}}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{
    border-color: {ACCENT};
    background-color: #16202a;
}}
QCheckBox::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    {_CHECK_IMAGE}
}}
QCheckBox::indicator:checked:hover {{
    background-color: #61b2e8;
    border-color: #61b2e8;
}}
QCheckBox::indicator:disabled {{
    border-color: #333d46;
    background-color: #171d22;
}}
QCheckBox::indicator:checked:disabled {{
    background-color: #2f5a77;
    border-color: #2f5a77;
}}

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
