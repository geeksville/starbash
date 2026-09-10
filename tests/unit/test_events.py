"""Tests for the core event bus and the interaction protocol (Phase 0)."""

import logging

import pytest

from starbash import events
from starbash.interaction import (
    AutoAcceptUserInteraction,
    RichUserInteraction,
    get_interaction,
    set_interaction,
)


@pytest.fixture(autouse=True)
def _clean_bus():
    """Ensure every test starts (and ends) with no subscribers installed."""
    events.clear_subscribers()
    yield
    events.clear_subscribers()


def test_publish_delivers_kind_and_data_to_subscribers():
    """A subscriber receives the event kind plus its payload dict."""
    received: list[events.Event] = []
    events.subscribe(received.append)

    events.publish(events.EVENT_TASK_STARTED, {"task": "stack", "title": "Stack"})

    assert len(received) == 1
    assert received[0].kind == events.EVENT_TASK_STARTED
    assert received[0].data == {"task": "stack", "title": "Stack"}


def test_publish_defaults_to_empty_payload():
    """Publishing without data yields an empty (never missing) payload."""
    received: list[events.Event] = []
    events.subscribe(received.append)

    events.publish("something.happened")

    assert received[0].data == {}


def test_publish_with_no_subscribers_is_a_noop():
    """The CLI subscribes to nothing, so publish must be safe with no listeners."""
    # Should not raise even though nothing is listening.
    events.publish(events.EVENT_TOOL_OUTPUT, {"line": "hello"})


def test_returned_unsubscribe_handle_removes_subscriber():
    """The function returned by subscribe() unregisters the callback again."""
    received: list[events.Event] = []
    unsubscribe = events.subscribe(received.append)

    events.publish("a")
    unsubscribe()
    events.publish("b")

    assert [event.kind for event in received] == ["a"]
    assert events.subscriber_count() == 0


def test_failing_subscriber_does_not_break_publish(caplog):
    """A buggy observer must never abort the producing code path."""
    good: list[events.Event] = []

    def boom(event: events.Event) -> None:
        raise RuntimeError("subscriber blew up")

    events.subscribe(boom)
    events.subscribe(good.append)

    with caplog.at_level(logging.ERROR):
        events.publish(events.EVENT_STAGE_RESULT, {"result": object()})

    # The healthy subscriber still ran, and the failure was logged.
    assert len(good) == 1
    assert "subscriber failed" in caplog.text.lower()


def test_subscriber_may_unsubscribe_during_dispatch():
    """Mutating the subscriber list while an event is dispatched is safe."""
    calls: list[str] = []

    def self_removing(event: events.Event) -> None:
        calls.append(event.kind)
        events.unsubscribe(self_removing)

    events.subscribe(self_removing)
    events.publish("first")
    events.publish("second")

    assert calls == ["first"]


def test_clear_subscribers_empties_the_bus():
    """clear_subscribers() is the test/GUI-shutdown escape hatch."""
    events.subscribe(lambda event: None)
    events.subscribe(lambda event: None)
    assert events.subscriber_count() == 2

    events.clear_subscribers()

    assert events.subscriber_count() == 0


def test_auto_accept_interaction_returns_defaults():
    """The headless interaction answers every prompt with its default."""
    interaction = AutoAcceptUserInteraction()

    assert interaction.confirm("proceed?", default=True) is True
    assert interaction.confirm("proceed?", default=False) is False
    assert interaction.text("name?", default="Ada") == "Ada"
    # URLs are never opened in headless mode.
    assert interaction.open_url("https://example.com") is False


def test_rich_interaction_delegates_to_rich_prompts(monkeypatch):
    """RichUserInteraction reproduces the CLI's Rich prompt behaviour."""
    from rich.prompt import Confirm, Prompt

    monkeypatch.setattr(Confirm, "ask", staticmethod(lambda *a, **k: True))
    monkeypatch.setattr(Prompt, "ask", staticmethod(lambda *a, **k: "typed"))

    interaction = RichUserInteraction()

    assert interaction.confirm("continue?") is True
    assert interaction.text("name?") == "typed"


def test_get_and_set_interaction_roundtrip():
    """The process-wide interaction accessor installs and restores implementations."""
    original = get_interaction()
    assert isinstance(original, RichUserInteraction)

    auto = AutoAcceptUserInteraction()
    try:
        set_interaction(auto)
        assert get_interaction() is auto

        # Passing None restores the default Rich implementation.
        set_interaction(None)
        assert isinstance(get_interaction(), RichUserInteraction)
    finally:
        set_interaction(original)
