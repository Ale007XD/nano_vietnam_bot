# NanoVietnam AI — Spec v0.3 (личный проект, draft)

Status: DRAFT — не в scope nano-vm ecosystem, отдельный трек. Не блокирует и не блокируется support_bot_pilot/Sieshka.

Changelog v0.1→v0.2: домен (Word FSM) явно отделён от execution-слоя (nano-vm Program); scenario-модули с первого дня; Living Vietnam — независимый sidecar-поток; честная формулировка MVP-гипотезы (habit loop, не тон-анализ); execution trace analytics перенесён в backlog с явной зависимостью.

Changelog v0.2→v0.3: доменный слой расщеплён на две ответственности — WordStateService (качественное знание слова, 4 состояния) и ReviewScheduler (когда показать слово, SRS-веса/даты). REVIEW/RETRY убраны из состояний знания — это были скрытые scheduling-концепции внутри domain FSM, перенесены в ReviewScheduler. Один документ word_fsm.md на обе ответственности (anti-sprawl — не плодить второй файл под тесно связанную концепцию).

---

## 1. Проблема

Существующие инструменты закрывают только часть задачи:
- LingQ — комфортный вход в реальный контент, но библиотека для вьетнамского тонкая, UI тяжёлый для новичка.
- Drops — сильный habit loop (5 мин/день, визуальная мнемоника), но без грамматики (частично) и без живого диалога.
- Ни один из двух не даёт feedback по тонам — критично для вьетнамского, где ошибка тона меняет смысл слова.

Задача: собрать loop, который берёт словарный habit-engine Drops + comprehension-модель LingQ + добавляет то, чего нет ни у кого — тоновый feedback и ролевые диалоги под конкретную жизненную ситуацию пользователя (рынок, аренда, врач).

**MVP-гипотеза (v0.2, явно сужена):** v0.1 отвечает на один вопрос — вернётся ли человек в бот на следующий день без внешнего давления. Это гипотеза про daily habit loop, НЕ про качество тонового анализа. Тоновый feedback — заявленный долгосрочный дифференциатор продукта, но не то, что MVP валидирует. Смешивать эти два утверждения нечестно перед самим собой: если habit loop не держит внимание на 50 словах без тона, добавление ASR это не починит.

## 2. Целевой пользователь (v0.1 — один персонаж, не пять)

Экспат/переезжающий в Вьетнам, живёт в русскоязычном контексте (как сам автор — Phan Rang), нужен разговорный вьетнамский под конкретные бытовые сценарии, не экзамен/сертификация. MVP не пытается закрыть турист + бизнес + семья одновременно — это функция, добавляемая после того, как loop работает на одном персонаже.

## 3. Принципы (что берём и что нет)

Берём:
- Drops: 5-минутная сессия, streak, визуальная мнемоника, spaced repetition как двигатель retention.
- LingQ: known/unknown word tracking как единственный источник истины о прогрессе (не оценка LLM "на глаз").
- Собственное: тоновый ASR-feedback (post-MVP) + ролевые диалоги под survival-сценарии.

Не берём:
- LingQ-style огромную библиотеку контента с нуля — для MVP это самое дорогое и наименее дифференцирующее.
- Drops-style полный набор языков/UI-фреймворк — telegram-first, без нативного приложения на первом этапе.
- Открытый диалог "поговори о чём хочешь" — слишком широкая, неконтролируемая content space для LLM-шага без projection.

## 4. Доменная модель: два сервиса, две ответственности (не execution-слой)

Формализуется до Telegram, до daily_session, до кода вообще. Домен расщеплён на два независимых компонента — это не два уровня иерархии, а два разных вопроса:

```
Domain layer
------------
WordStateService              ReviewScheduler
(что человек знает)           (когда это показать)
       |                             |
       v                             v
transition(word, event)      due_words(), schedule_next(word, result)
       |                             |
       +--------------+--------------+
                      |
                      v
              Execution layer
           daily_session Program
        (nano-vm orchestration)
```

### 4.1 WordStateService — качественное состояние знания слова

```
UNKNOWN -> INTRODUCED -> LEARNING -> KNOWN
```

Четыре состояния, не шесть. REVIEW и RETRY из v0.2 убраны отсюда — это были scheduling-концепции ("когда вернуть слово"), случайно смешанные с вопросом "что человек знает". Ошибка в fail-сценарии не меняет качественное состояние знания (слово всё ещё LEARNING, просто провалена одна попытка) — она влияет только на то, когда ReviewScheduler покажет его снова. Точный критерий перехода LEARNING->KNOWN (сколько успехов, с каким интервалом) — предмет `word_fsm.md`, не этой спеки.

Проверяется полностью без LLM и без nano-vm — чистые unit-тесты вида:
```
UNKNOWN + first_success -> INTRODUCED
LEARNING + success (N-й подряд) -> KNOWN
LEARNING + fail -> LEARNING (без изменения состояния, событие уходит в ReviewScheduler)
```

### 4.2 ReviewScheduler — когда вернуть слово пользователю

Владеет SRS-весами, датами следующего повторения, историей ответов. Не знает о Telegram, не знает о daily_session — только `due_words(user_id) -> list[Word]` и `schedule_next(word, result)`.

### 4.3 Архитектурное разграничение (тот же паттерн, что уже есть в Sieshka)

| | Sieshka (прецедент) | NanoVietnam |
|---|---|---|
| Domain state machine | ORDER_TRANSITIONS (DRAFT->CONFIRMED->PAID->...) | WordStateService (UNKNOWN->...->KNOWN) |
| Кто валидирует domain-переход | OrderService (Python-логика, не nano-vm) | WordStateService + ReviewScheduler (по аналогии) |
| nano-vm Program | transition_order_state — исполняет ОДИН domain-переход как одну транзакцию | daily_session — исполняет пакет domain-переходов (N слов) за одну сессию |
| Ошибка в этом слое | domain graph НЕ дублируется внутри generic tool (см. DECISIONS.md 2026-07-02, test_invalid_event_rejected) | ни один из двух графов (знание/расписание) НЕ должен жить внутри nano-vm Step/CONDITION |

Практический вывод: оба сервиса — обычный Python (enum + transition table + функции), которые вызывает TOOL-шаг daily_session Program, а не реализация через цепочку nano-vm Step'ов. Смешение этих слоёв — ровно та ошибка, которую уже находили и чинили в Sieshka.

Следующий документ к написанию (до кода): `word_fsm.md` — один файл на обе ответственности (не два: WordStateService и ReviewScheduler тесно связаны, отдельный файл под каждый — sprawl без пользы на масштабе 50 слов). Содержит: состояния WordStateService + таблицу переходов; алгоритм ReviewScheduler (веса, интервалы, due-критерий).

## 5. Execution-слой: FSM-governed learning loop (nano-vm)

Program daily_session — это оркестратор поверх N словных FSM за одну сессию, не представление одного слова.

```
select_mode[TOOL, читает StateContext + ReviewScheduler.due_words()]
  -> CONDITION: has_new_words? has_due_reviews? survival_topic_pending?
      -> drops_review[TOOL sub-program]      (due SRS items)
      -> drops_new[LLM+TOOL sub-program]     (3 новых слова)
      -> conversation_scenario[LLM sub-program]  (если новых/повторов нет)
  -> score_session[TOOL]     -> для каждого слова: WordStateService.transition(word, event) + ReviewScheduler.schedule_next(word, result)
  -> notify_summary[terminal]
```

### 5.1 Step-уровень (пример: drops_new)

```
generate_word_batch[LLM]       -> normalize_output(text, {word, translit, gloss})
  -> next_step: present_cards
present_cards[TOOL]             -> рендер в Telegram (карточка/картинка/аудио)
  -> next_step: capture_answer
capture_answer[TOOL]            -> сверка ответа со словарём, output: 0|1 сентинел (НЕ строка)
  -> CONDITION: $capture_answer.output == 1
      -> then: mark_known[TOOL]  -> WordStateService.transition(word, SUCCESS) + ReviewScheduler.schedule_next(word, SUCCESS) -> is_terminal
      -> otherwise: schedule_retry[TOOL] -> ReviewScheduler.schedule_next(word, FAIL) -> is_terminal  # состояние знания не меняется на fail
```

Важно (уроки nano-vm, применяются 1:1):
- Терминальные TOOL-шаги, которые не читаются downstream CONDITION — raise, не return "ERROR". Тихий sentinel в SRS-движке = тихая порча расписания повторов, тот же класс бага, что был в order_tools.py.
- CONDITION consumers — числовой sentinel (0/1), не строковый литерал (ASTEngine ограничение).
- normalize_output — total function: LLM-генерация слова должна всегда мапиться в валидную карточку или explicit fallback (RETRY_GENERATION), никогда не "как получится".
- Граф переходов WordStateService и логика ReviewScheduler живут в domain-слое, вызываются из TOOL-шага — не дублируются как CONDITION-цепочка внутри Program (см. п.4, таблица).

### 5.2 StateContext (per user)

```python
{
  "known_words": dict[str, WordState],   # WordState = enum(UNKNOWN|INTRODUCED|LEARNING|KNOWN) — только WordStateService
  "streak_days": int,
  "active_scenario": str | None,         # "market" | "clinic" | "rental" | None
  "last_session_trace_id": str,
}
```

level_estimate из v0.1 убран — производная метрика без чёткого определения "откуда берётся" не нужна для MVP; появится как честная агрегация (% MASTERED от общего словаря) когда будет что агрегировать.

## 6. Сценарии как независимые модули (с первого дня, не после MVP)

```
programs/
    market.py       # реализован в v0.1
    clinic.py        # заглушка/stub, не реализован
    coffee.py        # заглушка/stub
    rental.py         # заглушка/stub
```

Принцип: новый сценарий = новый файл programs/*.py с собственным Program (набор Step'ов + normalize_output словарь исходов), без изменений в daily_session, WordStateService или ядре. select_mode знает только про список зарегистрированных Program по имени сценария — не про их внутреннюю структуру. В v0.1 реализован ровно один (market.py) — остальные существуют только как имена файлов, чтобы архитектура не переписывалась при добавлении второго сценария.

## 7. Living Vietnam — независимый sidecar-поток

Явно НЕ часть daily_session FSM. Отдельный, гораздо более простой поток:

```
daily_culture_tip[TOOL]  -> одно сообщение в день (слово/фраза + культурная заметка)
```

Общее с daily_session — только дата отправки (не пересекать в одном execution/trace). Никакого SRS, никакого WordStateService, никакой оценки ответа — чисто информационное сообщение. Причина держать отдельно: если тут появится баг или LLM сгенерирует что-то странное, это не должно иметь возможности сломать или задержать основной обучающий цикл.

## 8. Данные (минимум для MVP)

- users — telegram_id, created_at, active_scenario
- known_words — user_id, word, state (WordState enum: UNKNOWN|INTRODUCED|LEARNING|KNOWN) — владелец: WordStateService
- review_schedule — user_id, word, srs_weight, next_review_at, last_result — владелец: ReviewScheduler
- sessions — user_id, trace_id, started_at, mode, completed_at
- (execution_traces/canonical_hash — переиспользовать llm-nano-vm схему как есть, не изобретать заново)

tone_errors из v0.1 убран из MVP data model — если тон не в MVP (см. п.1), таблица под него не нужна сейчас; появится вместе с ASR в post-MVP.

## 9. Telegram UX (happy path, v0.1)

```
/start -> onboarding (1 вопрос: "зачем вьетнамский" -> сценарий по умолчанию "рынок")
/lesson (или ежедневный push) -> daily_session Program
  -> 3 карточки (текст, БЕЗ voice в v0.1) -> ответ пользователя текстом
  -> тоновый quiz (выбор из 4 вариантов тона для 1 слова, не ASR)
  -> мини-диалог по сценарию market (2-4 реплики, normalize_output -> completed/partial/failed)
  -> саммари: "выучено X слов, streak N дней"
/progress -> known_words по состояниям (INTRODUCED/LEARNING/KNOWN count) + streak
```

Отдельно, вне daily_session: daily_culture_tip — push без команды, по расписанию.

## 10. Стек

- llm-nano-vm как execution-ядро (тот же движок, что и в остальной экосистеме — не изобретать второй runtime)
- Python: WordStateService (enum + transition table) + ReviewScheduler (веса/даты) — оба не nano-vm Step'ы
- aiogram 3 (паттерн из Tarot-Nano-Bot — переиспользовать i18n.py, database.py WAL)
- LiteLLMAdapter -> Vibecode/Groq, тот же паттерн что везде
- SQLite WAL (не Postgres — нагрузка минимальна для личного проекта на старте)

## 11. Что режем в MVP (explicit non-goals v0.1)

- Никакого voice/ASR — текстовый тоновый quiz (выбор из 4 вариантов) вместо распознавания произношения.
- Никакой библиотеки контента (LingQ-style importer) — фиксированный набор из ~50 слов + 1 сценарий (рынок) вручную.
- Никакой персонализации "5 целей" из исходного черновика — один персонаж, один сценарий.
- Никакой монетизации — считать чисто личным инструментом до proof, что loop работает на самом авторе минимум 30 дней подряд.
- Никаких микро-историй (карточка->история->диалог) — требует открытой content-генерации под known_words пользователя, не вписывается в текущий normalize_output-контракт. v0.2+.
- Execution trace analytics (где чаще ошибается, скорость обучения) — идея верная, но зависит от накопленного объёма сессий; backlog-пункт с явной зависимостью "N дней данных", не MVP.

## 12. Риски / открытые вопросы

- Текстовый тоновый quiz вместо ASR — сознательно НЕ заявляется как "решение тонового фидбека", а как временная заглушка, чтобы не жертвовать честностью MVP-гипотезы (см. п.1).
- Совмещение с nano-vm core CI — этот репо должен быть отдельным (аналог Tarot-Nano-Bot), не трогать основной nano_vm/nano-vm-mcp release cycle.
- Личный проект = нет внешнего давления по срокам — явный риск бесконечного low-priority фонового трека без сдачи MVP. Гейт: "30 дней личного использования" — если нет, проект не двигается дальше v0.1.

## 13. Следующие шаги (по порядку, не параллельно)

1. word_fsm.md — один документ, две секции: (a) WordStateService — состояния UNKNOWN/INTRODUCED/LEARNING/KNOWN, разрешённые переходы, критерий LEARNING->KNOWN; (b) ReviewScheduler — SRS-веса, интервалы, due-критерий. До этого шага daily_session Program не проектируется в деталях — она бессмысленна без готового домена, который вызывает.
2. Зафиксировать 50 слов + 1 сценарий (market) вручную, markdown-список, без кода.
3. Ручной прогон методики 3 дня в чате (без бота, без FSM-кода) — проверить, что сама последовательность карточка->тоновый quiz->мини-диалог держит внимание.
4. Только после 1-3 — код: WordStateService -> daily_session Program -> aiogram-обвязка.
