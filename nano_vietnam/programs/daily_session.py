"""daily_session — execution-layer orchestrator (nano-vm-shaped Program equivalent).

This is NOT a real llm-nano-vm Program (no ASTEngine, no Step/CONDITION DSL, no Trace) — it is a
plain-async simulation of the same step names/shapes, written so it can be swapped for a real
Program later without changing the domain layer it calls. See nanovietnam_spec v0.3 §5 for the
target Step graph this mirrors.

Hard rule enforced here (word_fsm.md §3): score_answer runs its DB work inside exactly one
database.session() block passed in by the caller. It never opens its own connection. This is the
fix for the session-boundary bug that was found and fixed once already in Sieshka's order_tools.py
(DECISIONS.md 2026-07-01) — the same class of bug must not be reintroduced here.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite

from nano_vietnam.domain import (
    ReviewScheduler,
    WordEvent,
    WordKnowledge,
    WordState,
    WordStateService,
    get_known_word_list,
    get_word_knowledge,
    save_word_knowledge,
)
from nano_vietnam.market_data import WordCard

NEW_WORDS_PER_SESSION = 3


def normalize_answer(text: str) -> str:
    """Lenient comparison — strip, lowercase, drop trailing punctuation.

    MVP-honesty note (spec v0.1 §1 review, comment on the first code draft): exact-match comparison
    punishes typos/trailing-space/case on the very metric the MVP is supposed to validate (daily
    return rate), not the thing it's supposed to teach. Keep this lenient on purpose.
    """
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[.,!?;:]+$", "", cleaned)
    return cleaned.strip()


@dataclass
class SessionPlan:
    mode: str  # "drops_review" | "drops_new" | "no_words_due"
    cards: list[WordCard] = field(default_factory=list)


class DailySessionProgram:
    def __init__(self, user_id: int, words_pool: list[WordCard]):
        self.user_id = user_id
        self.words_pool = words_pool
        self.trace_id = str(uuid.uuid4())

    def _find_card(self, word: str) -> WordCard:
        for card in self.words_pool:
            if card.word == word:
                return card
        raise ValueError(f"Unknown word not in pool: {word!r}")

    async def select_mode(
        self, db: aiosqlite.Connection, now: datetime | None = None
    ) -> SessionPlan:
        """select_mode[TOOL] — due reviews take priority over new words (spec v0.3 §5).

        `now` is accepted explicitly (not just defaulted inside ReviewScheduler) so callers —
        tests in particular — can pin time deterministically instead of racing real wall-clock time.
        """
        due = await ReviewScheduler.get_due_words(db, self.user_id, now=now)
        if due:
            due_set = set(due)
            cards = [c for c in self.words_pool if c.word in due_set]
            return SessionPlan(mode="drops_review", cards=cards)

        known = await get_known_word_list(db, self.user_id)
        new_cards = [c for c in self.words_pool if c.word not in known][:NEW_WORDS_PER_SESSION]

        if not new_cards:
            return SessionPlan(mode="no_words_due", cards=[])

        for card in new_cards:
            await ReviewScheduler.add_new_word(db, self.user_id, card.word, now=now)
            shown = WordStateService.transition(
                WordKnowledge(WordState.UNKNOWN, 0), WordEvent.SHOWN
            )
            await save_word_knowledge(db, self.user_id, card.word, shown)

        return SessionPlan(mode="drops_new", cards=new_cards)

    async def score_answer(
        self,
        db: aiosqlite.Connection,
        word: str,
        user_answer: str,
        now: datetime | None = None,
    ) -> WordEvent:
        """score_session[TOOL] for one word — one CONDITION-equivalent branch, one transaction.

        Caller is responsible for wrapping this in `async with database.session(...) as db:` so
        both domain writes (state + schedule) commit or roll back together.
        """
        now = now or datetime.now(timezone.utc)
        card = self._find_card(word)
        event = (
            WordEvent.SUCCESS
            if normalize_answer(user_answer) == normalize_answer(card.gloss)
            else WordEvent.FAIL
        )

        knowledge = await get_word_knowledge(db, self.user_id, word)
        new_knowledge = WordStateService.transition(knowledge, event)
        await save_word_knowledge(db, self.user_id, word, new_knowledge)
        await ReviewScheduler.schedule_next(db, self.user_id, word, event, now=now)

        return event

    @staticmethod
    def notify_summary(results: list[WordEvent]) -> str:
        """notify_summary[terminal] — pure formatting, no I/O."""
        known_count = sum(1 for r in results if r is WordEvent.SUCCESS)
        total = len(results)
        return f"Сессия завершена. Верно: {known_count}/{total}."
