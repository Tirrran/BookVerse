# BookVerse — умный поиск по книгам

Решение для кейса **«Умный поиск по книгам»** (направление «Искусственный интеллект»).

Проект реализует локальный гибридный режим:  
**алгоритмический поиск + локальная LLM (Ollama) + проверка ответа по цитатам**.

---

## Содержание

- [1. Кратко о проекте](#1-кратко-о-проекте)
- [2. Быстрый старт](#2-быстрый-старт)
- [3. Возможности под критерии конкурса](#3-возможности-под-критерии-конкурса)
- [4. Как работает гибридный режим](#4-как-работает-гибридный-режим)
- [5. Подробный запуск (вкладки)](#5-подробный-запуск-вкладки)
- [6. Работа через интерфейс (демо-сценарий)](#6-работа-через-интерфейс-демо-сценарий)
- [7. API-эндпоинты](#7-api-эндпоинты)
- [8. Формат ответов и метаданные качества](#8-формат-ответов-и-метаданные-качества)
- [9. Переменные окружения](#9-переменные-окружения)
- [10. Структура проекта](#10-структура-проекта)
- [11. Проверка по критериям жюри](#11-проверка-по-критериям-жюри)
- [12. Troubleshooting](#12-troubleshooting)

---

## 1. Кратко о проекте

BookVerse — это сервис, который:
1. Загружает книги (`.txt` и `.fb2`);
2. Находит релевантные фрагменты по запросу;
3. Отвечает на вопросы с обязательными цитатами-основаниями;
4. Строит расширенную карточку героя, таймлайн и граф связей персонажей;
5. Показывает метрики качества ответа (grounding/confidence).

Проект не использует внешние AI API:  
для генерации применяется только **локальная LLM через Ollama** (или fallback в алгоритм).

---

## 2. Быстрый старт

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Запуск backend:

```bash
export BOOKVERSE_DISABLE_AUTH=true
export BOOKVERSE_ALGO_ONLY=false
export BOOKVERSE_LOCAL_LLM_ENABLED=true
uvicorn server:app --host 127.0.0.1 --port 8000
```

Запуск frontend (во втором терминале):

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
python3 -m http.server 5500
```

Открыть:
- `http://127.0.0.1:5500/index.html`

---

## 3. Возможности под критерии конкурса

### Основная функциональность (поиск + ответы)
- Гибридный ранжировщик: `BM25 + char n-gram + hash-embedding + RRF`.
- Поиск фрагментов с источником: книга/глава/строки.
- Ответы по книге с цитатами-основаниями.
- Честный отказ при нехватке данных.

### Добавление и обработка книг
- Загрузка пользовательских книг в библиотеку (`.txt`, `.fb2`).
- Отдельный case-режим для загрузки `.txt`.
- Разбиение на чанки, определение глав, индексация.

### Удобство интерфейса
- Интерфейс чтения + боковая панель инструментов.
- Поиск фрагментов и Q&A из вкладки «Инструменты».
- Переход к найденному месту прямо в ридере.

### Качество кода/архитектуры
- Backend на `FastAPI`, frontend на чистом JS.
- Разделение retrieval, answer synthesis, quality checks.
- Кэширование поиска/ответов и инвалидация при изменении данных.

### Оформление репозитория
- Подробный README (этот файл) с запуском, API, сценариями, критериями.

---

## 4. Как работает гибридный режим

1. **Retrieval**: выбираются релевантные фрагменты из книги(книг).  
2. **Алгоритмический черновик**: строится базовый ответ по интенту вопроса.  
3. **LLM-этап (локально)**: ответ улучшается и переформулируется.  
4. **Grounding-check**: проверка, что финальный ответ опирается на цитаты.  
5. **Fallback**: если LLM недоступна/ответ слабый — возвращается алгоритмический ответ.

Дополнительно:
- анти-«общие» фильтры (чтобы убрать пустые формулировки);
- интент-шаблоны (сюжет, действия героя, мотивация, отношения, глава и т.д.);
- confidence-оценка с причинами.

---

## 5. Подробный запуск (вкладки)

<details open>
<summary><b>Вкладка 1 — Самый простой запуск через скрипт</b></summary>

Если зависимости уже установлены:

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
./run_backend.sh
```

Во втором терминале:

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
python3 -m http.server 5500
```

</details>

<details>
<summary><b>Вкладка 2 — Ручной запуск backend</b></summary>

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
source .venv/bin/activate

export BOOKVERSE_DISABLE_AUTH=true
export BOOKVERSE_ALGO_ONLY=false
export BOOKVERSE_LOCAL_LLM_ENABLED=true
export BOOKVERSE_LOCAL_LLM_MODEL=gemma3:1b
export BOOKVERSE_LOCAL_LLM_FALLBACK_MODELS="gemma3:1b,qwen2.5:1.5b-instruct"

uvicorn server:app --host 127.0.0.1 --port 8000
```

</details>

<details>
<summary><b>Вкладка 3 — Запуск локальной LLM (Ollama)</b></summary>

```bash
ollama serve
```

И один раз загрузить модели:

```bash
ollama pull gemma3:1b
ollama pull qwen2.5:1.5b-instruct
```

Рекомендация для MacBook Air M1: начать с `gemma3:1b`.

</details>

<details>
<summary><b>Вкладка 4 — Если порт 8000 занят</b></summary>

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

</details>

---

## 6. Работа через интерфейс (демо-сценарий)

1. Откройте `library.html` или `index.html`.
2. Загрузите книгу (`.txt` / `.fb2`).
3. Откройте книгу в `reader.html`.
4. В меню откройте **Инструменты → Умный поиск по книгам**.

### Поиск фрагментов
- Введите запрос.
- При необходимости включите строгие фильтры:
  - `Точная фраза`,
  - `Только целые слова`,
  - `Глава`.

### Ответ на вопрос
- Введите вопрос (или используйте кнопки-подсказки).
- Получите:
  - ответ,
  - цитаты-основания,
  - карточку героя,
  - таймлайн,
  - граф персонажей,
  - метрики качества.

---

## 7. API-эндпоинты

### Пользовательские книги
- `POST /api/books/search`
- `POST /api/books/ask`
- `POST /api/books/summary`
- `POST /api/books/quiz`

### Case-режим
- `POST /api/case/upload`
- `GET /api/case/books`
- `POST /api/case/search`
- `POST /api/case/ask`

### Примеры

Поиск:

```bash
curl -X POST "http://127.0.0.1:8000/api/case/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query":"где герой говорит о вере",
    "top_k":5,
    "strict_phrase":false,
    "whole_words":true,
    "chapter_number":2
  }'
```

Вопрос-ответ:

```bash
curl -X POST "http://127.0.0.1:8000/api/case/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question":"Что делал главный герой?",
    "top_k":8,
    "citations_k":4,
    "answer_mode":"hybrid",
    "local_model":"gemma3:1b"
  }'
```

---

## 8. Формат ответов и метаданные качества

В `ask`-ответах, помимо `answer` и `citations`, возвращаются:

- `intent` — распознанный тип вопроса;
- `main_characters` — ключевые персонажи;
- `character_card`:
  - `name`, `gender`, `role`,
  - `traits`, `actions`, `goals`, `relations`,
  - `evolution`, `chapter_refs`,
  - `mode` (`llm` / `algorithm`);
- `timeline` — события по главам;
- `character_graph` — узлы и связи персонажей;
- `grounding_status`, `grounding_score`, `grounding_warning`;
- `confidence`, `confidence_label`, `confidence_reasons`;
- `answer_mode_note` — примечание по гибридному этапу.

---

## 9. Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---:|---|
| `BOOKVERSE_DISABLE_AUTH` | `true` | Отключить авторизацию для локального демо |
| `BOOKVERSE_ALGO_ONLY` | `false` | Принудительно алгоритмический режим |
| `BOOKVERSE_LOCAL_LLM_ENABLED` | `true` | Включить LLM-этап |
| `BOOKVERSE_LOCAL_LLM_BASE_URL` | `http://127.0.0.1:11434` | URL Ollama |
| `BOOKVERSE_LOCAL_LLM_MODEL` | `gemma3:1b` | Основная локальная модель |
| `BOOKVERSE_LOCAL_LLM_FALLBACK_MODELS` | `gemma3:1b` | Резервные модели через запятую |
| `BOOKVERSE_LOCAL_LLM_TIMEOUT_SEC` | `90` | Таймаут запроса к LLM |
| `BOOKVERSE_LOCAL_LLM_MAX_CITATIONS` | `6` | Лимит цитат в prompt |
| `BOOKVERSE_RRF_K` | `60` | Параметр RRF rerank |
| `BOOKVERSE_SEARCH_CACHE_TTL_SEC` | `600` | TTL кэша поиска |
| `BOOKVERSE_ASK_CACHE_TTL_SEC` | `600` | TTL кэша ответов |
| `BOOKVERSE_RESULT_CACHE_MAX_ITEMS` | `250` | Размер кэша |
| `BOOKVERSE_CACHE_SCHEMA_VERSION` | `2026-03-23-v2` | Версия схемы кэша |

---

## 10. Структура проекта

```text
BookVerse (3)/
├─ server.py                  # FastAPI backend, retrieval + QA + metadata
├─ run_backend.sh             # быстрый запуск backend
├─ reader.html                # ридер
├─ library.html               # библиотека
├─ index.html                 # точка входа
├─ scripts/
│  ├─ reader.js               # ридер, главы, поиск, навигация
│  ├─ menu.js                 # боковое меню
│  └─ ...                     
├─ tools/
│  ├─ book-qa.html            # UI блока "Умный поиск по книгам"
│  ├─ bookai.js               # логика поиска/ответов/визуализаций
│  ├─ bookai.css              # стили блока
│  └─ eval_general_questions.py
└─ README.md
```

---

## 11. Проверка по критериям жюри

### 0–6: Качество основной функциональности
- Проверить 10–15 вопросов разных типов:
  - сюжет,
  - события по главам,
  - действия/мотивация героя,
  - связи персонажей.
- Убедиться, что есть цитаты и честные отказы, где данных нет.

### 0–3: Добавление и обработка книг
- Загрузить `.txt` и `.fb2`.
- Проверить, что книги появляются в библиотеке и участвуют в поиске.

### 0–4: Удобство интерфейса
- Поиск фрагментов с фильтрами.
- Q&A + карточка героя + таймлайн + граф.
- Переход к фрагменту в ридере.

### 0–2: Качество кода и архитектуры
- Четко разделены retrieval / synthesis / grounding / UI.
- Есть кэш и fallback-механизмы.

### 0–2: Оформление репозитория
- Есть подробный README с запуском, API и сценариями.

---

## 12. Troubleshooting

<details>
<summary><b>Ошибка: address already in use (127.0.0.1:8000)</b></summary>

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

</details>

<details>
<summary><b>Ошибка Ollama: model not found</b></summary>

```bash
ollama pull gemma3:1b
```

</details>

<details>
<summary><b>Ответ слишком общий</b></summary>

- Вопрос лучше формулировать конкретно (персонаж + действие + глава/эпизод).
- Используйте фильтр по главе в поиске.
- Проверьте, что книга действительно содержит нужный эпизод.

</details>

<details>
<summary><b>Не открывается переход к фрагменту</b></summary>

- Убедитесь, что книга открыта в `reader.html`.
- Проверьте, что у цитаты есть `chapter`/`line_start`/`char_start`.
- Перезагрузите страницу ридера.

</details>

---

## License

Учебный/конкурсный проект.

