"""Tests for the shared user-preference helpers."""

from starbash.preferences import DEFAULT_AUTO_REINDEX, auto_reindex_enabled


class _FakeRepo:
    """Minimal stand-in for the user preferences repo."""

    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = values or {}

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


class TestAutoReindexPreference:
    """The canonical auto-reindex default is shared by every front end.

    It mirrors the comment in ``templates/userconfig.toml``: a processing run
    scans the image folders first, unless the user opts out.
    """

    def test_documented_default_value(self):
        assert DEFAULT_AUTO_REINDEX is True

    def test_unset_preference_reindexes(self):
        assert auto_reindex_enabled(_FakeRepo()) is True

    def test_explicit_preferences_win(self):
        assert auto_reindex_enabled(_FakeRepo({"reindex.auto": False})) is False
        assert auto_reindex_enabled(_FakeRepo({"reindex.auto": True})) is True

    def test_helper_coerces_to_bool(self):
        assert auto_reindex_enabled(_FakeRepo({"reindex.auto": 0})) is False
        assert auto_reindex_enabled(_FakeRepo({"reindex.auto": 1})) is True
