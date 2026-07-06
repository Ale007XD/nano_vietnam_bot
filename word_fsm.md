# word_fsm.md — доменная модель: WordStateService + ReviewScheduler

Один документ, две ответственности (см. nanovietnam_spec v0.3 п.4). Это единственный источник истины
для домена — код в `nano_vietnam/domain.py` реализует ровно то, что здесь описано, не более и не менее.

---

## 1. WordStateService — качественное состояние знания слова

### 1.1 Состояния

```
UNKNOWN     — слово не показано пользователю
INTRODUCED  — слово показано впервые, ещё не было ни одной попытки ответа
LEARNING    — минимум одна попытка ответа сделана, слово ещё не освоено
KNOWN       — критерий освоения выполнен (см. 1.3)
```

### 1.2 События

```
SHOWN    — карточка со словом показана пользователю (не зависит от ответа)
SUCCESS  — пользователь ответил верно
FAIL     — пользователь ответил неверно
```

### 1.3 Таблица переходов (полная, тотальная — WordStateService.transition это реализует)

| Состояние | Событие | Новое состояние | consecutive_successes |
|---|---|---|---|
| UNKNOWN | SHOWN | INTRODUCED | 0 |
| UNKNOWN | SUCCESS / FAIL | — | **invalid, raise ValueError** (нельзя отвечать на непоказанное слово) |
| INTRODUCED | SUCCESS | LEARNING | 1 |
| INTRODUCED | FAIL | LEARNING | 0 |
| INTRODUCED | SHOWN | — | **invalid, raise ValueError** (уже показано) |
| LEARNING | SUCCESS | LEARNING, если streak < 3; **KNOWN, если streak == 3** | streak = n+1 |
| LEARNING | FAIL | LEARNING | 0 (сброс streak) |
| LEARNING | SHOWN | — | **invalid, raise ValueError** |
| KNOWN | SUCCESS | KNOWN | n+1 (не ограничено сверху, не влияет на поведение) |
| KNOWN | FAIL | LEARNING | 0 (**демоция** — забывание) |
| KNOWN | SHOWN | — | **invalid, raise ValueError** |

`MASTERY_THRESHOLD = 3` — три успешных ответа подряд в состоянии LEARNING переводят слово в KNOWN.
Число зафиксировано как константа в коде (`WordStateService.MASTERY_THRESHOLD`), меняется в одном месте.

### 1.4 Явные инварианты

- Функция **тотальна**: для каждой пары (состояние, событие) либо определён переход, либо явный `raise ValueError`
  — никогда не молчаливый no-op и не возврат текущего состояния как "как бы обработали". Тот же принцип,
  что normalize_output в nano-vm (Authority Projection Principle, DECISIONS.md 2026-06-19).
- `FAIL` **никогда** не переводит слово в состояние хуже LEARNING (то есть не откатывает в UNKNOWN/INTRODUCED)
  — забывание есть, полная потеря прогресса нет.
- WordStateService не знает о времени, датах, весах — это исключительно зона ReviewScheduler (см. §2).
- WordStateService не имеет побочных эффектов (нет DB-вызовов внутри) — чистая функция,
  тестируется без БД и без event loop.

---

## 2. ReviewScheduler — когда показать слово снова

Не знает о WordState вообще — только о датах/весах/последнем результате. Реализует SM-2-подобный
(упрощённый) алгоритм интервальных повторений.

### 2.1 Данные на слово

```
srs_weight: int        — счётчик успешных повторов подряд (сбрасывается на FAIL)
next_review_at: datetime
last_result: "SUCCESS" | "FAIL" | None
```

### 2.2 Правила

```
on SUCCESS:
    new_weight = srs_weight + 1
    next_review_at = now + 2**new_weight дней   (1, 2, 4, 8, 16... дней)

on FAIL:
    new_weight = 0
    next_review_at = now + 10 минут              (быстрый повтор в той же/следующей сессии)
```

### 2.3 due_words

Слово входит в выборку `get_due_words(user_id)`, если `next_review_at <= now`. Новое слово
(`add_new_word`) получает `next_review_at = now` — доступно для повтора сразу же после первого показа.

---

## 3. Взаимодействие в рамках одной сессии (daily_session)

Порядок вызовов на одном ответе пользователя (`score_answer`):

```
1. WordStateService.transition(current_knowledge, event)   — чистая функция, без побочных эффектов
2. persist новое WordKnowledge в known_words                — в рамках ОДНОЙ db-транзакции
3. ReviewScheduler.schedule_next(...)                        — в той же db-транзакции
4. commit одной транзакцией; любое исключение на любом из шагов 2-3 откатывает оба
```

Это требование, не рекомендация — нарушение (два независимых commit) было
задокументированной ошибкой в Sieshka (DECISIONS.md 2026-07-01, "Tool-authoring: side-effect
session boundary") и не должно повториться здесь.
