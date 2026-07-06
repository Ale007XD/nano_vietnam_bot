"""SQLite WAL storage.

CONSTRAINT (see word_fsm.md §3, DECISIONS.md 2026-07-01 "Tool-authoring: side-effect session
boundary"): every logical operation that touches more than one table must run inside exactly one
`session()` block, with exactly one commit at the end. Domain functions in domain.py never open
their own connection — they always receive `db` as a parameter (closure injection), so callers
control the transaction boundary. Do not add a `get_db()`-style helper that opens-and-closes per
call; that is the bug this module exists to avoid.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

DEFAULT_DB_PATH = "nano_vietnam.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active_scenario TEXT DEFAULT 'market',
    streak_days INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS known_words (
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'UNKNOWN',
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, word)
);

CREATE TABLE IF NOT EXISTS review_schedule (
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    srs_weight INTEGER NOT NULL DEFAULT 0,
    next_review_at TIMESTAMP NOT NULL,
    last_result TEXT,
    PRIMARY KEY (user_id, word)
);

CREATE TABLE IF NOT EXISTS sessions (
    trace_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mode TEXT,
    completed_at TIMESTAMP
);
"""


async def init_db(path: str = DEFAULT_DB_PATH) -> None:
    """Create schema if absent. Idempotent — safe to call on every bot startup."""
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(SCHEMA)
        await db.commit()


@asynccontextmanager
async def session(path: str = DEFAULT_DB_PATH) -> AsyncIterator[aiosqlite.Connection]:
    """Single transaction boundary for one logical operation.

    Commits once on clean exit, rolls back the whole block on any exception, always closes.
    Callers pass the yielded connection into domain functions instead of letting those functions
    open their own connections.
    """
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON;")
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
