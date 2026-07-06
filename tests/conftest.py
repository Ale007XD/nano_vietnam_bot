from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from nano_vietnam import database


@pytest_asyncio.fixture
async def db_path(tmp_path: Path) -> AsyncIterator[str]:
    path = str(tmp_path / "test.db")
    await database.init_db(path)
    yield path
