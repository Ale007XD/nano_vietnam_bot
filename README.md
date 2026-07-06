# NanoVietnam AI — v0.1 (личный проект)

FSM-governed Vietnamese daily-habit-loop bot. См. `nanovietnam_spec_v0.3.md` (архитектура,
non-goals, MVP-гипотеза) и `word_fsm.md` (доменная модель — единственный источник истины по
состояниям слова и алгоритму повторений).

## Что это, а что нет

- Это: WordStateService (чистая FSM) + ReviewScheduler (SRS) + плоская оркестрация
  (`daily_session.py`), имитирующая форму nano-vm Program (Step-имена, но без реального
  ASTEngine/Trace) + aiogram-адаптер.
- Это НЕ: интеграция с настоящим `llm-nano-vm` runtime (см. README раздел "Интеграция с
  llm-nano-vm" ниже — это следующий, не текущий шаг), НЕ voice/ASR (MVP использует
  текстовый ввод), НЕ библиотека контента (~20 слов-заглушка, расширить вручную до ~50).

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # вписать реальный BOT_TOKEN
```

## Запуск

```bash
python -m nano_vietnam.bot
```

## Тесты и проверки (как в CI)

```bash
ruff check .
mypy --strict nano_vietnam
pytest -v
```

## Структура

```
nano_vietnam/
    database.py             — SQLite WAL + database.session() — единственная точка транзакций
    domain.py                — WordStateService (чистая FSM) + ReviewScheduler + repository-функции
    market_data.py            — словарь сценария "market" (~20 слов, расширить вручную до ~50)
    programs/
        daily_session.py       — оркестрация: select_mode → score_answer → notify_summary
        market.py                — сценарий-модуль (диалог — пока stub, без реального LLM)
    bot.py                     — aiogram 3 адаптер (Telegram)
tests/
    test_domain.py              — вся таблица переходов WordStateService, без БД
    test_review_scheduler.py    — SRS-таймер против временной БД
    test_daily_session.py       — регрессионные тесты на оба найденных бага (см. ниже)
word_fsm.md                — доменная спека (состояния/переходы/SRS-алгоритм)
```

## Два бага, зафиксированных регрессионными тестами

1. **Session boundary.** Первый черновик кода открывал 2-3 независимых DB-соединения на один
   логический переход слова — тот же класс ошибки, что уже находили и чинили в Sieshka
   (`order_tools.py`, DECISIONS.md 2026-07-01). Исправлено: `database.session()` — одна
   транзакция на весь `score_answer`, коммит один раз, откат при любом исключении.
   `test_score_answer_is_atomic_on_scheduler_failure` проверяет это явно.
2. **Прогрессия словаря.** Первый черновик всегда брал `MARKET_WORDS[:3]` — словарь никогда не
   рос. Исправлено: `select_mode` фильтрует уже показанные слова через `get_known_word_list`.
   `test_select_mode_skips_already_known_words_for_new_batch` проверяет это явно.

## Интеграция с настоящим llm-nano-vm (следующий шаг, не сделано здесь)

`daily_session.py` написан так, чтобы domain-слой (`domain.py`) можно было вызывать из настоящих
TOOL-шагов nano-vm без изменений: `WordStateService.transition` и `ReviewScheduler.*` не знают
про nano-vm вообще, принимают только явные аргументы. Перенос `select_mode`/`score_answer`/
`notify_summary` в реальный Program (Step/CONDITION DSL, `normalize_output`, `is_terminal`) —
отдельная задача, требующая доступа к `llm-nano-vm` как зависимости.
