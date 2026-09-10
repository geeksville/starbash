"""The dashboard: headline numbers plus the most recent sessions."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from starbash.app import Starbash
from starbash.ui.qt.models import SESSION_COLUMNS, DictTableModel
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.services import dashboard_stats, load_sessions
from starbash.ui.qt.widgets import StatCard

__all__ = ["DashboardPage"]

MAX_RECENT_SESSIONS = 50


class DashboardPage(Page):
    """An at-a-glance summary of what Starbash currently knows about."""

    nav_title = "Dashboard"
    subtitle = "Overview of your indexed sessions, frames and repositories."

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        self._cards: dict[str, StatCard] = {}
        super().__init__(sb, parent)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        cards = QHBoxLayout()
        for key, caption in (
            ("sessions", "Sessions"),
            ("frames", "Frames"),
            ("integration_hours", "Integration (h)"),
            ("images_indexed", "Images indexed"),
            ("repos", "Repositories"),
        ):
            card = StatCard(caption)
            self._cards[key] = card
            cards.addWidget(card)
        cards.addStretch(1)
        layout.addLayout(cards)

        layout.addWidget(QLabel("Most recent sessions"))
        self._model = DictTableModel(SESSION_COLUMNS)
        self._table = self.make_table(self._model)
        layout.addWidget(self._table, 1)

    def refresh(self) -> None:
        """Reload the stat cards and the recent-sessions table."""
        try:
            stats = dashboard_stats(self.sb)
        except Exception as exc:  # noqa: BLE001 - surface, don't crash the window
            self.show_error(f"Could not load dashboard: {exc}")
            return

        for key, card in self._cards.items():
            card.set_value(stats.get(key, 0))

        sessions = load_sessions(self.sb)
        sessions.sort(key=lambda row: str(row.get("start") or ""), reverse=True)
        self._model.set_rows(sessions[:MAX_RECENT_SESSIONS])
