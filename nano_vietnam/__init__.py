"""NanoVietnam AI — personal Vietnamese-learning Telegram bot.

Layout (see ../word_fsm.md and ../nanovietnam_spec_v0.3.md for the design):
    domain.py            — WordStateService + ReviewScheduler, pure domain logic, no I/O
                            side effects beyond explicit db parameter (closure-injected,
                            never opened internally)
    database.py           — SQLite WAL connection + schema + single-transaction session
                            context manager
    market_data.py        — word list + scenario data for the "market" scenario module
    programs/daily_session.py — nano-vm-shaped orchestration layer (Program-equivalent)
    programs/market.py    — scenario module (conversation stub)
    bot.py                 — aiogram 3 Telegram adapter
"""
