"""Smoke-import test — mirrors the ecosystem's CI hardening pattern (CONSTRAINTS.md: 'smoke-import
шаг в lint job после каждого нового модуля'). Catches import-time errors (bad imports, syntax
errors introduced by editing) without needing a real BOT_TOKEN or network access.
"""

from __future__ import annotations

import importlib


def test_bot_module_imports_without_a_configured_token(monkeypatch: object) -> None:
    # BOT_TOKEN is read at import time as an optional value (may be None) — the module must not
    # raise on import; it only raises inside main() when actually starting polling.
    module = importlib.import_module("nano_vietnam.bot")
    assert hasattr(module, "dp")
    assert hasattr(module, "main")


def test_all_public_modules_import_cleanly() -> None:
    for name in [
        "nano_vietnam.database",
        "nano_vietnam.domain",
        "nano_vietnam.market_data",
        "nano_vietnam.programs.daily_session",
        "nano_vietnam.programs.market",
        "nano_vietnam.bot",
    ]:
        importlib.import_module(name)
