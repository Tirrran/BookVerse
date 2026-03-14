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

## Гайд на запуск (каждый раз)

Если зависимости уже установлены, достаточно этих шагов:

1. Backend (терминал 1):

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
source .venv/bin/activate
export BOOKVERSE_DISABLE_AUTH=true
export BOOKVERSE_ALGO_ONLY=true
uvicorn server:app --host 127.0.0.1 --port 8000
```

2. Frontend (терминал 2):

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
python3 -m http.server 5500
```

3. Открыть сайт:

- `http://127.0.0.1:5500/index.html`

4. Если порт `8000` занят:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

## Как пользоваться (по заданию)

1. В библиотеке загрузите книгу (лучше `.txt`).
2. Откройте меню `Инструменты`.
3. Выберите `Умный поиск по книгам`.
4. Используйте:
   - **Поиск фрагментов**: запрос вида «Найди, где говорится про ...»;
   - **Ответ на вопрос**: вопрос по тексту книги.
5. Проверяйте цитаты-основания под ответом.

## Проверка по критериям жюри

Ниже быстрый способ показать соответствие каждому критерию:

1. Качество основной функциональности (поиск и ответы)
- Проверьте `Поиск фрагментов` на 3-5 запросах по загруженной книге.
- Проверьте `Ответ на вопрос` на общих и главовых вопросах.
- Ожидаемое поведение: ответ с цитатами или честный отказ, если данных нет.

2. Добавление и обработка книг
- Загрузите `.txt` (и при необходимости `.fb2`) через интерфейс библиотеки.
- Убедитесь, что книга появляется в списке и участвует в поиске/ответах.

3. Удобство интерфейса
- Основные сценарии доступны из UI: загрузка книги, поиск, вопрос-ответ, просмотр цитат.
- Вкладка `Инструменты` содержит функции по кейсу и работает без внешних AI API.

4. Качество кода и архитектуры
- Backend и frontend разделены, алгоритмы поиска/ответов вынесены в серверную логику.
- Есть скрипт оценки качества для повторяемой проверки.

5. Оформление репозитория
- В корне есть `README.md` с описанием, запуском и примерами.
- Есть тестовые команды API и сценарий автоматической оценки.

### Быстрая автоматическая проверка качества

```bash
cd "/Users/kirill/Documents/Code/BookVerse (3)"
source .venv/bin/activate
python tools/eval_general_questions.py \
  --base-url http://127.0.0.1:8000 \
  --book-file "/Users/kirill/Downloads/Leskov_Nikolai__Na_krau_sveta_www.Litmir.net_95240.txt" \
  --output /tmp/bookverse_eval_report.json
```

Скрипт выводит:
- `found_rate`;
- `avg_citations`;
- `avg_grounding`;
- `chapter_accuracy`;
- `heuristic_ok_rate`.

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
