"""Domain layer — see word_fsm.md for the specification this module implements.

Two responsibilities, kept separate on purpose (word_fsm.md §0, nanovietnam_spec v0.3 §4):

    WordStateService  — qualitative knowledge of a word. Pure function, no I/O, no datetime.
    ReviewScheduler    — when to show a word again. Owns srs_weight/next_review_at, not WordState.

Repository helpers (get_word_knowledge/save_word_knowledge/get_known_words) take an open
`aiosqlite.Connection` as their first argument and never open or close one themselves — the
transaction boundary belongs to the caller (see database.session()).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import aiosqlite


class WordState(str, Enum):
    UNKNOWN = "UNKNOWN"
    INTRODUCED = "INTRODUCED"
    LEARNING = "LEARNING"
    KNOWN = "KNOWN"


class WordEvent(str, Enum):
    SHOWN = "SHOWN"
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class WordKnowledge:
    state: WordState
    consecutive_successes: int = 0


class WordStateService:
    """Pure domain state machine. No DB, no LLM, no nano-vm. See word_fsm.md §1."""

    MASTERY_THRESHOLD = 3

    @staticmethod
    def transition(knowledge: WordKnowledge, event: WordEvent) -> WordKnowledge:
        state = knowledge.state
        n = knowledge.consecutive_successes

        if state is WordState.UNKNOWN:
            if event is WordEvent.SHOWN:
                return WordKnowledge(WordState.INTRODUCED, 0)
            raise ValueError(
                f"{event} is invalid for {state}: a word must be SHOWN before it can be answered"
            )

        if state is WordState.INTRODUCED:
            if event is WordEvent.SUCCESS:
                return WordKnowledge(WordState.LEARNING, 1)
            if event is WordEvent.FAIL:
                return WordKnowledge(WordState.LEARNING, 0)
            raise ValueError(f"{event} is invalid for {state}: already shown once")

        if state is WordState.LEARNING:
            if event is WordEvent.SUCCESS:
                streak = n + 1
                if streak >= WordStateService.MASTERY_THRESHOLD:
                    return WordKnowledge(WordState.KNOWN, streak)
                return WordKnowledge(WordState.LEARNING, streak)
            if event is WordEvent.FAIL:
                return WordKnowledge(WordState.LEARNING, 0)
            raise ValueError(f"{event} is invalid for {state}")

        if state is WordState.KNOWN:
            if event is WordEvent.SUCCESS:
                return WordKnowledge(WordState.KNOWN, n + 1)
            if event is WordEvent.FAIL:
                return WordKnowledge(WordState.LEARNING, 0)
            raise ValueError(f"{event} is invalid for {state}")

        raise ValueError(f"Unknown state: {state!r}")  # pragma: no cover — exhaustive Enum guard


async def get_word_knowledge(
    db: aiosqlite.Connection, user_id: int, word: str
) -> WordKnowledge:
    async with db.execute(
        "SELECT state, consecutive_successes FROM known_words WHERE user_id = ? AND word = ?",
        (user_id, word),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return WordKnowledge(WordState.UNKNOWN, 0)
    return WordKnowledge(WordState(row["state"]), row["consecutive_successes"])


async def save_word_knowledge(
    db: aiosqlite.Connection, user_id: int, word: str, knowledge: WordKnowledge
) -> None:
    """Writes only — does not commit. Commit belongs to the caller's session() block."""
    await db.execute(
        """
        INSERT INTO known_words (user_id, word, state, consecutive_successes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, word) DO UPDATE SET
            state = excluded.state,
            consecutive_successes = excluded.consecutive_successes
        """,
        (user_id, word, knowledge.state.value, knowledge.consecutive_successes),
    )


async def get_known_word_list(db: aiosqlite.Connection, user_id: int) -> set[str]:
    """Words that have been shown at least once (any state != absent row)."""
    async with db.execute(
        "SELECT word FROM known_words WHERE user_id = ?", (user_id,)
    ) as cur:
        rows = await cur.fetchall()
    return {row["word"] for row in rows}


class ReviewScheduler:
    """Owns timing only. Never touches WordState. See word_fsm.md §2."""

    FAIL_RETRY_MINUTES = 10

    @staticmethod
    async def get_due_words(
        db: aiosqlite.Connection,
        user_id: int,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[str]:
        now = now or datetime.now(timezone.utc)
        async with db.execute(
            """
            SELECT word FROM review_schedule
            WHERE user_id = ? AND next_review_at <= ?
            ORDER BY next_review_at ASC LIMIT ?
            """,
            (user_id, now.isoformat(), limit),
        ) as cur:
            rows = await cur.fetchall()
        return [row["word"] for row in rows]

    @staticmethod
    async def schedule_next(
        db: aiosqlite.Connection,
        user_id: int,
        word: str,
        event: WordEvent,
        now: datetime | None = None,
    ) -> None:
        if event is WordEvent.SHOWN:
            raise ValueError("SHOWN does not carry a review outcome — use SUCCESS or FAIL")

        now = now or datetime.now(timezone.utc)
        async with db.execute(
            "SELECT srs_weight FROM review_schedule WHERE user_id = ? AND word = ?",
            (user_id, word),
        ) as cur:
            row = await cur.fetchone()
        current_weight = row["srs_weight"] if row is not None else 0

        if event is WordEvent.SUCCESS:
            new_weight = current_weight + 1
            next_review = now + timedelta(days=2**new_weight)
        else:
            new_weight = 0
            next_review = now + timedelta(minutes=ReviewScheduler.FAIL_RETRY_MINUTES)

        await db.execute(
            """
            INSERT INTO review_schedule (user_id, word, srs_weight, next_review_at, last_result)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, word) DO UPDATE SET
                srs_weight = excluded.srs_weight,
                next_review_at = excluded.next_review_at,
                last_result = excluded.last_result
            """,
            (user_id, word, new_weight, next_review.isoformat(), event.value),
        )

    @staticmethod
    async def add_new_word(
        db: aiosqlite.Connection, user_id: int, word: str, now: datetime | None = None
    ) -> None:
        now = now or datetime.now(timezone.utc)
        await db.execute(
            "INSERT OR IGNORE INTO review_schedule (user_id, word, srs_weight, next_review_at, "
            "last_result) VALUES (?, ?, 0, ?, NULL)",
            (user_id, word, now.isoformat()),
        )
