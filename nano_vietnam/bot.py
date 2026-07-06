"""aiogram 3 Telegram adapter — thin channel adapter, no domain logic here.

receive(payload) -> daily_session.select_mode/score_answer -> send(output), per the
channel-adapter pattern already used in the nano-vm ecosystem (Tarot-Nano-Bot, sprint_5_mcp_vmstep).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

from nano_vietnam import database
from nano_vietnam.domain import WordEvent
from nano_vietnam.market_data import MARKET_WORDS, WordCard
from nano_vietnam.programs.daily_session import DailySessionProgram

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = os.environ.get("NANO_VIETNAM_DB_PATH", database.DEFAULT_DB_PATH)

logger = logging.getLogger(__name__)

dp = Dispatcher()


@dataclass
class ActiveSession:
    program: DailySessionProgram
    cards: list[WordCard]
    index: int = 0
    results: list[WordEvent] = field(default_factory=list)


# In-memory per-user session state (v0.1 constraint, see nanovietnam_spec §12 risks — lost on
# restart; acceptable for a single-user local personal prototype, not beyond that).
_active_sessions: dict[int, ActiveSession] = {}


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    assert message.from_user is not None
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="/lesson")]], resize_keyboard=True
    )
    await message.answer(
        "Привет! NanoVietnam MVP.\nСценарий по умолчанию: Рынок.\n"
        "Нажми /lesson, чтобы начать сессию.",
        reply_markup=kb,
    )


@dp.message(Command("lesson"))
async def cmd_lesson(message: Message) -> None:
    assert message.from_user is not None
    user_id = message.from_user.id
    program = DailySessionProgram(user_id, MARKET_WORDS)

    async with database.session(DB_PATH) as db:
        plan = await program.select_mode(db)

    if plan.mode == "no_words_due":
        await message.answer("Все слова изучены и ничего не просрочено. Загляни позже.")
        return

    _active_sessions[user_id] = ActiveSession(program=program, cards=plan.cards)
    card = plan.cards[0]
    await message.answer(
        f"Слово: {card.word}\nТранскрипция: {card.translit}\nПеревод: {card.gloss}\n\n"
        "Напиши перевод этого слова:"
    )


@dp.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    assert message.from_user is not None
    user_id = message.from_user.id
    async with database.session(DB_PATH) as db:
        async with db.execute(
            "SELECT state, COUNT(*) as n FROM known_words WHERE user_id = ? GROUP BY state",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Пока нет данных. Начни с /lesson.")
        return
    counts = {row["state"]: row["n"] for row in rows}
    await message.answer(
        "Прогресс:\n"
        f"INTRODUCED: {counts.get('INTRODUCED', 0)}\n"
        f"LEARNING: {counts.get('LEARNING', 0)}\n"
        f"KNOWN: {counts.get('KNOWN', 0)}"
    )


@dp.message(F.text)
async def handle_text_answer(message: Message) -> None:
    assert message.from_user is not None
    assert message.text is not None
    user_id = message.from_user.id
    session_data = _active_sessions.get(user_id)
    if session_data is None:
        await message.answer("Сессия не активна. Напиши /lesson")
        return

    card = session_data.cards[session_data.index]

    async with database.session(DB_PATH) as db:
        event = await session_data.program.score_answer(db, card.word, message.text)
    session_data.results.append(event)

    session_data.index += 1
    if session_data.index < len(session_data.cards):
        next_card = session_data.cards[session_data.index]
        await message.answer(
            f"Следующее слово:\n{next_card.word} ({next_card.translit})\n\nНапиши перевод:"
        )
    else:
        summary = DailySessionProgram.notify_summary(session_data.results)
        await message.answer(summary)
        del _active_sessions[user_id]


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set — copy .env.example to .env and fill it in")
    await database.init_db(DB_PATH)
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
