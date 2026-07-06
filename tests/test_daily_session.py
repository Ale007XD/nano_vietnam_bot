"""Tests for the two concrete bugs found and fixed in review of the first code draft:

1. score_answer used to open 2-3 independent DB connections/commits per call (session-boundary
   bug, same class as Sieshka order_tools.py, DECISIONS.md 2026-07-01) — test_score_answer_is_atomic
   proves a failure in the second write rolls back the first.
2. drops_new used to hardcode MARKET_WORDS[:3] regardless of what the user already knows, so the
   vocabulary never grew past 3 words — test_select_mode_skips_already_known_words proves the fix.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nano_vietnam import database
from nano_vietnam.domain import (
    ReviewScheduler,
    WordEvent,
    WordKnowledge,
    WordState,
    get_word_knowledge,
    save_word_knowledge,
)
from nano_vietnam.market_data import MARKET_WORDS
from nano_vietnam.programs.daily_session import DailySessionProgram, normalize_answer

FIXED_NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_select_mode_introduces_first_batch_as_new(db_path: str) -> None:
    program = DailySessionProgram(1, MARKET_WORDS)
    async with database.session(db_path) as db:
        plan = await program.select_mode(db, now=FIXED_NOW)

    assert plan.mode == "drops_new"
    assert [c.word for c in plan.cards] == [c.word for c in MARKET_WORDS[:3]]


@pytest.mark.asyncio
async def test_select_mode_skips_already_known_words_for_new_batch(db_path: str) -> None:
    """Regression test for the fixed bug: MARKET_WORDS[:3] must not repeat forever."""
    async with database.session(db_path) as db:
        for card in MARKET_WORDS[:3]:
            await save_word_knowledge(db, 1, card.word, WordKnowledge(WordState.KNOWN, 5))
            await ReviewScheduler.add_new_word(db, 1, card.word, now=FIXED_NOW)
            # push far enough into the future that they are not "due" during this test
            await ReviewScheduler.schedule_next(
                db, 1, card.word, WordEvent.SUCCESS, now=FIXED_NOW
            )
            await ReviewScheduler.schedule_next(
                db, 1, card.word, WordEvent.SUCCESS, now=FIXED_NOW
            )

    program = DailySessionProgram(1, MARKET_WORDS)
    async with database.session(db_path) as db:
        plan = await program.select_mode(db, now=FIXED_NOW + timedelta(hours=1))

    assert plan.mode == "drops_new"
    introduced_words = {c.word for c in plan.cards}
    already_known_words = {c.word for c in MARKET_WORDS[:3]}
    assert introduced_words.isdisjoint(already_known_words)
    assert introduced_words == {c.word for c in MARKET_WORDS[3:6]}


@pytest.mark.asyncio
async def test_select_mode_prioritizes_due_reviews_over_new_words(db_path: str) -> None:
    async with database.session(db_path) as db:
        await ReviewScheduler.add_new_word(db, 1, MARKET_WORDS[0].word, now=FIXED_NOW)

    program = DailySessionProgram(1, MARKET_WORDS)
    async with database.session(db_path) as db:
        plan = await program.select_mode(db, now=FIXED_NOW)

    assert plan.mode == "drops_review"
    assert [c.word for c in plan.cards] == [MARKET_WORDS[0].word]


@pytest.mark.asyncio
async def test_select_mode_reports_no_words_due_when_pool_exhausted(db_path: str) -> None:
    small_pool = MARKET_WORDS[:1]
    program = DailySessionProgram(1, small_pool)
    async with database.session(db_path) as db:
        await program.select_mode(db, now=FIXED_NOW)  # introduces the only word, now due
        # answer it correctly and push it far into the future so nothing is due
        await program.score_answer(db, small_pool[0].word, small_pool[0].gloss, now=FIXED_NOW)

    async with database.session(db_path) as db:
        plan = await program.select_mode(db, now=FIXED_NOW + timedelta(hours=1))

    assert plan.mode == "no_words_due"


@pytest.mark.asyncio
async def test_score_answer_success_matches_normalized_gloss(db_path: str) -> None:
    program = DailySessionProgram(1, MARKET_WORDS)
    word = MARKET_WORDS[0].word
    async with database.session(db_path) as db:
        await program.select_mode(db, now=FIXED_NOW)
        event = await program.score_answer(
            db, word, "  Здравствуйте!  ", now=FIXED_NOW
        )
    assert event is WordEvent.SUCCESS


@pytest.mark.asyncio
async def test_score_answer_wrong_answer_is_fail(db_path: str) -> None:
    program = DailySessionProgram(1, MARKET_WORDS)
    word = MARKET_WORDS[0].word
    async with database.session(db_path) as db:
        await program.select_mode(db, now=FIXED_NOW)
        event = await program.score_answer(db, word, "совершенно неверно", now=FIXED_NOW)
    assert event is WordEvent.FAIL


@pytest.mark.parametrize(
    "raw",
    ["здравствуйте", "Здравствуйте", "  здравствуйте  ", "здравствуйте.", "ЗДРАВСТВУЙТЕ!"],
)
def test_normalize_answer_is_lenient(raw: str) -> None:
    assert normalize_answer(raw) == "здравствуйте"


@pytest.mark.asyncio
async def test_score_answer_is_atomic_on_scheduler_failure(
    db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for the fixed session-boundary bug.

    If ReviewScheduler.schedule_next fails partway through score_answer, the WordStateService
    write that already happened in the same transaction must be rolled back too — not left
    half-committed. This is the exact class of bug documented in DECISIONS.md 2026-07-01 for
    Sieshka's order_tools.py.
    """
    program = DailySessionProgram(1, MARKET_WORDS)
    word = MARKET_WORDS[0].word

    async with database.session(db_path) as db:
        await program.select_mode(db, now=FIXED_NOW)

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated scheduler failure")

    monkeypatch.setattr(ReviewScheduler, "schedule_next", boom)

    with pytest.raises(RuntimeError):
        async with database.session(db_path) as db:
            await program.score_answer(db, word, MARKET_WORDS[0].gloss, now=FIXED_NOW)

    monkeypatch.undo()
    async with database.session(db_path) as db:
        knowledge = await get_word_knowledge(db, 1, word)
    # Must still be INTRODUCED (as select_mode left it) — NOT LEARNING, because the write inside
    # the failed transaction must have been rolled back together with the scheduler failure.
    assert knowledge == WordKnowledge(WordState.INTRODUCED, 0)


@pytest.mark.asyncio
async def test_notify_summary_counts_successes() -> None:
    summary = DailySessionProgram.notify_summary(
        [WordEvent.SUCCESS, WordEvent.FAIL, WordEvent.SUCCESS]
    )
    assert summary == "Сессия завершена. Верно: 2/3."
