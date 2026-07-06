from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nano_vietnam import database
from nano_vietnam.domain import (
    ReviewScheduler,
    WordEvent,
    WordKnowledge,
    WordState,
    get_known_word_list,
    get_word_knowledge,
    save_word_knowledge,
)

pytestmark = pytest.mark.asyncio

FIXED_NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


async def test_add_new_word_is_due_immediately(db_path: str) -> None:
    async with database.session(db_path) as db:
        await ReviewScheduler.add_new_word(db, user_id=1, word="chợ", now=FIXED_NOW)

    async with database.session(db_path) as db:
        due = await ReviewScheduler.get_due_words(db, user_id=1, now=FIXED_NOW)
    assert due == ["chợ"]


async def test_success_pushes_next_review_out_exponentially(db_path: str) -> None:
    async with database.session(db_path) as db:
        await ReviewScheduler.add_new_word(db, 1, "chợ", now=FIXED_NOW)
        await ReviewScheduler.schedule_next(db, 1, "chợ", WordEvent.SUCCESS, now=FIXED_NOW)

    # weight becomes 1 -> next review in 2**1 = 2 days; not due 1 day later
    async with database.session(db_path) as db:
        due_early = await ReviewScheduler.get_due_words(
            db, 1, now=FIXED_NOW + timedelta(days=1)
        )
    assert due_early == []

    async with database.session(db_path) as db:
        due_later = await ReviewScheduler.get_due_words(
            db, 1, now=FIXED_NOW + timedelta(days=2)
        )
    assert due_later == ["chợ"]


async def test_fail_schedules_quick_retry_and_resets_weight(db_path: str) -> None:
    async with database.session(db_path) as db:
        await ReviewScheduler.add_new_word(db, 1, "chợ", now=FIXED_NOW)
        await ReviewScheduler.schedule_next(db, 1, "chợ", WordEvent.SUCCESS, now=FIXED_NOW)
        # second event: FAIL should reset weight to 0 -> next retry in 10 minutes, not 4 days
        await ReviewScheduler.schedule_next(
            db, 1, "chợ", WordEvent.FAIL, now=FIXED_NOW + timedelta(days=2)
        )

    async with database.session(db_path) as db:
        not_due_yet = await ReviewScheduler.get_due_words(
            db, 1, now=FIXED_NOW + timedelta(days=2, minutes=5)
        )
        due_after_retry_window = await ReviewScheduler.get_due_words(
            db, 1, now=FIXED_NOW + timedelta(days=2, minutes=11)
        )
    assert not_due_yet == []
    assert due_after_retry_window == ["chợ"]


async def test_schedule_next_rejects_shown_event(db_path: str) -> None:
    async with database.session(db_path) as db:
        await ReviewScheduler.add_new_word(db, 1, "chợ", now=FIXED_NOW)
        with pytest.raises(ValueError, match="SHOWN"):
            await ReviewScheduler.schedule_next(db, 1, "chợ", WordEvent.SHOWN, now=FIXED_NOW)


async def test_word_knowledge_roundtrip(db_path: str) -> None:
    async with database.session(db_path) as db:
        before = await get_word_knowledge(db, 1, "chợ")
        assert before == WordKnowledge(WordState.UNKNOWN, 0)

        await save_word_knowledge(db, 1, "chợ", WordKnowledge(WordState.LEARNING, 2))

    async with database.session(db_path) as db:
        after = await get_word_knowledge(db, 1, "chợ")
    assert after == WordKnowledge(WordState.LEARNING, 2)


async def test_get_known_word_list_reflects_saved_words(db_path: str) -> None:
    async with database.session(db_path) as db:
        await save_word_knowledge(db, 1, "chợ", WordKnowledge(WordState.INTRODUCED, 0))
        await save_word_knowledge(db, 1, "mua", WordKnowledge(WordState.LEARNING, 1))

    async with database.session(db_path) as db:
        known = await get_known_word_list(db, 1)
    assert known == {"chợ", "mua"}


async def test_known_words_are_isolated_per_user(db_path: str) -> None:
    async with database.session(db_path) as db:
        await save_word_knowledge(db, 1, "chợ", WordKnowledge(WordState.KNOWN, 5))

    async with database.session(db_path) as db:
        user2_knowledge = await get_word_knowledge(db, 2, "chợ")
    assert user2_knowledge == WordKnowledge(WordState.UNKNOWN, 0)
