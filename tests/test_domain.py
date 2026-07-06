"""WordStateService — pure domain tests. No DB, no asyncio.

Mirrors word_fsm.md §1.3 table exactly.
"""

from __future__ import annotations

import pytest

from nano_vietnam.domain import WordEvent, WordKnowledge, WordState, WordStateService


def test_unknown_shown_becomes_introduced() -> None:
    result = WordStateService.transition(WordKnowledge(WordState.UNKNOWN, 0), WordEvent.SHOWN)
    assert result == WordKnowledge(WordState.INTRODUCED, 0)


@pytest.mark.parametrize("event", [WordEvent.SUCCESS, WordEvent.FAIL])
def test_unknown_cannot_be_answered_before_shown(event: WordEvent) -> None:
    with pytest.raises(ValueError, match="SHOWN"):
        WordStateService.transition(WordKnowledge(WordState.UNKNOWN, 0), event)


def test_introduced_success_becomes_learning_streak_1() -> None:
    result = WordStateService.transition(
        WordKnowledge(WordState.INTRODUCED, 0), WordEvent.SUCCESS
    )
    assert result == WordKnowledge(WordState.LEARNING, 1)


def test_introduced_fail_becomes_learning_streak_0() -> None:
    result = WordStateService.transition(WordKnowledge(WordState.INTRODUCED, 0), WordEvent.FAIL)
    assert result == WordKnowledge(WordState.LEARNING, 0)


def test_introduced_cannot_be_shown_again() -> None:
    with pytest.raises(ValueError):
        WordStateService.transition(WordKnowledge(WordState.INTRODUCED, 0), WordEvent.SHOWN)


def test_learning_success_below_threshold_stays_learning() -> None:
    result = WordStateService.transition(WordKnowledge(WordState.LEARNING, 1), WordEvent.SUCCESS)
    assert result == WordKnowledge(WordState.LEARNING, 2)


def test_learning_success_reaches_mastery_threshold_becomes_known() -> None:
    result = WordStateService.transition(WordKnowledge(WordState.LEARNING, 2), WordEvent.SUCCESS)
    assert result == WordKnowledge(WordState.KNOWN, 3)


def test_three_consecutive_successes_from_introduced_reach_known() -> None:
    """End-to-end walk of the happy path: INTRODUCED -> LEARNING(1) -> LEARNING(2) -> KNOWN(3)."""
    k = WordKnowledge(WordState.INTRODUCED, 0)
    k = WordStateService.transition(k, WordEvent.SUCCESS)
    assert k == WordKnowledge(WordState.LEARNING, 1)
    k = WordStateService.transition(k, WordEvent.SUCCESS)
    assert k == WordKnowledge(WordState.LEARNING, 2)
    k = WordStateService.transition(k, WordEvent.SUCCESS)
    assert k == WordKnowledge(WordState.KNOWN, 3)


def test_learning_fail_resets_streak_without_demoting_state() -> None:
    result = WordStateService.transition(WordKnowledge(WordState.LEARNING, 2), WordEvent.FAIL)
    assert result == WordKnowledge(WordState.LEARNING, 0)


def test_known_success_stays_known_and_counter_keeps_incrementing() -> None:
    result = WordStateService.transition(WordKnowledge(WordState.KNOWN, 3), WordEvent.SUCCESS)
    assert result == WordKnowledge(WordState.KNOWN, 4)


def test_known_fail_demotes_to_learning_streak_0() -> None:
    result = WordStateService.transition(WordKnowledge(WordState.KNOWN, 5), WordEvent.FAIL)
    assert result == WordKnowledge(WordState.LEARNING, 0)


def test_known_cannot_be_shown_again() -> None:
    with pytest.raises(ValueError):
        WordStateService.transition(WordKnowledge(WordState.KNOWN, 3), WordEvent.SHOWN)


def test_fail_never_produces_unknown_or_introduced() -> None:
    """Invariant from word_fsm.md §1.4: FAIL never regresses below LEARNING."""
    for state in (WordState.INTRODUCED, WordState.LEARNING, WordState.KNOWN):
        result = WordStateService.transition(WordKnowledge(state, 2), WordEvent.FAIL)
        assert result.state in (WordState.LEARNING,)


def test_mastery_threshold_is_the_documented_constant() -> None:
    assert WordStateService.MASTERY_THRESHOLD == 3
