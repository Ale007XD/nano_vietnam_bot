"""market — one scenario module, per nanovietnam_spec v0.3 §6 (scenario-as-modules).

Only this scenario is implemented in v0.1. clinic.py/coffee.py/rental.py do not exist yet — they
are added later as new files under programs/, without touching daily_session.py or domain.py.

The conversation step is a stub: it returns one canned exchange instead of calling an LLM, so the
whole pipeline (select_mode -> cards -> score_answer -> summary) is testable and runnable in CI
without any API key or network access. Wiring a real LLMAdapter here is a follow-up, not part of
this MVP code drop.
"""

from __future__ import annotations

SCENARIO_PROMPT = (
    "Ты продавец на рынке во Вьетнаме. Покупатель хочет купить фрукты. "
    "Ответь одной репликой по-вьетнамски, с транскрипцией и переводом. Будь дружелюбным."
)


def stub_dialog_turn(user_reply: str) -> str:
    """Deterministic placeholder for the real LLM call — keeps the module importable/testable
    without a live model. Replace body with an LLMAdapter.complete() call when wiring the real
    conversation_scenario step; keep the function signature so daily_session doesn't need to change.
    """
    return (
        "Cảm ơn! (кам эн — спасибо) Bao nhiêu? (бао ньеу — сколько будете брать?)\n"
        f"[получено от пользователя: {user_reply!r}]"
    )
