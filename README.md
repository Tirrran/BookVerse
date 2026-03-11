# BookVerse: умный поиск по книгам

Решение под кейс **«Умный поиск по книгам»**.

Реализовано:
- загрузка книг пользователя (`.txt`, `.fb2`);
- поиск релевантных фрагментов (3-5 результатов);
- ответ на вопрос по книгам с цитатами-основаниями;
- честный отказ, если данных недостаточно.

## Важно

Проект работает в **алгоритмическом режиме** (без внешних AI API):
- лексический ранжировщик по чанкам текста;
- извлекающий (extractive) ответ из найденных фрагментов.

По умолчанию включен режим:
- `BOOKVERSE_ALGO_ONLY=true`

OpenAI-зависимые legacy-эндпоинты в этом режиме отключены.

## Стек

- Backend: `FastAPI`, `SQLAlchemy`
- Frontend: текущий дизайн сайта (`library.html`, `reader.html`)
- Алгоритмы: токенизация + ранжирование фрагментов + extractive answer

## Быстрый запуск

1. Установить зависимости:

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Запустить backend:

```bash
export BOOKVERSE_DISABLE_AUTH=true
export BOOKVERSE_ALGO_ONLY=true
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

3. Запустить frontend (во втором терминале):

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
python3 -m http.server 5500
```

4. Открыть:

- `http://127.0.0.1:5500/library.html`

## Как пользоваться (по заданию)

1. В библиотеке загрузите книгу (лучше `.txt`).
2. Откройте меню `Инструменты`.
3. Выберите `Умный поиск по книгам`.
4. Используйте:
   - **Поиск фрагментов**: запрос вида «Найди, где говорится про ...»;
   - **Ответ на вопрос**: вопрос по тексту книги.
5. Проверяйте цитаты-основания под ответом.

## Ключевые API (алгоритмические)

Для книг пользователя:
- `POST /api/books/search`
- `POST /api/books/ask`

Для технического case-интерфейса:
- `POST /api/case/upload`
- `POST /api/case/search`
- `POST /api/case/ask`
- `GET /api/case/books`

## Примеры

Поиск:

```bash
curl -X POST "http://127.0.0.1:8000/api/case/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"где говорится о дуэли", "top_k":5}'
```

Вопрос-ответ:

```bash
curl -X POST "http://127.0.0.1:8000/api/case/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"Что произошло после дуэли?", "top_k":5, "citations_k":3}'
```

## Оценка качества (eval)

Добавлен скрипт автоматической проверки общих вопросов:

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
source .venv/bin/activate
python tools/eval_general_questions.py \
  --base-url http://127.0.0.1:8000 \
  --book-file "/path/to/book.txt" \
  --output /tmp/bookverse_eval_report.json
```

Что считает скрипт:
- `found_rate`;
- `avg_citations`;
- `avg_grounding` (перекрытие ответа с цитатами);
- `chapter_accuracy` для вопросов по главам;
- `heuristic_ok_rate` для тематики/отношений/глав.
