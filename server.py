from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Form,
    Header,
    Depends,
    Body,
)
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import uuid
import logging
import uvicorn
import xml.etree.ElementTree as ET
import os
import json
import re
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

try:
    import openai
except ModuleNotFoundError:
    openai = None

# from diffusers import AutoPipelineForText2Image
import requests
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from passlib.hash import bcrypt
from datetime import datetime
import jwt

# Удалим старую базу и создадим новую

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if openai and OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
else:
    client = None

SECRET_KEY = os.getenv("BOOKVERSE_SECRET_KEY", "change-me-in-env")
AUTH_DISABLED = os.getenv("BOOKVERSE_DISABLE_AUTH", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALGORITHM_ONLY_MODE = os.getenv("BOOKVERSE_ALGO_ONLY", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if AUTH_DISABLED:
        return get_or_create_guest_user(db)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except jwt.PyJWTError as e:
        logger.warning("Token decode error: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")


async def generate_image(
    prompt, height=512, width=512, steps=10, guidance=7.5, output_path="img.png"
):
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="OpenAI client is not configured. Set OPENAI_API_KEY.",
        )

    """# Очистка памяти перед началом
    gc.collect()
    torch.mps.empty_cache()

    # Генерация изображения
    image = pipe(
        prompt,
        height=height,           # Оптимальное разрешение для MPS
        width=width,
        num_inference_steps=steps,  # Количество шагов диффузии
        guidance_scale=guidance    # Вес подсказки
    ).images[0]

    # Сохранение изображения
    image.save(output_path)

    # Очистка памяти после завершения
    torch.mps.empty_cache()
    gc.collect()"""

    response = await client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )

    url = response.data[0].url

    try:
        # Отправляем GET-запрос на URL изображения
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Проверка на успешность запроса

        # Сохраняем файл локально
        with open(output_path, "wb") as image_file:
            for chunk in response.iter_content(1024):  # Скачиваем по частям
                image_file.write(chunk)

        print(f"Изображение успешно сохранено в {output_path}")
    except Exception as e:
        print(f"Ошибка при скачивании изображения: {e}")

    return output_path


app = FastAPI()

# Полностью отключаем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Словарь для хранения обработчиков и идентификаторов потоков
class_dict = {}
thread_cache = {}  # Кеш для хранения `thread_id` на основе пути к файлу


class EventHandler:
    def __init__(self, stream):
        self.messages = []
        self.done = False
        self.stream = stream

    async def updating_message(self):
        async for event in self.stream:
            try:
                if "MessageDeltaEvent" in str(event.data):
                    if event.data.object == "thread.message.delta":
                        self.messages.append(event.data.delta.content[0].text.value)
                elif "Message" in str(event.data) and event.data.status in [
                    "completed",
                    "failed",
                ]:
                    self.done = True
                    if event.data.status == "completed":
                        logging.info("Поток завершен")
                    elif event.data.status == "failed":
                        logging.warning("Поток завершен с ошибкой")
                        self.messages = ["Произошла ошибка, повторите запрос"]
            except Exception as e:
                logging.error(f"Ошибка в обработке события: {e}")

    async def get_messages(self):
        await asyncio.sleep(1.25)
        return self.done, "".join(self.messages)


# thread_cache будет хранить `thread_id` на основе пути к файлу и типа генерации
thread_cache = {}  # Структура: {file_name: {"book": thread_id, "summarize": thread_id, ...}}


async def get_id_class(text_file_path, prompt, add_prompt, type_generation, file_name):
    try:
        if client is None:
            raise RuntimeError("OpenAI client is not configured")
        print(text_file_path, prompt, add_prompt, type_generation, file_name)

        if type_generation == "quiz":
            asst_id = "asst_pr2ihTRvgoh3We6VztlPJrb2"
            quiz_prompt = (
                f"Сделай викторину по загруженному файлу. Сложность викторины: {prompt}"
            )
        elif type_generation == "book":
            asst_id = "asst_ar4Hdu78ltGm9zJssFYTLq7N"
            quiz_prompt = prompt
        else:
            asst_id = "asst_Aa2QXjHzQkjmzUMC2vFDOOGf"
            quiz_prompt = prompt
        print(prompt)
        print(
            file_name in thread_cache and "book" in thread_cache.get(file_name),
            file_name,
            thread_cache,
        )
        # Проверка существующего потока по имени файла и типу генерации
        if file_name in thread_cache and type_generation in thread_cache[file_name]:
            thread_id = thread_cache.get(file_name).get(type_generation)
            print(
                f"Повторное использование потока: {thread_id} для типа генерации: {type_generation}"
            )
            logging.info(f"Используем существующий поток: {thread_id}")
        else:
            # Если поток не существует, создаем новый
            message_file = await client.files.create(
                file=open(text_file_path, "rb"), purpose="assistants"
            )
            logging.info(f"Создан файл: {message_file.id}")

            # Создаем новый поток для файла
            thread = await client.beta.threads.create(
                messages=[
                    {
                        "role": "user",
                        "content": quiz_prompt,
                        "attachments": [
                            {
                                "file_id": message_file.id,
                                "tools": [{"type": "file_search"}],
                            }
                        ],
                    }
                ]
            )
            thread_id = thread.id

            # Сохраняем `thread_id` в кеш для данного файла и типа генерации
            if file_name not in thread_cache:
                thread_cache[file_name] = {}
            thread_cache[file_name][type_generation] = thread_id
            logging.info(
                f"Создан новый поток: {thread_id} для типа генерации: {type_generation}"
            )

            # Настройка ассистента с использованием созданного потока
            assistant = await client.beta.assistants.update(
                assistant_id=asst_id,
                tool_resources={
                    "file_search": {
                        "vector_store_ids": [
                            thread.tool_resources.file_search.vector_store_ids[0]
                        ]
                    }
                },
            )

        # Запуск потока для ответа
        stream = await client.beta.threads.runs.create(
            thread_id=thread_id,
            additional_messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            additional_instructions=f"Отвечай учитывая просьбу от пользователя: {add_prompt}"
            if add_prompt
            else "",
            assistant_id=asst_id,
            stream=True,
        )

        # Создаем обработчик и запускаем обновление сообщений
        handler = EventHandler(stream)
        asyncio.create_task(handler.updating_message())

        # Создаем уникальный идентификатор для класса и сохраняем обработчик в словаре
        id_class = uuid.uuid4().hex
        class_dict[id_class] = handler
        return id_class, handler
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return None, None


# Создаем временную папку для хранения файлов
os.makedirs("/tmp/fb2_files", exist_ok=True)
os.makedirs("/tmp/txt_files", exist_ok=True)


# Функция для извлечения текста из FB2
def extract_text_from_fb2(fb2_path):
    try:
        tree = ET.parse(fb2_path)
        root = tree.getroot()
        namespace = {"fb2": "http://www.gribuser.ru/xml/fictionbook/2.0"}

        texts = []
        for section in root.findall(".//fb2:section", namespace):
            for elem in section.findall(".//fb2:*", namespace):
                if elem.tag == "{http://www.gribuser.ru/xml/fictionbook/2.0}p":
                    texts.append("".join(elem.itertext()))
        return preprocess_book_text("\n".join(texts))
    except Exception as e:
        logging.error(f"Ошибка при извлечении текста из FB2: {e}")
        return ""


# Создаем базу данных
Base = declarative_base()
engine = create_engine("sqlite:///bookverse.db")
SessionLocal = sessionmaker(bind=engine)


# Модель пользователя
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)
    email = Column(String, unique=True)
    books = relationship("Book", back_populates="user")
    stats = relationship("UserStats", back_populates="user", uselist=False)


# Модель книги
class Book(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    original_filename = Column(String)
    stored_filename = Column(String)
    file_path = Column(String)
    upload_date = Column(DateTime, default=datetime.utcnow)
    file_size = Column(Integer)
    file_type = Column(String)
    progress = Column(Integer, default=0)
    last_read = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="books")


# Модель статистики пользователя
class UserStats(Base):
    __tablename__ = "user_stats"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    books_read = Column(Integer, default=0)
    books_in_progress = Column(Integer, default=0)
    favorite_genres = Column(String)  # Храним как JSON строку
    user = relationship("User", back_populates="stats")


# Создаем таблицы
Base.metadata.create_all(engine)


def get_or_create_guest_user(db: Session) -> User:
    guest_user = db.query(User).filter(User.username == "guest").first()
    if guest_user:
        return guest_user

    username = "guest"
    email = "guest@bookverse.local"
    suffix = 1
    while db.query(User).filter(User.username == username).first() or db.query(User).filter(
        User.email == email
    ).first():
        username = f"guest{suffix}"
        email = f"guest{suffix}@bookverse.local"
        suffix += 1

    guest_user = User(
        username=username,
        email=email,
        password_hash="auth-disabled",
    )
    db.add(guest_user)
    db.commit()
    db.refresh(guest_user)
    return guest_user


CASE_STORAGE_DIR = Path("case_books")
CASE_META_FILE = CASE_STORAGE_DIR / "index.json"
CASE_CHUNK_CACHE: dict[str, dict[str, Any]] = {}
USER_BOOK_CHUNK_CACHE: dict[str, dict[str, Any]] = {}
TOKEN_REGEX = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
MIN_FRAGMENT_SCORE = 0.08
SEPARATOR_LINE_REGEX = re.compile(r"^\s*[-=_*~]{6,}\s*$")
BOOK_TEXT_LINE_NOISE_MARKERS = (
    "litru.ru",
    "litmir.net",
    "электронная библиотека",
    "адрес книги:",
    "название книги:",
    "жанр:",
    "по вопросам приобретения",
)


class CaseSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class CaseAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    citations_k: int = Field(default=3, ge=1, le=5)


class UserSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    book_ids: list[int] = Field(default_factory=list)


class UserAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    citations_k: int = Field(default=3, ge=1, le=5)
    book_ids: list[int] = Field(default_factory=list)


def ensure_case_storage() -> None:
    CASE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not CASE_META_FILE.exists():
        CASE_META_FILE.write_text("{}", encoding="utf-8")


def load_case_metadata() -> dict[str, dict[str, Any]]:
    ensure_case_storage()
    try:
        data = json.loads(CASE_META_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    return data if isinstance(data, dict) else {}


def save_case_metadata(data: dict[str, dict[str, Any]]) -> None:
    ensure_case_storage()
    CASE_META_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_service_or_meta_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    lowered = stripped.lower().replace("ё", "е")
    if SEPARATOR_LINE_REGEX.match(stripped):
        return True
    if any(marker in lowered for marker in BOOK_TEXT_LINE_NOISE_MARKERS):
        return True
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    return False


def preprocess_book_text(text: str) -> str:
    if not text:
        return ""

    normalized = (
        text.replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\xa0", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    cleaned_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        if is_service_or_meta_line(raw_line):
            continue
        line = re.sub(r"\[\d{1,3}\]", "", raw_line)
        line = re.sub(r"\s+", " ", line).strip()
        cleaned_lines.append(line if line else "")

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


def decode_uploaded_txt(content: bytes) -> str:
    for encoding in ("utf-8", "cp1251", "utf-16", "latin-1"):
        try:
            return preprocess_book_text(content.decode(encoding))
        except UnicodeDecodeError:
            continue
    return preprocess_book_text(content.decode("utf-8", errors="replace"))


def read_txt_file(path: str) -> str:
    for encoding in ("utf-8", "cp1251", "utf-16", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as file:
                return preprocess_book_text(file.read())
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    with open(path, "r", encoding="utf-8", errors="replace") as file:
        return preprocess_book_text(file.read())


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_REGEX.findall(text)]


RUS_STOPWORDS = {
    "и",
    "в",
    "во",
    "не",
    "что",
    "он",
    "на",
    "я",
    "с",
    "со",
    "как",
    "а",
    "то",
    "все",
    "она",
    "так",
    "его",
    "но",
    "да",
    "ты",
    "к",
    "у",
    "же",
    "вы",
    "за",
    "бы",
    "по",
    "только",
    "ее",
    "мне",
    "было",
    "вот",
    "от",
    "меня",
    "еще",
    "нет",
    "о",
    "из",
    "ему",
    "теперь",
    "когда",
    "даже",
    "ну",
    "вдруг",
    "ли",
    "если",
    "уже",
    "или",
    "ни",
    "быть",
    "был",
    "него",
    "до",
    "вас",
    "нибудь",
    "опять",
    "уж",
    "вам",
    "ведь",
    "там",
    "потом",
    "себя",
    "ничего",
    "ей",
    "может",
    "они",
    "тут",
    "где",
    "есть",
    "надо",
    "ней",
    "для",
    "мы",
    "тебя",
    "их",
    "чем",
    "была",
    "сам",
    "чтоб",
    "без",
    "будто",
    "чего",
    "раз",
    "тоже",
    "себе",
    "под",
    "будет",
    "ж",
    "тогда",
    "кто",
    "этот",
    "того",
    "потому",
    "этого",
    "какой",
    "совсем",
    "ним",
    "здесь",
    "этом",
    "один",
    "почти",
    "мой",
    "тем",
    "чтобы",
    "нее",
    "сейчас",
    "были",
    "куда",
    "зачем",
    "всех",
    "никогда",
    "можно",
    "при",
    "наконец",
    "два",
    "об",
    "другой",
    "хоть",
    "после",
    "над",
    "больше",
    "тот",
    "через",
    "эти",
    "нас",
    "про",
    "всего",
    "них",
    "какая",
    "много",
    "разве",
    "три",
    "эту",
    "моя",
    "впрочем",
    "хорошо",
    "свою",
    "этой",
    "перед",
    "иногда",
    "лучше",
    "чуть",
    "том",
    "нельзя",
    "такой",
    "им",
    "более",
    "всегда",
    "конечно",
    "всю",
    "между",
}

RUS_STEM_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ией",
    "ией",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ее",
    "ие",
    "ые",
    "ое",
    "ей",
    "ий",
    "ый",
    "ой",
    "ем",
    "им",
    "ым",
    "ом",
    "их",
    "ых",
    "ую",
    "юю",
    "ая",
    "яя",
    "ах",
    "ях",
    "ам",
    "ям",
    "ов",
    "ев",
    "ом",
    "ем",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)

DATE_OR_YEAR_REGEX = re.compile(
    r"\\b\\d{1,2}[./-]\\d{1,2}[./-]\\d{2,4}\\b|\\b(1[0-9]{3}|20[0-9]{2})\\b"
)
CAPITALIZED_WORD_REGEX = re.compile(r"\b[А-ЯЁ][а-яё]{2,}\b")

CHAPTER_HEADING_REGEX = re.compile(
    r"(?im)^\s*(?:глава|chapter)\s+([ivxlcdm]+|\d+|[a-zа-яё-]+)\b[^\n]*"
)
CHAPTER_WORD_HINTS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
    "одиннадцат": 11,
    "двенадцат": 12,
    "тринадцат": 13,
    "четырнадцат": 14,
    "пятнадцат": 15,
    "шестнадцат": 16,
    "семнадцат": 17,
    "восемнадцат": 18,
    "девятнадцат": 19,
    "двадцат": 20,
    "тридцат": 30,
}

LOW_INFORMATION_MARKERS = (
    "по вопросам приобретения",
    "литмир",
    "www.",
    "http://",
    "https://",
    "isbn",
    "электронн",
    "rights reserved",
    "тел.",
    "содержание",
    "тираж",
    "печать офсет",
    "зак. №",
)

GENERIC_QUERY_TERMS = {
    "гер",
    "делает",
    "дела",
    "делал",
    "человек",
    "люд",
    "котор",
    "так",
    "эт",
    "это",
    "быт",
    "происход",
    "случ",
    "говор",
    "сказ",
    "поч",
    "когд",
    "как",
    "где",
    "куда",
    "откуда",
    "кто",
    "что",
    "зачем",
}

# Термины, которые сами по себе слишком расплывчаты для поиска по книге.
NON_SPECIFIC_FOCUS_TERMS = {
    "гер",
    "персонаж",
    "главн",
    "человек",
    "книг",
    "роман",
    "повест",
    "рассказ",
    "произвед",
    "сюжет",
    "событ",
    "истор",
    "част",
    "глав",
    "перв",
    "втор",
    "треть",
    "начал",
    "конец",
    "делает",
    "дела",
    "происход",
    "случ",
    "иной",
    "некотор",
    "любой",
    "кажд",
}



def normalize_token(token: str) -> str:
    normalized = token.lower().replace("ё", "е")
    if normalized.isdigit():
        return normalized

    if len(normalized) <= 3:
        return normalized

    for suffix in RUS_STEM_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 3:
            return normalized[: -len(suffix)]
    return normalized


def tokenize_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in tokenize(text):
        raw = token.lower().replace("ё", "е")
        if raw in RUS_STOPWORDS:
            continue

        term = normalize_token(raw)
        if len(term) <= 1:
            continue
        if term in RUS_STOPWORDS:
            continue
        terms.append(term)
    return terms


def line_for_offset(text: str, offset: int) -> int:
    if offset <= 0:
        return 1
    return text.count("\n", 0, min(offset, len(text))) + 1


def roman_to_int(value: str) -> int | None:
    roman = value.lower().strip()
    if not roman:
        return None

    mapping = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    prev = 0
    for char in reversed(roman):
        current = mapping.get(char)
        if current is None:
            return None
        if current < prev:
            total -= current
        else:
            total += current
            prev = current

    return total if total > 0 else None


def parse_chapter_token(token: str) -> int | None:
    value = token.strip().lower().replace("ё", "е")
    if not value:
        return None
    if value.isdigit():
        number = int(value)
        return number if number > 0 else None

    roman_number = roman_to_int(value)
    if roman_number:
        return roman_number

    for stem, number in CHAPTER_WORD_HINTS.items():
        if value.startswith(stem):
            return number

    return None


def build_chapter_spans(text: str) -> list[dict[str, Any]]:
    matches = list(CHAPTER_HEADING_REGEX.finditer(text))
    if not matches:
        return []

    spans: list[dict[str, Any]] = []
    for idx, match in enumerate(matches):
        number = parse_chapter_token(match.group(1) or "") or (idx + 1)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        spans.append(
            {
                "number": number,
                "title": match.group(0).strip(),
                "start": start,
                "end": end,
            }
        )

    return spans


def chapter_for_offset(chapter_spans: list[dict[str, Any]], offset: int) -> dict[str, Any] | None:
    if not chapter_spans:
        return None

    for span in chapter_spans:
        if span["start"] <= offset < span["end"]:
            return span

    if offset < chapter_spans[0]["start"]:
        return chapter_spans[0]

    return chapter_spans[-1]


def assign_virtual_chapters(chunks: list[dict[str, Any]]) -> None:
    if not chunks:
        return

    # Если в тексте нет явных заголовков глав, делим книгу на виртуальные части,
    # чтобы поддержать вопросы вида "что было во второй главе".
    virtual_count = min(10, max(3, len(chunks) // 25 + 1))
    total = len(chunks)
    for idx, chunk in enumerate(chunks):
        number = int(idx * virtual_count / max(1, total)) + 1
        chunk["chapter_number"] = number
        chunk["chapter_title"] = f"Часть {number}"
        chunk["virtual_chapter"] = True


def split_text_chunks(text: str, max_chars: int = 1200, overlap: int = 220):
    chunks = []
    index = 0
    chunk_id = 0
    text_len = len(text)
    chapter_spans = build_chapter_spans(text)

    while index < text_len:
        end = min(text_len, index + max_chars)
        hit_chapter_boundary = False

        if chapter_spans:
            for span in chapter_spans:
                boundary = span.get("start", 0)
                if index < boundary < end:
                    end = boundary
                    hit_chapter_boundary = True
                    break

        if end < text_len:
            split_at = text.rfind(" ", index + int(max_chars * 0.6), end)
            if split_at > index:
                end = split_at

        raw_chunk = text[index:end]
        normalized_chunk = raw_chunk.strip()
        if normalized_chunk:
            left_trim = len(raw_chunk) - len(raw_chunk.lstrip())
            right_trim = len(raw_chunk) - len(raw_chunk.rstrip())
            chunk_start = index + left_trim
            chunk_end = end - right_trim
            terms = tokenize_terms(normalized_chunk)

            chapter_info = chapter_for_offset(chapter_spans, chunk_start)
            chapter_number = chapter_info.get("number") if chapter_info else None
            chapter_title = chapter_info.get("title") if chapter_info else None

            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "text": normalized_chunk,
                    "tokens": tokenize(normalized_chunk),
                    "terms": terms,
                    "term_counts": Counter(terms),
                    "start": chunk_start,
                    "end": chunk_end,
                    "line_start": line_for_offset(text, chunk_start),
                    "line_end": line_for_offset(text, chunk_end),
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_title,
                    "virtual_chapter": False,
                }
            )
            chunk_id += 1

        next_index = end if hit_chapter_boundary else end - overlap
        if next_index <= index:
            next_index = end
        index = next_index

    if not chapter_spans:
        assign_virtual_chapters(chunks)

    return chunks


def get_case_book_chunks(book_id: str, book_meta: dict[str, Any]):
    path = book_meta.get("path", "")
    if not path or not os.path.exists(path):
        return []

    mtime = os.path.getmtime(path)
    cached = CASE_CHUNK_CACHE.get(book_id)
    if cached and cached.get("mtime") == mtime:
        return cached.get("chunks", [])

    text = read_txt_file(path)
    chunks = split_text_chunks(text)
    CASE_CHUNK_CACHE[book_id] = {"mtime": mtime, "chunks": chunks}
    return chunks


def extract_book_text(book: Book) -> str:
    path = book.file_path or ""
    if not path or not os.path.exists(path):
        return ""

    file_type = (book.file_type or "").lower()
    if file_type == "fb2" or path.lower().endswith(".fb2"):
        return extract_text_from_fb2(path)
    return read_txt_file(path)


def get_user_book_chunks(book: Book):
    path = book.file_path or ""
    if not path or not os.path.exists(path):
        return []

    cache_key = str(book.id)
    mtime = os.path.getmtime(path)
    cached = USER_BOOK_CHUNK_CACHE.get(cache_key)
    if cached and cached.get("mtime") == mtime:
        return cached.get("chunks", [])

    text = extract_book_text(book)
    chunks = split_text_chunks(text)
    USER_BOOK_CHUNK_CACHE[cache_key] = {"mtime": mtime, "chunks": chunks}
    return chunks


def resolve_user_books(
    db: Session, current_user: User, selected_book_ids: list[int]
) -> list[Book]:
    query = db.query(Book).filter(Book.user_id == current_user.id)
    if selected_book_ids:
        query = query.filter(Book.id.in_(selected_book_ids))
    return query.all()


def build_idf_map(query_terms: list[str], chunks: list[dict[str, Any]]) -> dict[str, float]:
    if not query_terms or not chunks:
        return {}

    doc_count = max(1, len(chunks))
    df = Counter()
    for chunk in chunks:
        unique_terms = set(chunk.get("terms", []))
        for term in query_terms:
            if term in unique_terms:
                df[term] += 1

    idf_map: dict[str, float] = {}
    for term in query_terms:
        freq = df.get(term, 0)
        # Сглаженный BM25 IDF
        idf_map[term] = max(0.0, math.log((doc_count - freq + 0.5) / (freq + 0.5) + 1.0))
    return idf_map


def score_chunk(
    query: str,
    query_terms: list[str],
    query_counter: Counter,
    chunk: dict[str, Any],
    idf_map: dict[str, float],
    avg_doc_len: float,
) -> float:
    chunk_terms = chunk.get("terms", [])
    if not query_terms or not chunk_terms:
        return 0.0

    k1 = 1.5
    b = 0.75
    doc_len = max(1, len(chunk_terms))
    denom_norm = 1 - b + b * (doc_len / max(1.0, avg_doc_len))
    term_counts: Counter = chunk.get("term_counts") or Counter(chunk_terms)

    bm25 = 0.0
    for term, qtf in query_counter.items():
        tf = term_counts.get(term, 0)
        if tf <= 0:
            continue

        idf = idf_map.get(term, 0.0)
        denominator = tf + k1 * denom_norm
        tf_weight = (tf * (k1 + 1)) / max(1e-9, denominator)
        query_weight = 1.0 + 0.1 * min(2, max(0, qtf - 1))
        bm25 += idf * tf_weight * query_weight

    if bm25 <= 0:
        return 0.0

    unique_overlap = len(set(query_terms) & set(chunk_terms))
    coverage = unique_overlap / max(1, len(set(query_terms)))
    phrase_bonus = 0.22 if query.lower() in chunk.get("text", "").lower() else 0.0
    return bm25 + coverage * 0.35 + phrase_bonus


def jaccard_similarity(terms_a: list[str], terms_b: list[str]) -> float:
    if not terms_a or not terms_b:
        return 0.0
    set_a = set(terms_a)
    set_b = set(terms_b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def select_diverse_fragments(candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    if not candidates:
        return []

    remaining = candidates[:]
    selected: list[dict[str, Any]] = []
    max_score = max(item.get("score", 0.0) for item in remaining) or 1.0
    lambda_rel = 0.84

    while remaining and len(selected) < top_k:
        if not selected:
            best_idx = max(range(len(remaining)), key=lambda idx: remaining[idx]["score"])
        else:
            best_idx = 0
            best_mmr = -1e9
            for idx, item in enumerate(remaining):
                relevance = item["score"] / max_score
                max_similarity = max(
                    jaccard_similarity(item.get("_terms", []), chosen.get("_terms", []))
                    for chosen in selected
                )
                mmr = lambda_rel * relevance - (1 - lambda_rel) * max_similarity
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = idx

        selected.append(remaining.pop(best_idx))

    for item in selected:
        item.pop("_terms", None)

    return selected


def is_specific_query_term(term: str) -> bool:
    return any(ch.isdigit() for ch in term) or any("a" <= ch <= "z" for ch in term)


def query_focus_terms(query_terms: list[str]) -> set[str]:
    return {term for term in query_terms if term not in GENERIC_QUERY_TERMS and len(term) >= 3}


def specific_focus_terms(query_terms: list[str]) -> set[str]:
    return {
        term
        for term in query_focus_terms(query_terms)
        if term not in NON_SPECIFIC_FOCUS_TERMS
    }


def minimum_overlap_terms(query_term_set: set[str]) -> int:
    size = len(query_term_set)
    if size <= 1:
        return 1
    if size <= 3:
        return 2
    if size <= 6:
        return 3
    return 4


def minimum_focus_overlap(focus_terms: set[str]) -> int:
    size = len(focus_terms)
    if size <= 2:
        return 1
    if size <= 4:
        return 2
    return 3


def is_generic_unfocused_question(query_terms: list[str]) -> bool:
    query_term_set = set(query_terms)
    focus_terms = query_focus_terms(query_terms)
    if not focus_terms:
        return len(query_term_set) <= 4

    specific_focus = specific_focus_terms(query_terms)
    if specific_focus:
        return False

    # Есть только расплывчатые термины без имен/уникальных сущностей.
    return len(query_term_set) <= 8


def detect_query_position_preference(query: str) -> str:
    normalized = query.lower().replace("ё", "е")
    if any(marker in normalized for marker in ("по итогу", "в конце", "чем заканч", "финал", "концовк")):
        return "end"
    if any(marker in normalized for marker in ("в начале", "начало", "первая часть")):
        return "beginning"
    if any(marker in normalized for marker in ("в середине", "середина")):
        return "middle"
    return "any"


def chunk_noise_penalty(text: str) -> float:
    if not text:
        return 0.7

    penalty = 0.0
    lowered = text.lower().replace("ё", "е")
    if any(marker in lowered for marker in LOW_INFORMATION_MARKERS):
        penalty += 0.55
    if SEPARATOR_LINE_REGEX.search(text):
        penalty += 0.2

    tokens = TOKEN_REGEX.findall(text)
    if not tokens:
        penalty += 0.35
    else:
        alpha_tokens = sum(1 for token in tokens if any(ch.isalpha() for ch in token))
        alpha_ratio = alpha_tokens / max(1, len(tokens))
        if alpha_ratio < 0.72:
            penalty += 0.15

    short_lines = [line for line in text.splitlines() if line.strip() and len(line.strip().split()) <= 3]
    if short_lines and len(short_lines) / max(1, len([l for l in text.splitlines() if l.strip()])) > 0.5:
        penalty += 0.15

    return min(0.95, penalty)


def chunk_position_bonus(position_ratio: float, preference: str) -> float:
    ratio = max(0.0, min(1.0, position_ratio))
    if preference == "beginning":
        return (1.0 - ratio) * 0.24
    if preference == "middle":
        distance = abs(ratio - 0.5) * 2.0
        return max(0.0, (1.0 - distance) * 0.2)
    if preference == "end":
        return ratio * 0.24
    return 0.0


def chapter_proximity_bonus(requested_chapter: int | None, chunk_chapter: int | None) -> float:
    if requested_chapter is None or chunk_chapter is None:
        return 0.0
    distance = abs(requested_chapter - chunk_chapter)
    if distance == 0:
        return 0.32
    if distance == 1:
        return 0.18
    if distance == 2:
        return 0.08
    return -0.04


def rank_fragments_for_sources(
    query: str,
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
    relaxed: bool = False,
    chapter_number: int | None = None,
) -> list[dict[str, Any]]:
    query_terms = tokenize_terms(query)
    if not query_terms:
        return []

    query_counter = Counter(query_terms)
    requested_chapter = extract_requested_chapter(query)
    position_preference = detect_query_position_preference(query)
    query_term_set = set(query_terms)
    focus_terms = query_focus_terms(query_terms)
    concrete_focus_terms = specific_focus_terms(query_terms)
    matching_term_set = (
        concrete_focus_terms if concrete_focus_terms else focus_terms if focus_terms else query_term_set
    )

    required_overlap = minimum_overlap_terms(matching_term_set)
    focus_overlap_terms = concrete_focus_terms if concrete_focus_terms else focus_terms
    required_focus_overlap = minimum_focus_overlap(focus_overlap_terms) if focus_overlap_terms else 0
    specific_terms = [term for term in query_term_set if is_specific_query_term(term)]

    if relaxed:
        required_overlap = max(1, required_overlap - 1)
        if required_focus_overlap:
            required_focus_overlap = max(1, required_focus_overlap - 1)

    if is_generic_unfocused_question(query_terms) and not relaxed:
        return []

    all_chunks: list[dict[str, Any]] = []
    for _, _, chunks in sources:
        if chapter_number is None:
            all_chunks.extend(chunks)
        else:
            all_chunks.extend(
                chunk for chunk in chunks if chunk.get("chapter_number") == chapter_number
            )

    if not all_chunks:
        return []

    avg_doc_len = sum(len(chunk.get("terms", [])) for chunk in all_chunks) / max(
        1, len(all_chunks)
    )
    idf_map = build_idf_map(list(query_counter.keys()), all_chunks)
    max_end_by_book: dict[Any, int] = {}
    for book_id, _, chunks in sources:
        scoped = (
            [chunk for chunk in chunks if chunk.get("chapter_number") == chapter_number]
            if chapter_number is not None
            else chunks
        )
        if not scoped:
            continue
        max_end_by_book[book_id] = max(chunk.get("end", 0) for chunk in scoped)

    candidates: list[dict[str, Any]] = []
    for book_id, book_title, chunks in sources:
        for chunk in chunks:
            if chapter_number is not None and chunk.get("chapter_number") != chapter_number:
                continue

            chunk_terms = chunk.get("terms", [])
            chunk_term_set = set(chunk_terms)
            text = chunk.get("text", "")
            noise_penalty = chunk_noise_penalty(text)
            if noise_penalty >= 0.8 and not relaxed:
                continue

            overlap_count = len(matching_term_set & chunk_term_set)
            if overlap_count < required_overlap:
                continue

            if (
                focus_overlap_terms
                and len(focus_overlap_terms & chunk_term_set) < required_focus_overlap
            ):
                continue

            if specific_terms and not any(term in chunk_term_set for term in specific_terms):
                continue

            score = score_chunk(
                query,
                query_terms,
                query_counter,
                chunk,
                idf_map,
                avg_doc_len,
            )
            if position_preference != "any":
                max_end = max_end_by_book.get(book_id) or 1
                position_ratio = chunk.get("start", 0) / max(1, max_end)
                score += chunk_position_bonus(position_ratio, position_preference)

            score += chapter_proximity_bonus(requested_chapter, chunk.get("chapter_number"))
            score -= noise_penalty
            if score < MIN_FRAGMENT_SCORE:
                continue

            candidates.append(
                {
                    "book_id": book_id,
                    "book_title": book_title,
                    "fragment": chunk["text"],
                    "score": round(score, 4),
                    "location": build_location_payload(chunk),
                    "_terms": chunk_terms,
                }
            )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return select_diverse_fragments(candidates, top_k)


def build_user_sources(books: list[Book]) -> list[tuple[Any, str, list[dict[str, Any]]]]:
    return [(book.id, book.original_filename, get_user_book_chunks(book)) for book in books]


def build_case_sources() -> list[tuple[Any, str, list[dict[str, Any]]]]:
    metadata = load_case_metadata()
    return [
        (
            book_id,
            book_meta.get("original_filename", "unknown.txt"),
            get_case_book_chunks(book_id, book_meta),
        )
        for book_id, book_meta in metadata.items()
    ]


def rank_user_fragments(
    query: str,
    books: list[Book],
    top_k: int,
    relaxed: bool = False,
    chapter_number: int | None = None,
):
    return rank_fragments_for_sources(
        query,
        build_user_sources(books),
        top_k,
        relaxed=relaxed,
        chapter_number=chapter_number,
    )


def rank_case_fragments(
    query: str,
    top_k: int,
    relaxed: bool = False,
    chapter_number: int | None = None,
):
    return rank_fragments_for_sources(
        query,
        build_case_sources(),
        top_k,
        relaxed=relaxed,
        chapter_number=chapter_number,
    )


def extract_requested_chapter(query: str) -> int | None:
    normalized = query.lower().replace("ё", "е")

    patterns = [
        r"(?:глава|главе|главы|chapter)\s*([ivxlcdm]+|\d+|[a-zа-яё-]+)",
        r"([ivxlcdm]+|\d+|[a-zа-яё-]+)\s*(?:глава|главе|главы)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            number = parse_chapter_token(match.group(1))
            if number:
                return number

    for stem, number in CHAPTER_WORD_HINTS.items():
        if re.search(rf"{stem}\w*\s+глав", normalized) or re.search(
            rf"глав\w*\s+{stem}\w*", normalized
        ):
            return number

    return None


NAME_LOOKUP_MARKERS = (
    "как зовут",
    "как звали",
    "имя",
    "фамилия",
    "отчество",
    "прозвище",
    "кличка",
    "по имени",
)

NAME_ROLE_HINTS = {
    "друг": "друга героя",
    "приятел": "приятеля героя",
    "товарищ": "товарища героя",
    "жен": "жену героя",
    "супруг": "супругу героя",
    "муж": "мужа героя",
    "отц": "отца героя",
    "мат": "мать героя",
    "сын": "сына героя",
    "доч": "дочь героя",
    "брат": "брата героя",
    "сестр": "сестру героя",
    "шаман": "шамана",
    "капитан": "капитана",
}

CHARACTER_DESCRIPTION_MARKERS = (
    "опиши героя",
    "описание героя",
    "охарактеризуй героя",
    "характер героя",
    "характеристика героя",
    "какой герой",
    "что можно сказать о герое",
    "что за герой",
    "опиши персонажа",
    "характеристика персонажа",
    "какой персонаж",
)

NAME_VALUE_REGEXES = (
    re.compile(
        r"(?:зовут|звали|по имени|прозвали|кличка(?:\s+была)?)\s+([А-ЯЁ][А-Яа-яЁё\-]{1,}(?:\s+[А-ЯЁ][А-Яа-яЁё\-]{1,}){0,2})"
    ),
    re.compile(
        r"как\s+(?:его|ее|её|их)\s+зовут\?\s*[—–-]\s*([А-ЯЁ][А-Яа-яЁё\-]{1,}(?:\s+[А-ЯЁ][А-Яа-яЁё\-]{1,}){0,2})",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"имя\s+(?:его|ее|её|героя|персонажа|друга)?\s*(?:—|–|-|:)\s*([А-ЯЁ][А-Яа-яЁё\-]{1,}(?:\s+[А-ЯЁ][А-Яа-яЁё\-]{1,}){0,2})",
        flags=re.IGNORECASE,
    ),
)


def is_name_lookup_query(normalized_query: str) -> bool:
    normalized = normalized_query.lower().replace("ё", "е")
    if any(marker in normalized for marker in NAME_LOOKUP_MARKERS):
        return True
    return bool(re.search(r"\bкак\s+зовут\s+[а-яё\- ]{2,40}", normalized))


def detect_name_lookup_target(query: str) -> dict[str, Any]:
    normalized = query.lower().replace("ё", "е")

    if re.search(r"\bглавн\w+\s+(?:геро\w+|персонаж\w+)\b", normalized):
        return {"key": "protagonist", "subject": "главного героя", "role_terms": ["герой"]}

    for stem, subject in NAME_ROLE_HINTS.items():
        if re.search(rf"\b{stem}\w*\b", normalized):
            return {"key": stem, "subject": subject, "role_terms": [stem, "герой"]}

    if re.search(r"\b(?:геро\w+|персонаж\w+)\b", normalized):
        return {"key": "protagonist", "subject": "главного героя", "role_terms": ["герой"]}

    capture = re.search(
        r"(?:как\s+зовут|как\s+звали|имя|фамилия|отчество|прозвище|кличка)\s+([а-яё\- ]{2,40})",
        normalized,
    )
    if capture:
        subject = capture.group(1).strip()
        subject = re.sub(
            r"\b(?:в\s+книге|в\s+романе|по\s+тексту|по\s+книге|в\s+главе.*)$",
            "",
            subject,
        ).strip()
        subject_terms = [term for term in tokenize_terms(subject) if len(term) >= 3]
        if subject_terms:
            return {"key": "custom", "subject": subject, "role_terms": subject_terms}

    return {"key": "unknown", "subject": "персонажа", "role_terms": []}


def extract_candidate_names(text: str) -> list[str]:
    names: list[str] = []
    for pattern in NAME_VALUE_REGEXES:
        for match in pattern.findall(text):
            candidate = re.sub(r"[\"'«»()\\[\\],.?!:;]+$", "", (match or "").strip())
            if not candidate:
                continue
            words = [part for part in candidate.split() if part]
            if not words:
                continue
            if any(not word[0].isupper() for word in words):
                continue
            names.append(candidate)
    return names


def is_character_description_query(normalized_query: str) -> bool:
    normalized = normalized_query.lower().replace("ё", "е")
    if any(marker in normalized for marker in CHARACTER_DESCRIPTION_MARKERS):
        return True
    return bool(
        re.search(
            r"\b(?:опиши|охарактеризуй|характеристика|характер)\s+(?:главн\w+\s+)?(?:геро\w+|персонаж\w+)\b",
            normalized,
        )
        or re.search(
            r"\bкаков?\w*\s+(?:главн\w+\s+)?(?:геро\w+|персонаж\w+)\b",
            normalized,
        )
    )


def detect_generic_intent(query: str) -> str:
    normalized = query.lower().replace("ё", "е")
    chapter_reference = extract_requested_chapter(query)
    has_chapter_word = re.search(r"\bглав(?:а|е|ы|у|ой|ам|ами|ах)\b", normalized)

    if is_name_lookup_query(normalized):
        return "name_lookup"

    if is_character_description_query(normalized):
        return "character_description"

    if any(marker in normalized for marker in ("по итогу", "чем законч", "чем заканч", "концовк", "финал", "в конце")):
        return "finale"

    if chapter_reference is not None or has_chapter_word:
        return "chapter"

    if any(marker in normalized for marker in ("в начале книги", "что происходит в начале", "начало книги")):
        return "beginning"

    if any(marker in normalized for marker in ("в середине книги", "что происходит в середине", "середина книги")):
        return "middle"

    if any(
        marker in normalized
        for marker in (
            "что делал",
            "что сделал",
            "что делает",
            "чем занимается",
            "чем занимал",
            "что происходило с",
        )
    ):
        return "actions"

    if any(marker in normalized for marker in ("зачем", "почему", "по какой причине", "для чего")):
        return "motivation"

    protagonist_regex = re.search(r"\bглавн\w+\s+(?:геро\w+|персонаж\w+)\b", normalized)
    if any(
        marker in normalized
        for marker in (
            "имя главного героя",
            "имя главного персонажа",
            "имя героя",
            "имя персонажа",
            "как зовут главного героя",
            "как зовут героя",
            "кто главный герой",
            "кто главный персонаж",
            "главный герой",
            "главный персонаж",
            "о ком книга",
            "о ком произведение",
        )
    ) or protagonist_regex:
        return "protagonist"

    if any(
        marker in normalized
        for marker in (
            "как меняется",
            "как изменяется",
            "изменился герой",
            "развитие героя",
            "путь героя",
            "эволюция героя",
        )
    ):
        return "arc"

    if any(
        marker in normalized
        for marker in (
            "ключевые события",
            "главные события",
            "важные события",
            "самые важные события",
            "основные события",
        )
    ):
        return "events"

    if any(
        marker in normalized
        for marker in (
            "отношения",
            "взаимоотнош",
            "между персонаж",
            "между героя",
            "связь между",
        )
    ):
        return "relationships"

    if any(
        marker in normalized
        for marker in (
            "основная идея",
            "главная идея",
            "основная тема",
            "тема книги",
            "смысл книги",
            "основная мысль",
            "в чем идея",
            "в чем тема",
        )
    ):
        return "theme"

    if any(
        marker in normalized
        for marker in (
            "какой сюжет",
            "в чем сюжет",
            "о чем",
            "кратк",
            "сюжет",
            "общий сюжет",
            "основной сюжет",
        )
    ):
        return "plot"

    return "plot"


def is_explicit_general_question(query: str) -> bool:
    normalized = query.lower().replace("ё", "е")
    if is_name_lookup_query(normalized):
        return True
    if is_character_description_query(normalized):
        return True
    markers = (
        "о чем книга",
        "о чем произведение",
        "общий сюжет",
        "основной сюжет",
        "какой сюжет",
        "в чем сюжет",
        "по итогу",
        "чем заканч",
        "финал",
        "что происходит в начале",
        "что происходит в середине",
        "чем заканчивается книга",
        "в главе",
        "во второй главе",
        "в третьей главе",
        "имя главного героя",
        "имя главного персонажа",
        "имя героя",
        "имя персонажа",
        "как зовут главного героя",
        "как зовут героя",
        "главный герой",
        "главный персонаж",
        "ключевые события",
        "главные события",
        "отношения между",
        "взаимоотнош",
        "основная идея",
        "основная тема",
        "смысл книги",
        "как меняется герой",
        "что делает герой",
        "что делал герой",
        "зачем герой",
        "почему герой",
        "цитаты подтверждают",
    )
    if any(marker in normalized for marker in markers):
        return True
    return bool(re.search(r"\bглавн\w+\s+(?:геро\w+|персонаж\w+)\b", normalized))


def looks_like_poetry_or_epigraph(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return False

    short_lines = sum(1 for line in lines if len(line.split()) <= 7)
    punctuation_sparse = sum(1 for line in lines if not re.search(r"[.!?]", line))
    return short_lines / len(lines) >= 0.6 and punctuation_sparse / len(lines) >= 0.5


def is_low_information_text(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    if any(marker in lowered for marker in LOW_INFORMATION_MARKERS):
        return True
    return looks_like_poetry_or_epigraph(text)


def build_location_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    location = {
        "line_start": chunk["line_start"],
        "line_end": chunk["line_end"],
        "char_start": chunk["start"],
        "char_end": chunk["end"],
    }

    chapter_number = chunk.get("chapter_number")
    chapter_title = chunk.get("chapter_title")
    if chapter_number:
        location["chapter"] = chapter_number
    if chapter_title:
        location["chapter_title"] = chapter_title

    return location


def overview_indices(count: int, sample_count: int, prefer_end: bool = False) -> list[int]:
    if count <= 0:
        return []

    sample_count = max(1, min(sample_count, count))
    if sample_count == 1:
        return [count - 1] if prefer_end else [count // 2]

    indices: list[int] = []
    if prefer_end:
        anchors = [
            count - 1,
            int((count - 1) * 0.8),
            int((count - 1) * 0.6),
            int((count - 1) * 0.4),
        ]
        for idx in anchors:
            safe_idx = max(0, min(count - 1, idx))
            if safe_idx not in indices:
                indices.append(safe_idx)
            if len(indices) >= sample_count:
                break
        if len(indices) < sample_count:
            for i in range(sample_count):
                idx = round(i * (count - 1) / max(1, sample_count - 1))
                if idx not in indices:
                    indices.append(idx)
                if len(indices) >= sample_count:
                    break
        return indices

    for i in range(sample_count):
        idx = round(i * (count - 1) / max(1, sample_count - 1))
        if idx not in indices:
            indices.append(idx)

    return indices


def choose_chapter_summary_chunk(chapter_chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for chunk in chapter_chunks[:12]:
        text = chunk.get("text", "")
        if is_low_information_text(text):
            continue
        if len(text) < 220:
            continue
        if text.count(".") + text.count("!") + text.count("?") < 1:
            continue
        return chunk

    for chunk in chapter_chunks:
        if not is_low_information_text(chunk.get("text", "")):
            return chunk

    return None


def build_overview_fragments_for_sources(
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
    chapter_number: int | None = None,
    prefer_end: bool = False,
    intent: str = "plot",
) -> list[dict[str, Any]]:
    if top_k <= 0:
        return []

    sample_per_source = max(1, min(3, top_k))
    fragments: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()

    for book_id, book_title, chunks in sources:
        scoped_chunks = (
            [chunk for chunk in chunks if chunk.get("chapter_number") == chapter_number]
            if chapter_number is not None
            else chunks
        )
        if not scoped_chunks:
            continue

        picked_chunks: list[dict[str, Any]] = []

        if intent in {"plot", "events", "arc"} and chapter_number is None:
            chapter_map: dict[int, list[dict[str, Any]]] = {}
            for chunk in scoped_chunks:
                chapter = chunk.get("chapter_number")
                if chapter is None:
                    continue
                chapter_map.setdefault(chapter, []).append(chunk)

            chapter_numbers = sorted(chapter_map.keys())
            if chapter_numbers:
                chapter_indices = overview_indices(
                    len(chapter_numbers),
                    sample_per_source,
                    prefer_end=prefer_end,
                )
                for idx in chapter_indices:
                    chapter = chapter_numbers[idx]
                    selected = choose_chapter_summary_chunk(chapter_map.get(chapter, []))
                    if selected:
                        picked_chunks.append(selected)

        if not picked_chunks:
            candidate_indices = overview_indices(
                len(scoped_chunks),
                sample_per_source * 6,
                prefer_end=prefer_end,
            )
            for idx in candidate_indices:
                chunk = scoped_chunks[idx]
                if is_low_information_text(chunk.get("text", "")):
                    continue
                if chunk_noise_penalty(chunk.get("text", "")) >= 0.65:
                    continue
                picked_chunks.append(chunk)
                if len(picked_chunks) >= sample_per_source:
                    break

        for rank, chunk in enumerate(picked_chunks[:sample_per_source]):
            fingerprint = (chunk.get("text", "")[:180] + str(chunk.get("start", 0))).strip()
            if not fingerprint or fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)

            score = round(max(0.1, 1.0 - rank * 0.12), 4)
            fragments.append(
                {
                    "book_id": book_id,
                    "book_title": book_title,
                    "fragment": chunk["text"],
                    "score": score,
                    "location": build_location_payload(chunk),
                }
            )

    fragments.sort(key=lambda item: item["score"], reverse=True)
    return fragments[:top_k]


def sort_fragments_chronologically(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        fragments,
        key=lambda fragment: (
            (fragment.get("location") or {}).get("chapter")
            if (fragment.get("location") or {}).get("chapter") is not None
            else 10**9,
            (fragment.get("location") or {}).get("line_start", 10**9),
            (fragment.get("location") or {}).get("char_start", 10**9),
        ),
    )


def build_overview_answer(question: str, fragments: list[dict[str, Any]], intent: str) -> str:
    if not fragments:
        return ""

    def fallback_snippet(fragment_text: str) -> str:
        snippet = normalize_sentence_text(fragment_text.replace("\n", " "))
        return snippet[:260] if snippet else ""

    fragments_for_scan = (
        sort_fragments_chronologically(fragments)
        if intent in {"plot", "events", "arc", "beginning", "middle", "chapter", "finale"}
        else fragments
    )

    seen: set[str] = set()
    sentences: list[str] = []
    for fragment in fragments_for_scan:
        for sentence in extract_clean_sentences(fragment.get("fragment", "")):
            fingerprint = sentence.lower().replace("ё", "е")
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            sentences.append(sentence)
            if len(sentences) >= 4:
                break
        if len(sentences) >= 4:
            break

    if intent == "finale":
        final_fragment = fragments_for_scan[-1]
        final_sentences = extract_clean_sentences(final_fragment.get("fragment", ""))
        if final_sentences:
            return f"По итогу: {final_sentences[0]}"
        snippet = fallback_snippet(final_fragment.get("fragment", ""))
        return f"По итогу: {snippet}" if snippet else ""

    if intent == "chapter":
        if sentences:
            if len(sentences) == 1:
                return f"По этой главе: {sentences[0]}"
            return f"По этой главе: {sentences[0]} {sentences[1]}"
        snippet = fallback_snippet(fragments[0].get("fragment", ""))
        return f"По этой главе: {snippet}" if snippet else ""

    if intent == "beginning":
        if sentences:
            return f"В начале книги: {sentences[0]}"
        snippet = fallback_snippet(fragments[0].get("fragment", ""))
        return f"В начале книги: {snippet}" if snippet else ""

    if intent == "middle":
        middle_fragment = fragments[len(fragments) // 2]
        middle_sentences = extract_clean_sentences(middle_fragment.get("fragment", ""))
        if middle_sentences:
            # Берем наиболее информативную среднюю фразу, а не случайную короткую.
            ranked = sorted(middle_sentences, key=lambda s: (len(tokenize_terms(s)), len(s)), reverse=True)
            return f"В середине книги: {ranked[0]}"
        if sentences:
            middle_idx = len(sentences) // 2
            return f"В середине книги: {sentences[middle_idx]}"
        snippet = fallback_snippet(middle_fragment.get("fragment", ""))
        return f"В середине книги: {snippet}" if snippet else ""

    if intent == "actions":
        if sentences:
            return " ".join(sentences[:2])
        return fallback_snippet(fragments[0].get("fragment", ""))

    if not sentences:
        snippet = fallback_snippet(fragments[0].get("fragment", ""))
        return f"В начале: {snippet}" if snippet else ""

    labels = ["В начале", "Далее", "К финалу"]
    parts: list[str] = []
    for idx, sentence in enumerate(sentences[:3]):
        label = labels[idx] if idx < len(labels) else "Далее"
        parts.append(f"{label}: {sentence}")

    return " ".join(parts)


NAME_TOKEN_BLACKLIST = {
    "глава",
    "часть",
    "книга",
    "русский",
    "россия",
    "россии",
    "бог",
    "господь",
    "господи",
    "это",
    "этот",
    "эта",
    "эти",
    "она",
    "он",
    "они",
    "как",
    "что",
    "кто",
    "почему",
    "когда",
    "где",
    "какой",
    "какая",
    "какие",
    "вот",
    "так",
    "все",
    "всех",
    "наш",
    "наши",
    "этом",
    "мне",
    "меня",
    "мой",
    "моя",
    "моей",
    "моему",
    "ваше",
    "ваш",
    "ваши",
    "христа",
    "христос",
    "божие",
    "божий",
}

COMMON_CAPITALIZED_NON_NAMES = {
    "нет",
    "ничего",
    "отчего",
    "зачем",
    "только",
    "очень",
    "хорошо",
    "однако",
    "признаюсь",
    "теперь",
    "опять",
    "куда",
    "тут",
    "там",
    "есть",
    "надо",
    "неужто",
    "счастливая",
}

RELATIONSHIP_MARKERS = (
    "отнош",
    "взаимоотнош",
    "люб",
    "друж",
    "вражд",
    "конфликт",
    "сем",
    "муж",
    "жен",
    "брат",
    "сестр",
)

ACTION_MARKERS = (
    "дела",
    "сдела",
    "поступ",
    "реш",
    "пош",
    "приш",
    "уш",
    "верну",
    "встрет",
    "увид",
    "сказ",
    "рассказ",
    "помог",
    "спас",
    "взя",
    "отдал",
    "напис",
    "чита",
    "поех",
    "узнал",
    "потреб",
)

THEME_MARKERS = (
    "смысл",
    "иде",
    "тем",
    "душ",
    "вер",
    "свобод",
    "чест",
    "правд",
    "совест",
    "долг",
    "добро",
    "зло",
)
THEME_TEXT_MARKERS = (
    "вера",
    "вере",
    "веры",
    "бог",
    "церк",
    "молитв",
    "душ",
    "совест",
    "смир",
    "милосерд",
    "добро",
    "зло",
    "грех",
    "истин",
    "спас",
    "любов",
)

INTENT_HINT_QUERIES = {
    "protagonist": "главный герой персонаж кто в центре повествования",
    "name_lookup": "как зовут как звали имя фамилия отчество прозвище кличка",
    "character_description": "характер героя описание героя внешность поступки качества",
    "events": "ключевые события важные эпизоды сначала затем в конце",
    "relationships": "отношения между героями дружба любовь конфликт",
    "theme": "основная идея тема смысл произведения",
    "arc": "как меняется герой в начале и в конце",
    "actions": "что делал герой какие поступки",
    "motivation": "зачем почему по какой причине герой делает поступки",
}


def normalize_sentence_text(sentence: str) -> str:
    clean = re.sub(r"^[\s,.;:!?\"'«»()\-–—]+", "", sentence.strip())
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def is_dialogue_heavy_sentence(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith(("—", "–", "-")):
        return True

    quote_count = text.count("«") + text.count("»") + text.count('"')
    if quote_count >= 2 and len(tokenize_terms(text)) <= 20:
        return True
    if text.count("—") >= 2 and len(text) <= 220:
        return True
    return False


def extract_clean_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        clean = normalize_sentence_text(sentence)
        if len(clean) < 25:
            continue
        if len(clean.split()) < 5:
            continue
        if clean.endswith("?"):
            continue
        if not any(ch.isalpha() for ch in clean):
            continue
        if is_low_information_text(clean):
            continue
        sentences.append(clean)
    return sentences


def is_plausible_character_token(normalized: str) -> bool:
    if len(normalized) < 3:
        return False
    if normalized in NAME_TOKEN_BLACKLIST:
        return False
    if normalized in COMMON_CAPITALIZED_NON_NAMES:
        return False
    if normalized in RUS_STOPWORDS:
        return False
    if normalized in GENERIC_QUERY_TERMS:
        return False
    if normalized in NON_SPECIFIC_FOCUS_TERMS:
        return False
    if normalized.startswith(("христ", "бог", "господ")):
        return False
    return True


def extract_name_candidates(text: str) -> list[str]:
    names: list[str] = []
    for raw_name in CAPITALIZED_WORD_REGEX.findall(text):
        normalized = raw_name.lower().replace("ё", "е")
        if not is_plausible_character_token(normalized):
            continue
        names.append(raw_name)
    return names


def normalize_name_token(name: str) -> str:
    return normalize_token(name.lower().replace("ё", "е"))


def dedupe_character_names(names: list[str], top_n: int = 3) -> list[str]:
    deduped: list[str] = []
    seen_stems: set[str] = set()
    for name in names:
        stem = normalize_name_token(name)
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        deduped.append(name)
        if len(deduped) >= top_n:
            break
    return deduped


def build_character_relation_graph_from_sources(
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_characters: int = 8,
    min_edge_weight: int = 2,
) -> dict[str, Any]:
    mention_counts: Counter = Counter()
    chapter_hits: dict[str, set[int]] = defaultdict(set)
    display_names: dict[str, str] = {}
    pair_counts: Counter = Counter()
    pair_examples: dict[tuple[str, str], str] = {}

    for _, _, chunks in sources:
        for chunk in chunks:
            chapter_number = chunk.get("chapter_number")
            for sentence in extract_clean_sentences(chunk.get("text", "")):
                raw_names = extract_name_candidates(sentence)
                if not raw_names:
                    continue

                names_by_key: dict[str, str] = {}
                for raw_name in raw_names:
                    key = normalize_name_token(raw_name)
                    if not key:
                        continue
                    mention_counts[key] += 1
                    display_names.setdefault(key, raw_name)
                    names_by_key.setdefault(key, raw_name)
                    if chapter_number is not None:
                        chapter_hits[key].add(chapter_number)

                unique_keys = sorted(names_by_key.keys())
                if len(unique_keys) < 2:
                    continue

                for left, right in combinations(unique_keys, 2):
                    pair = (left, right)
                    pair_counts[pair] += 1
                    if pair not in pair_examples:
                        pair_examples[pair] = sentence

    if not mention_counts:
        return {"characters": [], "character_keys": [], "edges": []}

    scored_characters: list[tuple[float, str]] = []
    for key, mentions in mention_counts.items():
        spread = len(chapter_hits.get(key, set()))
        if mentions < 2 and spread < 2:
            continue
        score = mentions + min(2.4, spread * 0.4)
        scored_characters.append((score, key))

    scored_characters.sort(reverse=True)
    selected_keys = [key for _, key in scored_characters[:top_characters]]
    selected_key_set = set(selected_keys)

    edges: list[dict[str, Any]] = []
    for (left, right), weight in pair_counts.most_common():
        if left not in selected_key_set or right not in selected_key_set:
            continue
        if weight < min_edge_weight:
            continue
        edges.append(
            {
                "a": display_names.get(left, left),
                "b": display_names.get(right, right),
                "a_key": left,
                "b_key": right,
                "weight": weight,
                "example": pair_examples.get((left, right), ""),
            }
        )

    if not edges:
        for (left, right), weight in pair_counts.most_common(3):
            if left not in selected_key_set or right not in selected_key_set:
                continue
            edges.append(
                {
                    "a": display_names.get(left, left),
                    "b": display_names.get(right, right),
                    "a_key": left,
                    "b_key": right,
                    "weight": weight,
                    "example": pair_examples.get((left, right), ""),
                }
            )

    character_names = dedupe_character_names([display_names[key] for key in selected_keys], top_n=top_characters)
    return {
        "characters": character_names,
        "character_keys": selected_keys,
        "edges": edges,
    }


def detect_main_characters_from_sources(
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_n: int = 3,
) -> list[str]:
    relation_graph = build_character_relation_graph_from_sources(
        sources,
        top_characters=max(4, top_n + 1),
        min_edge_weight=1,
    )
    graph_weights: Counter = Counter()
    graph_display_names: dict[str, str] = {}
    for edge in relation_graph.get("edges") or []:
        left_key = edge.get("a_key")
        right_key = edge.get("b_key")
        weight = int(edge.get("weight") or 0)
        if left_key:
            graph_weights[left_key] += max(1, weight)
            graph_display_names.setdefault(left_key, edge.get("a") or left_key)
        if right_key:
            graph_weights[right_key] += max(1, weight)
            graph_display_names.setdefault(right_key, edge.get("b") or right_key)

    mention_counts: Counter = Counter()
    chapter_hits: dict[str, set[int]] = defaultdict(set)
    display_names: dict[str, str] = {}

    for _, _, chunks in sources:
        for chunk in chunks:
            chapter = chunk.get("chapter_number")
            text = chunk.get("text", "")
            chunk_names: set[str] = set()
            for raw in extract_name_candidates(text):
                normalized = raw.lower().replace("ё", "е")
                mention_counts[normalized] += 1
                display_names.setdefault(normalized, raw)
                chunk_names.add(normalized)

            if chapter is not None:
                for normalized in chunk_names:
                    chapter_hits[normalized].add(chapter)

    scored: list[tuple[float, str]] = []
    candidate_keys = set(mention_counts.keys()) | set(graph_weights.keys())
    for normalized in candidate_keys:
        mentions = mention_counts.get(normalized, 0)
        graph_boost = graph_weights.get(normalized, 0)
        chapter_spread = len(chapter_hits.get(normalized, set()))
        if mentions < 2 and graph_boost < 2:
            continue
        if chapter_spread == 0 and mentions < 4 and graph_boost < 3:
            continue

        score = mentions + min(2.2, chapter_spread * 0.45) + min(2.0, graph_boost * 0.25)
        scored.append((score, normalized))

    scored.sort(reverse=True)
    ranked_names = [
        display_names.get(key) or graph_display_names.get(key) or key.capitalize()
        for _, key in scored[: max(top_n * 2, top_n)]
    ]
    return dedupe_character_names(ranked_names, top_n=top_n)


def detect_main_characters_from_fragments(
    fragments: list[dict[str, Any]],
    top_n: int = 3,
) -> list[str]:
    normalized_counts: Counter = Counter()
    display_names: dict[str, str] = {}

    for fragment in fragments:
        fragment_text = fragment.get("fragment", "")
        for name in extract_name_candidates(fragment_text):
            normalized = name.lower().replace("ё", "е")
            normalized_counts[normalized] += 1
            if normalized not in display_names:
                display_names[normalized] = name

    frequent = [
        (key, count)
        for key, count in normalized_counts.most_common()
        if count >= 2
    ]
    if frequent:
        return dedupe_character_names([display_names[key] for key, _ in frequent[:top_n]], top_n=top_n)

    return []


def count_marker_hits(terms: list[str], markers: tuple[str, ...]) -> int:
    hits = 0
    for term in terms:
        for marker in markers:
            if len(marker) <= 3:
                if term == marker:
                    hits += 1
                    break
            elif term.startswith(marker):
                hits += 1
                break
    return hits


def collect_sentence_candidates(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for fragment_rank, fragment in enumerate(fragments):
        location = fragment.get("location") or {}
        base_score = max(0.0, 1.0 - fragment_rank * 0.08)
        for sentence in extract_clean_sentences(fragment.get("fragment", "")):
            fingerprint = sentence.lower().replace("ё", "е")
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            names = extract_name_candidates(sentence)

            candidates.append(
                {
                    "text": sentence,
                    "terms": tokenize_terms(sentence),
                    "names": names,
                    "name_keys": [normalize_name_token(name) for name in names],
                    "base_score": base_score,
                    "fragment_rank": fragment_rank,
                    "chapter": location.get("chapter"),
                    "line_start": location.get("line_start", 10**9),
                }
            )

    return candidates


def chronological_sentences(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda item: (
            item.get("chapter") if item.get("chapter") is not None else 10**9,
            item.get("line_start", 10**9),
            item.get("fragment_rank", 10**9),
        ),
    )


def sample_timeline_items(
    items: list[dict[str, Any]],
    count: int,
    prefer_end: bool = False,
) -> list[dict[str, Any]]:
    if not items:
        return []
    count = max(1, min(count, len(items)))
    if len(items) <= count:
        return items
    indices = overview_indices(len(items), count, prefer_end=prefer_end)
    return [items[idx] for idx in indices]


def pick_top_scored_items(
    scored: list[tuple[float, dict[str, Any]]],
    count: int,
    preserve_chronology: bool = True,
) -> list[dict[str, Any]]:
    if not scored:
        return []

    scored_sorted = sorted(scored, key=lambda row: row[0], reverse=True)
    pool_size = max(count, min(len(scored_sorted), count * 3))
    pool = [item for _, item in scored_sorted[:pool_size]]

    if preserve_chronology:
        pool = chronological_sentences(pool)
    return pool[:count]


def has_causal_marker(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return any(marker in lowered for marker in ("потому", "так как", "поэтому", "из-за", "чтобы", "для того"))


DESCRIPTION_QUALITY_MARKERS = (
    "смел",
    "суров",
    "добр",
    "строг",
    "мудр",
    "тих",
    "крот",
    "хитер",
    "чест",
    "благород",
    "жесток",
    "терпел",
    "горд",
    "милосерд",
    "характер",
    "нрав",
    "внешн",
    "поступ",
    "поведен",
    "простодуш",
    "преутеш",
    "чудак",
    "старик",
    "мил",
    "превосход",
    "суровост",
    "вспыльч",
    "кротк",
    "мягк",
    "сильн",
    "решитель",
    "волев",
    "малоприят",
    "впечатлен",
    "сдержан",
    "вниматель",
    "ласков",
    "жадн",
    "бескорыст",
)

DESCRIPTION_ROLE_MARKERS = (
    "герой",
    "персонаж",
    "человек",
    "мужчина",
    "женщина",
    "старик",
    "старуха",
    "юноша",
    "девушка",
    "рассказчик",
    "капитан",
    "монах",
    "юродив",
    "друг",
    "товарищ",
)

DESCRIPTION_EVENT_MARKERS = (
    "схоронил",
    "узнал",
    "поехал",
    "приехал",
    "пошел",
    "пошла",
    "окрестил",
    "встретил",
    "увидел",
    "рассказал",
    "возвращал",
    "прибыл",
    "отправил",
    "поход",
    "дорог",
)


def description_marker_hits(text: str) -> int:
    lowered = text.lower().replace("ё", "е")
    return sum(1 for marker in DESCRIPTION_QUALITY_MARKERS if marker in lowered)


def mentions_character_reference(
    text: str,
    focus_key: str = "",
    name_keys: list[str] | None = None,
) -> bool:
    lowered = text.lower().replace("ё", "е")
    if any(marker in lowered for marker in DESCRIPTION_ROLE_MARKERS):
        return True
    if re.search(r"\b(?:он|она|его|ее|её|ему|ей|ним|нею)\b", lowered):
        return True
    if focus_key:
        if focus_key in set(name_keys or []):
            return True
        if focus_key in set(tokenize_terms(text)):
            return True
    return False


def has_trait_pattern(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    if re.search(r"\b(?:внешност|характер|нрав|образ)\w*\b", lowered):
        return True
    if re.search(
        r"\b(?:он|она|герой|персонаж|человек|старик|девушка|юноша)\b.{0,42}"
        r"\b(?:был|была|были|казал\w*|выглядел\w*|производил\w*|отличал\w*|обладал\w*|славил\w*|являл\w*|стал\w*)\b",
        lowered,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:человек|герой|персонаж)\b.{0,36}\b(?:сильн|решитель|волев|доб|строг|смел|чест|жесток|мягк|кротк|мудр)\w*",
            lowered,
        )
    )


def is_descriptive_sentence(
    text: str,
    focus_key: str = "",
    name_keys: list[str] | None = None,
) -> bool:
    marker_hits = description_marker_hits(text)
    if marker_hits >= 2:
        return True
    if marker_hits >= 1 and mentions_character_reference(text, focus_key=focus_key, name_keys=name_keys):
        return True
    if has_trait_pattern(text):
        return True
    return False


def is_event_driven_sentence(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return any(marker in lowered for marker in DESCRIPTION_EVENT_MARKERS)


def is_enumeration_heavy_sentence(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    capitals = CAPITALIZED_WORD_REGEX.findall(text)
    comma_count = text.count(",")
    has_ellipsis = ("…" in text) or ("..." in text)
    has_travel_context = any(
        marker in lowered
        for marker in ("город", "озер", "озеро", "храм", "шосс", "путешеств", "командиров")
    )
    if comma_count >= 4 and (has_ellipsis or len(capitals) >= 4):
        return True
    if len(capitals) >= 5 and has_travel_context:
        return True
    return False


def build_character_description_answer(
    question: str,
    candidates: list[dict[str, Any]],
    preferred_characters: list[str] | None = None,
) -> str:
    question_terms = tokenize_terms(question)
    focus_name = preferred_characters[0] if preferred_characters else ""
    focus_key = normalize_name_token(focus_name) if focus_name else ""

    working_candidates = candidates
    focus_confirmed = False
    if focus_key:
        focused = [item for item in candidates if focus_key in set(item.get("name_keys", []))]
        if focused:
            working_candidates = focused
            focus_confirmed = True

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in working_candidates:
        terms = item.get("terms", [])
        text = item.get("text", "")
        lowered = text.lower().replace("ё", "е")
        name_keys = item.get("name_keys", [])
        has_focus = bool(focus_key and focus_key in set(name_keys))
        if has_focus:
            focus_confirmed = True
        overlap = lexical_overlap_score(question_terms, terms)
        marker_hits = description_marker_hits(text)
        trait_signal = has_trait_pattern(text)
        descriptive = is_descriptive_sentence(text, focus_key=focus_key, name_keys=name_keys)
        mentions_person = mentions_character_reference(text, focus_key=focus_key, name_keys=name_keys)
        event_like = is_event_driven_sentence(text)
        enum_like = is_enumeration_heavy_sentence(text)
        names_count = len(name_keys)

        score = item.get("base_score", 0.0)
        score += overlap * 0.22
        score += marker_hits * 0.12
        score += 0.44 if trait_signal else 0.0
        score += 0.2 if descriptive else 0.0
        score += 0.32 if has_focus else 0.0
        score += 0.12 if mentions_person else 0.0
        if names_count > 0:
            score += min(0.08, names_count * 0.03)
        if event_like:
            score -= 0.12 if trait_signal else 0.32
        if enum_like and not trait_signal:
            score -= 0.25
        if len(text) > 320 and not trait_signal:
            score -= 0.12
        if re.search(r"\bя\b", lowered) and not (has_focus or trait_signal):
            score -= 0.08

        if not mentions_person and not trait_signal and marker_hits < 2:
            continue
        if not descriptive and marker_hits == 0 and not trait_signal:
            continue
        if not descriptive and overlap < 0.3 and not has_focus:
            continue

        if descriptive or overlap > 0.2 or has_focus:
            scored.append((score, item))

    if not scored:
        fallback_pool = [
            item
            for item in working_candidates
            if is_descriptive_sentence(
                item.get("text", ""),
                focus_key=focus_key,
                name_keys=item.get("name_keys", []),
            )
        ]
        if not fallback_pool:
            return ""
        fallback_pool.sort(key=lambda row: row.get("base_score", 0.0), reverse=True)
        fallback = fallback_pool[:2]
        selected_text = " ".join(item.get("text", "") for item in fallback)
        focus_in_selected = bool(
            focus_key
            and any(focus_key in set(item.get("name_keys", [])) for item in fallback)
        )
        if focus_name and (focus_confirmed or focus_in_selected):
            return f"По тексту образ героя {focus_name} раскрывается так: {selected_text}".strip()
        return f"По тексту образ героя раскрывается так: {selected_text}".strip()

    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = [item for _, item in scored[:2]]
    selected_text = " ".join(item["text"] for item in selected)
    focus_in_selected = bool(
        focus_key
        and any(focus_key in set(item.get("name_keys", [])) for item in selected)
    )
    if focus_name and (focus_confirmed or focus_in_selected):
        return f"По тексту образ героя {focus_name} раскрывается так: {selected_text}".strip()
    return f"По тексту образ героя раскрывается так: {selected_text}".strip()


def build_name_lookup_answer(
    question: str,
    candidates: list[dict[str, Any]],
    preferred_characters: list[str] | None = None,
) -> str:
    target = detect_name_lookup_target(question)
    target_key = target.get("key", "unknown")
    target_subject = (target.get("subject") or "персонажа").strip()
    role_terms = target.get("role_terms") or []
    role_term_set = set(tokenize_terms(" ".join(role_terms))) if role_terms else set()
    question_terms = tokenize_terms(question)

    scored_rows: list[tuple[float, dict[str, Any], list[str]]] = []
    cue_markers = ("зовут", "звали", "по имени", "имя", "прозвищ", "кличк")
    for item in candidates:
        text = item.get("text", "")
        lowered = text.lower().replace("ё", "е")
        cue_hits = sum(1 for marker in cue_markers if marker in lowered)
        names = extract_candidate_names(text)
        if cue_hits == 0 and not names:
            continue

        item_terms = item.get("terms", [])
        role_overlap = (
            len(role_term_set & set(item_terms)) / max(1, len(role_term_set))
            if role_term_set
            else 0.0
        )
        if role_term_set and role_overlap == 0 and target_key not in {"protagonist", "unknown"}:
            continue

        question_overlap = lexical_overlap_score(question_terms, item_terms)
        score = item.get("base_score", 0.0) + cue_hits * 0.42 + question_overlap * 0.35 + role_overlap * 0.45
        scored_rows.append((score, item, names))

    if not scored_rows:
        if target_key == "protagonist" and preferred_characters:
            return f"Главный герой по тексту: {preferred_characters[0]}."
        return ""

    scored_rows.sort(key=lambda row: row[0], reverse=True)
    top_rows = scored_rows[:5]

    weighted_names: Counter = Counter()
    for score, _, names in top_rows:
        for name in names:
            weighted_names[name] += max(0.1, score)

    if weighted_names:
        selected_name = weighted_names.most_common(1)[0][0]
    elif target_key == "protagonist" and preferred_characters:
        selected_name = preferred_characters[0]
    else:
        return ""

    if target_key == "protagonist":
        return f"Главный герой по тексту: {selected_name}."

    if target_key in {"жен", "супруг", "муж", "отц", "мат", "сын", "доч", "брат", "сестр", "друг", "приятел", "товарищ"}:
        return f"По найденным фрагментам имя {target_subject}: {selected_name}."

    return f"По найденным фрагментам {target_subject} зовут {selected_name}."


def build_intent_answer_from_fragments(
    question: str,
    fragments: list[dict[str, Any]],
    intent: str,
    preferred_characters: list[str] | None = None,
    relation_graph: dict[str, Any] | None = None,
) -> str:
    if not fragments:
        return ""

    candidates = collect_sentence_candidates(fragments)
    if not candidates:
        return ""

    timeline = chronological_sentences(candidates)
    fragment_characters = detect_main_characters_from_fragments(fragments, top_n=3)
    base_characters = preferred_characters or fragment_characters
    main_characters = dedupe_character_names(base_characters, top_n=3)
    main_character_keys = [normalize_name_token(name) for name in main_characters]
    focus_name = main_characters[0] if main_characters else ""
    focus_key = main_character_keys[0] if main_character_keys else ""

    if intent == "name_lookup":
        return build_name_lookup_answer(
            question,
            candidates,
            preferred_characters=main_characters,
        )

    if intent == "character_description":
        return build_character_description_answer(
            question,
            candidates,
            preferred_characters=main_characters,
        )

    if intent == "protagonist":
        normalized_question = question.lower().replace("ё", "е")
        asks_name = any(
            marker in normalized_question
            for marker in (
                "имя главного героя",
                "имя героя",
                "как зовут главного героя",
                "как зовут героя",
            )
        )
        asks_single_main = any(
            marker in normalized_question
            for marker in (
                "кто главный герой",
                "кто главный персонаж",
            )
        )
        focus_keys = set(main_character_keys[:2]) if main_character_keys else set()
        focused = [
            item
            for item in timeline
            if focus_keys and focus_keys.intersection(set(item.get("name_keys", [])))
        ]
        selected = focused[:2] if focused else timeline[:2]

        if (asks_name or asks_single_main) and main_characters:
            return f"Главный герой по тексту: {main_characters[0]}."

        if main_characters:
            intro = f"По этим фрагментам в центре повествования: {', '.join(main_characters[:2])}."
        else:
            intro = "По этим фрагментам в центре повествования несколько ключевых персонажей."
        return f"{intro} {' '.join(item['text'] for item in selected)}".strip()

    if intent == "events":
        if len(timeline) <= 3:
            selected = timeline
        else:
            indices = overview_indices(len(timeline), 3, prefer_end=False)
            selected = [timeline[idx] for idx in indices]
        parts = [f"{idx + 1}) {item['text']}" for idx, item in enumerate(selected)]
        return "Ключевые события по книге: " + " ".join(parts)

    if intent == "relationships":
        scored: list[tuple[float, dict[str, Any]]] = []
        main_set = set(main_character_keys[:3])
        edge_pairs: list[set[str]] = []
        edge_labels: list[str] = []
        if relation_graph:
            for edge in (relation_graph.get("edges") or [])[:2]:
                left_key = edge.get("a_key")
                right_key = edge.get("b_key")
                left_name = edge.get("a")
                right_name = edge.get("b")
                if left_key and right_key:
                    edge_pairs.append({left_key, right_key})
                if left_name and right_name:
                    if normalize_name_token(left_name) != normalize_name_token(right_name):
                        label = f"{left_name} и {right_name}"
                        if label not in edge_labels:
                            edge_labels.append(label)

        for item in candidates:
            name_key_set = set(item.get("name_keys", []))
            marker_hits = count_marker_hits(item.get("terms", []), RELATIONSHIP_MARKERS)
            names_count = len(name_key_set)
            has_main_pair = len(main_set & name_key_set) >= 2
            has_main_one = len(main_set & name_key_set) >= 1
            edge_match = max((len(pair & name_key_set) for pair in edge_pairs), default=0)
            dialogue_penalty = 0.24 if is_dialogue_heavy_sentence(item.get("text", "")) else 0.0

            if not has_main_pair and edge_match < 2 and names_count < 2:
                if marker_hits == 0 or names_count == 0:
                    continue
            if names_count >= 2 and not has_main_one and edge_match == 0 and marker_hits == 0:
                continue
            if dialogue_penalty > 0 and marker_hits == 0 and edge_match < 2:
                continue

            score = item.get("base_score", 0.0) + marker_hits * 0.18 + (0.25 if names_count >= 2 else 0.0)
            if has_main_pair:
                score += 0.35
            elif has_main_one:
                score += 0.15
            if edge_match >= 2:
                score += 0.42
            elif edge_match == 1:
                score += 0.18
            score -= dialogue_penalty
            scored.append((score, item))

        if not scored:
            non_dialogue = [item for item in timeline if not is_dialogue_heavy_sentence(item.get("text", ""))]
            selected = sample_timeline_items(non_dialogue if non_dialogue else timeline, 2, prefer_end=False)
            intro = "По этим фрагментам показаны взаимоотношения персонажей."
        else:
            selected = pick_top_scored_items(scored, 2, preserve_chronology=True)
            if edge_labels:
                intro = f"По книге заметны связи между персонажами: {'; '.join(edge_labels[:2])}."
            else:
                intro = "По этим фрагментам заметна линия отношений между персонажами."

        return f"{intro} {' '.join(item['text'] for item in selected)}".strip()

    if intent == "theme":
        question_terms = tokenize_terms(question)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in candidates:
            theme_hits = count_marker_hits(item.get("terms", []), THEME_MARKERS)
            overlap = lexical_overlap_score(question_terms, item.get("terms", []))
            text_lower = item.get("text", "").lower().replace("ё", "е")
            text_hits = sum(1 for marker in THEME_TEXT_MARKERS if marker in text_lower)
            score = item.get("base_score", 0.0) * 0.6 + theme_hits * 0.23 + text_hits * 0.12 + overlap * 0.3
            if theme_hits > 0 or text_hits > 0 or overlap > 0.1:
                scored.append((score, item))

        if not scored:
            selected = sample_timeline_items(timeline, 3, prefer_end=False)
            intro = "Основная тема по найденным фрагментам проявляется так:"
        else:
            scored.sort(key=lambda pair: pair[0], reverse=True)
            selected = [item for _, item in scored[:2]]
            intro = "Основная тема по найденным фрагментам проявляется так:"

        return f"{intro} {' '.join(item['text'] for item in selected)}".strip()

    if intent == "arc":
        if focus_key and any(focus_key in item.get("name_keys", []) for item in timeline):
            with_focus = [item for item in timeline if focus_key in item.get("name_keys", [])]
        else:
            focus_name = ""
            focus_key = ""
            with_focus = timeline

        if len(with_focus) >= 2:
            first = with_focus[0]["text"]
            last = with_focus[-1]["text"]
            if first == last and len(with_focus) > 1:
                last = with_focus[-2]["text"]
        else:
            first = timeline[0]["text"]
            last = timeline[-1]["text"]

        intro = (
            f"Линия героя {focus_name} по книге меняется так:"
            if focus_name
            else "По книге линия героя меняется так:"
        )
        return f"{intro} В начале: {first} К финалу: {last}"

    if intent == "motivation":
        question_terms = tokenize_terms(question)
        scored: list[tuple[float, dict[str, Any]]] = []
        focus_set = set(main_character_keys[:2])
        for item in candidates:
            overlap = lexical_overlap_score(question_terms, item.get("terms", []))
            name_key_set = set(item.get("name_keys", []))
            has_focus = bool(focus_set & name_key_set) if focus_set else False
            causal_bonus = 0.3 if has_causal_marker(item.get("text", "")) else 0.0
            action_hits = count_marker_hits(item.get("terms", []), ACTION_MARKERS)
            dialogue_penalty = 0.2 if is_dialogue_heavy_sentence(item.get("text", "")) else 0.0
            score = item.get("base_score", 0.0) + overlap * 0.36 + causal_bonus + action_hits * 0.08
            if has_focus:
                score += 0.2
            score -= dialogue_penalty

            if causal_bonus == 0 and overlap < 0.12 and not (has_focus and action_hits > 0):
                continue
            if dialogue_penalty > 0 and causal_bonus == 0 and overlap < 0.2:
                continue
            scored.append((score, item))

        if scored:
            selected = pick_top_scored_items(scored, 2, preserve_chronology=True)
        else:
            non_dialogue = [item for item in timeline if not is_dialogue_heavy_sentence(item.get("text", ""))]
            selected = sample_timeline_items(non_dialogue if non_dialogue else timeline, 2, prefer_end=False)

        selected_has_focus = bool(
            focus_key and any(focus_key in set(item.get("name_keys", [])) for item in selected)
        )
        if focus_name and selected_has_focus:
            intro = f"По тексту причины действий героя {focus_name} выглядят так:"
        else:
            intro = "По тексту причины действий героя выглядят так:"
        return f"{intro} {' '.join(item['text'] for item in selected)}"

    if intent == "actions":
        question_terms = tokenize_terms(question)
        focus_set = set(main_character_keys[:2])
        action_scored: list[tuple[float, dict[str, Any]]] = []

        for item in timeline:
            terms = item.get("terms", [])
            name_key_set = set(item.get("name_keys", []))
            has_focus = bool(focus_set & name_key_set) if focus_set else False
            action_hits = count_marker_hits(terms, ACTION_MARKERS)
            overlap = lexical_overlap_score(question_terms, terms)
            dialogue_penalty = 0.22 if is_dialogue_heavy_sentence(item.get("text", "")) else 0.0

            score = item.get("base_score", 0.0) + action_hits * 0.2 + overlap * 0.3
            if has_focus:
                score += 0.22
            score -= dialogue_penalty

            if action_hits == 0 and overlap < 0.1:
                continue
            if focus_set and not has_focus and overlap < 0.2 and action_hits < 2:
                continue
            if dialogue_penalty > 0 and action_hits < 2 and overlap < 0.2:
                continue
            action_scored.append((score, item))

        if action_scored:
            selected = pick_top_scored_items(action_scored, 2, preserve_chronology=True)
        else:
            non_dialogue = [item for item in timeline if not is_dialogue_heavy_sentence(item.get("text", ""))]
            selected = sample_timeline_items(non_dialogue if non_dialogue else timeline, 2, prefer_end=False)

        selected_has_focus = bool(
            focus_key and any(focus_key in set(item.get("name_keys", [])) for item in selected)
        )
        if focus_name and selected_has_focus:
            intro = f"По тексту действия героя {focus_name} описаны так:"
        else:
            intro = "По тексту действия героя описаны так:"
        return f"{intro} {' '.join(item['text'] for item in selected)}"

    return ""


def merge_fragments(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any, Any]] = set()

    for fragment in primary + secondary:
        location = fragment.get("location") or {}
        key = (
            fragment.get("book_id"),
            location.get("chapter"),
            location.get("line_start"),
            location.get("line_end"),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(fragment)
        if len(merged) >= limit:
            break

    return merged


def build_generic_answer_for_sources(
    query: str,
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
    citations_k: int,
) -> tuple[str, list[dict[str, Any]]]:
    chapter_number = extract_requested_chapter(query)
    intent = detect_generic_intent(query)
    prefer_end = intent == "finale"
    overview_intent = "plot" if intent in {"beginning", "middle"} else intent

    fragments: list[dict[str, Any]] = []

    if intent in {"plot", "finale", "chapter", "beginning", "middle"}:
        fragments = build_overview_fragments_for_sources(
            sources,
            max(1, top_k),
            chapter_number=chapter_number,
            prefer_end=prefer_end,
            intent=overview_intent,
        )

        if not fragments and chapter_number is not None:
            fragments = build_overview_fragments_for_sources(
                sources,
                max(1, top_k),
                chapter_number=None,
                prefer_end=prefer_end,
                intent=overview_intent,
            )

        answer = build_overview_answer(query, fragments, intent)
        return answer, fragments[: max(1, citations_k)]

    name_target_info = detect_name_lookup_target(query) if intent == "name_lookup" else {}
    name_target_hints = " ".join(name_target_info.get("role_terms") or [])
    ranked_query = f"{query} {name_target_hints} {INTENT_HINT_QUERIES.get(intent, '')}".strip()
    rank_top_k = max(3, top_k)
    preferred_characters = detect_main_characters_from_sources(sources, top_n=3)
    character_fragments: list[dict[str, Any]] = []
    relation_graph = (
        build_character_relation_graph_from_sources(sources, top_characters=8, min_edge_weight=2)
        if intent == "relationships"
        else None
    )
    relation_fragments: list[dict[str, Any]] = []

    ranked_fragments, _ = rank_fragments_with_fallback(
        ranked_query,
        sources,
        rank_top_k,
        chapter_number=chapter_number,
    )
    if not ranked_fragments and chapter_number is not None:
        ranked_fragments, _ = rank_fragments_with_fallback(
            ranked_query,
            sources,
            rank_top_k,
            chapter_number=None,
        )

    if intent in {"actions", "motivation", "arc", "protagonist", "name_lookup", "character_description"} and preferred_characters:
        character_query = f"{preferred_characters[0]} {INTENT_HINT_QUERIES.get(intent, '')}".strip()
        character_fragments, _ = rank_fragments_with_fallback(
            character_query,
            sources,
            rank_top_k,
            chapter_number=chapter_number,
        )
        if not character_fragments and chapter_number is not None:
            character_fragments, _ = rank_fragments_with_fallback(
                character_query,
                sources,
                rank_top_k,
                chapter_number=None,
            )

    if intent == "relationships" and relation_graph:
        top_edges = (relation_graph.get("edges") or [])[:2]
        if top_edges:
            relation_terms = " ".join(
                f"{edge.get('a', '')} {edge.get('b', '')}".strip()
                for edge in top_edges
            ).strip()
            relation_query = f"{relation_terms} {INTENT_HINT_QUERIES.get('relationships', '')}".strip()
            relation_fragments, _ = rank_fragments_with_fallback(
                relation_query,
                sources,
                rank_top_k,
                chapter_number=chapter_number,
            )
            if not relation_fragments and chapter_number is not None:
                relation_fragments, _ = rank_fragments_with_fallback(
                    relation_query,
                    sources,
                    rank_top_k,
                    chapter_number=None,
                )

    overview_fragments = build_overview_fragments_for_sources(
        sources,
        rank_top_k,
        chapter_number=chapter_number,
        prefer_end=prefer_end,
        intent="plot",
    )
    if not overview_fragments and chapter_number is not None:
        overview_fragments = build_overview_fragments_for_sources(
            sources,
            rank_top_k,
            chapter_number=None,
            prefer_end=prefer_end,
            intent="plot",
        )

    if intent in {"events", "arc"}:
        ranked_priority = merge_fragments(character_fragments, ranked_fragments, rank_top_k)
        fragments = merge_fragments(overview_fragments, ranked_priority, rank_top_k)
    elif intent == "relationships":
        primary = merge_fragments(relation_fragments, character_fragments, rank_top_k)
        primary = merge_fragments(primary, ranked_fragments, rank_top_k)
        fragments = merge_fragments(primary, overview_fragments, rank_top_k)
    else:
        primary = merge_fragments(character_fragments, ranked_fragments, rank_top_k)
        fragments = merge_fragments(primary, overview_fragments, rank_top_k)

    answer = build_intent_answer_from_fragments(
        query,
        fragments,
        intent,
        preferred_characters=preferred_characters,
        relation_graph=relation_graph,
    )
    if not answer:
        if intent in {"name_lookup", "character_description"}:
            return "", fragments[: max(1, citations_k)]
        answer = build_overview_answer(query, fragments, "plot")

    return answer, fragments[: max(1, citations_k)]

def rank_fragments_with_fallback(
    query: str,
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
    chapter_number: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    fragments = rank_fragments_for_sources(
        query,
        sources,
        top_k,
        relaxed=False,
        chapter_number=chapter_number,
    )
    if fragments:
        return fragments, False

    fragments = rank_fragments_for_sources(
        query,
        sources,
        top_k,
        relaxed=True,
        chapter_number=chapter_number,
    )
    if fragments:
        return fragments, True

    if chapter_number is not None:
        fragments = rank_fragments_for_sources(
            query,
            sources,
            top_k,
            relaxed=True,
            chapter_number=None,
        )

    return fragments, True


def search_fragments_in_sources(
    query: str,
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
) -> tuple[list[dict[str, Any]], str | None]:
    chapter_number = extract_requested_chapter(query)
    query_terms = tokenize_terms(query)

    if is_generic_unfocused_question(query_terms) or is_explicit_general_question(query):
        intent = detect_generic_intent(query)
        if intent == "name_lookup":
            ranked_query = f"{query} {INTENT_HINT_QUERIES.get('name_lookup', '')}".strip()
            fragments, _ = rank_fragments_with_fallback(
                ranked_query,
                sources,
                top_k,
                chapter_number=chapter_number,
            )
            name_fragments = [
                fragment
                for fragment in fragments
                if is_name_lookup_query(fragment.get("fragment", "").lower().replace("ё", "е"))
            ]
            if name_fragments:
                return name_fragments[:top_k], None
            if fragments:
                return fragments, None
            return (
                [],
                "Не удалось найти фрагменты с прямым указанием имени. Уточните персонажа.",
            )

        fragments = build_overview_fragments_for_sources(
            sources,
            top_k,
            chapter_number=chapter_number,
            prefer_end=intent == "finale",
            intent=intent,
        )
        if fragments:
            return fragments, None

        return (
            [],
            "Не удалось сформировать общий обзор. Уточните запрос: персонаж, глава или событие.",
        )

    fragments, _ = rank_fragments_with_fallback(
        query,
        sources,
        top_k,
        chapter_number=chapter_number,
    )
    if fragments:
        return fragments, None

    return [], "Подходящие фрагменты не найдены"


def answer_question_in_sources(
    question: str,
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
    citations_k: int,
) -> tuple[bool, str, list[dict[str, Any]]]:
    query_terms = tokenize_terms(question)
    intent_guess = detect_generic_intent(question)

    if is_generic_unfocused_question(query_terms) or is_explicit_general_question(question):
        answer, citations = build_generic_answer_for_sources(
            question,
            sources,
            top_k,
            citations_k,
        )
        if answer:
            return True, answer, citations

        if intent_guess == "name_lookup":
            return (
                False,
                "В загруженных книгах не найдено прямого указания имени для этого запроса.",
                [],
            )
        if intent_guess == "character_description":
            return (
                False,
                "В загруженных книгах не найдено явного описания героя для этого запроса.",
                [],
            )

        return (
            False,
            "Не удалось сформировать общий ответ. Уточните персонажа, главу или событие.",
            [],
        )

    chapter_number = extract_requested_chapter(question)
    fragments, relaxed_used = rank_fragments_with_fallback(
        question,
        sources,
        top_k,
        chapter_number=chapter_number,
    )
    if not fragments:
        return False, "К сожалению, в загруженных книгах нет ответа на этот вопрос.", []

    answer = extractive_answer(question, fragments, relaxed=relaxed_used)
    if not answer and not relaxed_used:
        answer = extractive_answer(question, fragments, relaxed=True)

    if not answer:
        return (
            False,
            "К сожалению, в загруженных книгах нет достаточной информации для ответа.",
            [],
        )

    return True, answer, fragments[: max(1, citations_k)]


def detect_question_type(question: str) -> str:
    normalized = question.lower()
    if any(marker in normalized for marker in ("почему", "зачем", "по какой причине")):
        return "why"
    if any(marker in normalized for marker in ("когда", "в каком году", "какого года", "дата")):
        return "when"
    if any(marker in normalized for marker in ("где", "куда", "откуда", "в каком месте")):
        return "where"
    if any(marker in normalized for marker in ("кто", "кого", "кому", "чей", "чья", "чьи")):
        return "who"
    if any(marker in normalized for marker in ("как", "каким образом")):
        return "how"
    return "what"


def lexical_overlap_score(question_terms: list[str], sentence_terms: list[str]) -> float:
    if not question_terms or not sentence_terms:
        return 0.0

    question_counter = Counter(question_terms)
    sentence_counter = Counter(sentence_terms)
    overlap_total = sum(
        min(count, sentence_counter.get(term, 0))
        for term, count in question_counter.items()
    )
    if overlap_total == 0:
        return 0.0

    unique_overlap = sum(
        1 for term in question_counter if sentence_counter.get(term, 0) > 0
    )
    coverage = unique_overlap / max(1, len(question_counter))
    density = overlap_total / max(1, len(sentence_terms))
    return coverage * 0.75 + density * 0.25


def question_type_bonus(question_type: str, sentence: str) -> float:
    lower = sentence.lower()

    if question_type == "why":
        markers = ("потому", "так как", "поэтому", "из-за", "вследствие", "чтобы")
        return 0.25 if any(marker in lower for marker in markers) else 0.0

    if question_type == "when":
        bonus = 0.0
        if DATE_OR_YEAR_REGEX.search(sentence):
            bonus += 0.22
        if any(
            marker in lower
            for marker in (
                "год",
                "году",
                "лет",
                "весной",
                "летом",
                "осенью",
                "зимой",
                "утром",
                "вечером",
                "ночью",
            )
        ):
            bonus += 0.1
        return bonus

    if question_type == "where":
        markers = (
            "в ",
            "на ",
            "из ",
            "около",
            "рядом",
            "внутри",
            "снаружи",
            "месте",
        )
        return 0.16 if any(marker in lower for marker in markers) else 0.0

    if question_type == "who":
        names = CAPITALIZED_WORD_REGEX.findall(sentence)
        return min(0.2, len(names) * 0.05)

    if question_type == "how":
        markers = ("так", "образом", "способ", "через", "с помощью", "путем")
        return 0.12 if any(marker in lower for marker in markers) else 0.0

    return 0.0


def select_diverse_sentences(candidates: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    if not candidates:
        return []

    remaining = candidates[:]
    selected: list[dict[str, Any]] = []
    max_score = max(item.get("score", 0.0) for item in remaining) or 1.0
    lambda_rel = 0.82

    while remaining and len(selected) < limit:
        if not selected:
            best_idx = max(range(len(remaining)), key=lambda idx: remaining[idx]["score"])
        else:
            best_idx = 0
            best_mmr = -1e9
            for idx, item in enumerate(remaining):
                relevance = item["score"] / max_score
                max_similarity = max(
                    jaccard_similarity(item.get("terms", []), chosen.get("terms", []))
                    for chosen in selected
                )
                mmr = lambda_rel * relevance - (1 - lambda_rel) * max_similarity
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = idx

        selected.append(remaining.pop(best_idx))

    return selected


def extractive_answer(
    question: str, fragments: list[dict[str, Any]], relaxed: bool = False
) -> str:
    question_terms = tokenize_terms(question)
    if not question_terms:
        return ""

    if is_generic_unfocused_question(question_terms) and not relaxed:
        return ""

    question_term_set = set(question_terms)
    focus_terms = query_focus_terms(question_terms)
    concrete_focus_terms = specific_focus_terms(question_terms)
    matching_sentence_terms = (
        concrete_focus_terms
        if concrete_focus_terms
        else focus_terms
        if focus_terms
        else question_term_set
    )

    required_sentence_overlap = minimum_overlap_terms(matching_sentence_terms)
    focus_sentence_terms = concrete_focus_terms if concrete_focus_terms else focus_terms
    required_focus_sentence_overlap = (
        minimum_focus_overlap(focus_sentence_terms) if focus_sentence_terms else 0
    )

    if relaxed:
        required_sentence_overlap = max(1, required_sentence_overlap - 1)
        if required_focus_sentence_overlap:
            required_focus_sentence_overlap = max(1, required_focus_sentence_overlap - 1)

    question_kind = detect_question_type(question)
    seen_sentences = set()
    sentence_candidates: list[dict[str, Any]] = []

    for fragment_rank, fragment in enumerate(fragments):
        fragment_weight = max(0.0, 1.0 - fragment_rank * 0.08)
        fragment_text = fragment.get("fragment", "")

        for sentence in re.split(r"(?<=[.!?])\s+", fragment_text):
            clean = sentence.strip()
            if len(clean) < 25:
                continue
            if clean.endswith("?"):
                continue

            fingerprint = clean.lower()
            if fingerprint == question.strip().lower():
                continue
            if fingerprint in seen_sentences:
                continue
            seen_sentences.add(fingerprint)

            sentence_terms = tokenize_terms(clean)
            sentence_term_set = set(sentence_terms)

            if len(matching_sentence_terms & sentence_term_set) < required_sentence_overlap:
                continue

            if (
                focus_sentence_terms
                and len(focus_sentence_terms & sentence_term_set) < required_focus_sentence_overlap
            ):
                continue

            overlap = lexical_overlap_score(question_terms, sentence_terms)
            if overlap <= 0:
                continue

            type_bonus = question_type_bonus(question_kind, clean)
            score = overlap * 0.82 + type_bonus + fragment_weight * 0.14

            if score >= MIN_FRAGMENT_SCORE:
                sentence_candidates.append(
                    {
                        "text": clean,
                        "score": score,
                        "terms": sentence_terms,
                    }
                )

    if not sentence_candidates:
        # Мягкий fallback: выбираем лучшее отдельное предложение из лучших фрагментов,
        # чтобы не терять ответ на специфичный вопрос из-за строгих порогов.
        fallback_candidates: list[dict[str, Any]] = []
        fallback_required_overlap = max(1, required_sentence_overlap - 1)
        fallback_required_focus_overlap = (
            max(1, required_focus_sentence_overlap - 1) if required_focus_sentence_overlap else 0
        )

        for fragment_rank, fragment in enumerate(fragments[:3]):
            fragment_weight = max(0.0, 1.0 - fragment_rank * 0.08)
            fragment_text = fragment.get("fragment", "")
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", fragment_text):
                clean = sentence.strip()
                if len(clean) < 25 or clean.endswith("?"):
                    continue

                sentence_terms = tokenize_terms(clean)
                sentence_term_set = set(sentence_terms)

                if len(matching_sentence_terms & sentence_term_set) < fallback_required_overlap:
                    continue

                if (
                    focus_sentence_terms
                    and len(focus_sentence_terms & sentence_term_set)
                    < fallback_required_focus_overlap
                ):
                    continue

                overlap = lexical_overlap_score(question_terms, sentence_terms)
                if overlap <= 0:
                    continue

                fallback_candidates.append(
                    {
                        "text": clean,
                        "score": overlap * 0.9 + fragment_weight * 0.1,
                        "terms": sentence_terms,
                    }
                )

        if not fallback_candidates:
            return ""

        fallback_candidates.sort(key=lambda item: item["score"], reverse=True)
        return fallback_candidates[0]["text"]

    sentence_candidates.sort(key=lambda item: item["score"], reverse=True)
    answer_limit = 1 if question_kind == "why" else 2 if question_kind in {"when", "where", "who", "how"} else 3
    selected = select_diverse_sentences(sentence_candidates, limit=answer_limit)
    return " ".join(item["text"] for item in selected)

@app.post("/api/case/upload")
async def upload_case_txt(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="Поддерживаются только .txt файлы")

    content = await file.read()
    text = decode_uploaded_txt(content)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Файл пустой или не содержит текст")

    ensure_case_storage()
    book_id = uuid.uuid4().hex[:12]
    book_path = CASE_STORAGE_DIR / f"{book_id}.txt"
    book_path.write_text(text, encoding="utf-8")

    metadata = load_case_metadata()
    metadata[book_id] = {
        "id": book_id,
        "original_filename": file.filename,
        "path": str(book_path),
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    save_case_metadata(metadata)
    CASE_CHUNK_CACHE.pop(book_id, None)

    return metadata[book_id]


@app.get("/api/case/books")
async def get_case_books():
    books = list(load_case_metadata().values())
    books.sort(key=lambda item: item.get("uploaded_at", ""), reverse=True)
    return books


@app.post("/api/case/search")
async def search_case_fragments(request: CaseSearchRequest):
    sources = build_case_sources()
    if not sources:
        return {
            "found": False,
            "message": "Сначала загрузите хотя бы одну книгу в формате .txt",
            "fragments": [],
        }

    fragments, message = search_fragments_in_sources(
        request.query,
        sources,
        request.top_k,
    )
    if not fragments:
        return {
            "found": False,
            "message": message,
            "fragments": [],
        }

    return {"found": True, "fragments": fragments}


@app.post("/api/case/ask")
async def ask_case_question(request: CaseAskRequest):
    sources = build_case_sources()
    if not sources:
        return {
            "found": False,
            "answer": "Сначала загрузите хотя бы одну книгу в формате .txt",
            "citations": [],
        }

    found, answer, citations = answer_question_in_sources(
        request.question,
        sources,
        request.top_k,
        request.citations_k,
    )
    return {
        "found": found,
        "answer": answer,
        "citations": citations,
    }


@app.get("/smart-search")
async def smart_search_page():
    page_path = Path(__file__).with_name("smart_search.html")
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="smart_search.html not found")
    return FileResponse(str(page_path), media_type="text/html")


@app.post("/api/books/search")
async def search_user_books(
    request: UserSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    books = resolve_user_books(db, current_user, request.book_ids)
    if not books:
        return {
            "found": False,
            "message": "Не найдено загруженных книг для поиска",
            "fragments": [],
        }

    sources = build_user_sources(books)
    fragments, message = search_fragments_in_sources(
        request.query,
        sources,
        request.top_k,
    )
    if not fragments:
        return {
            "found": False,
            "message": message,
            "fragments": [],
        }

    return {"found": True, "fragments": fragments}


@app.post("/api/books/ask")
async def ask_user_books(
    request: UserAskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    books = resolve_user_books(db, current_user, request.book_ids)
    if not books:
        return {
            "found": False,
            "answer": "Не найдено загруженных книг для поиска ответа.",
            "citations": [],
        }

    sources = build_user_sources(books)
    found, answer, citations = answer_question_in_sources(
        request.question,
        sources,
        request.top_k,
        request.citations_k,
    )
    return {
        "found": found,
        "answer": answer,
        "citations": citations,
    }


@app.get("/api/user/profile")
async def get_user_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    # Получаем или создаем статистику пользователя
    stats = current_user.stats
    if not stats:
        stats = UserStats(user_id=current_user.id)
        db.add(stats)
        db.commit()
        db.refresh(current_user)

    # Обновляем статистику на основе книг пользователя
    books_read_count = (
        db.query(Book)
        .filter(Book.user_id == current_user.id, Book.progress == 100)
        .count()
    )
    books_in_progress_count = (
        db.query(Book)
        .filter(Book.user_id == current_user.id, Book.progress < 100, Book.progress > 0)
        .count()
    )
    stats.books_read = books_read_count
    stats.books_in_progress = books_in_progress_count

    db.commit()
    # Получаем последнюю прочитанную книгу
    last_book = (
        db.query(Book)
        .filter(Book.user_id == current_user.id)
        .order_by(Book.last_read.desc().nullslast())
        .first()
    )

    return {
        "name": current_user.username,
        "email": current_user.email,
        "avatar": None,
        "stats": {
            "books_read": stats.books_read,
            "books_in_progress": stats.books_in_progress,
            "favorite_genres": stats.favorite_genres.split(",")
            if stats.favorite_genres
            else [],
        },
        "last_book": {
            "title": last_book.original_filename if last_book else None,
            "last_read": last_book.last_read if last_book else None,
        },
    }


# Добавляем новые эндпоинты
@app.post("/register")
async def register(user: dict = Body(...), db: Session = Depends(get_db)):
    if AUTH_DISABLED:
        guest_user = get_or_create_guest_user(db)
        token = jwt.encode({"user_id": guest_user.id}, SECRET_KEY, algorithm="HS256")
        return {"token": token, "auth_disabled": True}

    username = user.get("username")
    password = user.get("password")
    email = user.get("email")
    try:
        if not all([username, password, email]):
            raise HTTPException(status_code=400, detail="Все поля обязательны")

        if db.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=400, detail="Пользователь уже существует")

        password_hash = bcrypt.hash(password)
        new_user = User(username=username, password_hash=password_hash, email=email)
        db.add(new_user)
        db.commit()

        token = jwt.encode(
            {"user_id": new_user.id}, SECRET_KEY, algorithm="HS256"
        )
        return {"token": token}
    finally:
        db.close()


@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        if AUTH_DISABLED:
            guest_user = get_or_create_guest_user(db)
            token = jwt.encode({"user_id": guest_user.id}, SECRET_KEY, algorithm="HS256")
            return {"token": token, "auth_disabled": True}

        user = db.query(User).filter(User.username == username).first()
        if not user or not bcrypt.verify(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверные учетные данные")

        token = jwt.encode({"user_id": user.id}, SECRET_KEY, algorithm="HS256")
        return {"token": token}
    finally:
        db.close()


@app.get("/verify")
async def verify(current_user: User = Depends(get_current_user)):
    return {"valid": True, "user_id": current_user.id}


@app.get("/my-uploads")
async def get_user_uploads(current_user: User = Depends(get_current_user)):
    try:
        db = SessionLocal()
        books = db.query(Book).filter(Book.user_id == current_user.id).all()

        books_info = []
        for book in books:
            book_info = {
                "id": str(book.id),
                "filename": book.original_filename,
                "upload_date": book.upload_date.isoformat(),
                "progress": book.progress if hasattr(book, "progress") else 0,
                "cover_url": book.cover_url if hasattr(book, "cover_url") else None,
            }
            books_info.append(book_info)

        return books_info
    except Exception as e:
        logger.error(f"Error getting user uploads: {e}")
        raise HTTPException(status_code=500, detail="Error getting books")
    finally:
        db.close()


# Модифицируем существующий эндпоинт загрузки файла
@app.post("/upload-pdf/")
async def upload_book(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    add_prompt: str = Form(...),
    type_generation: str = Form(...),
    authorization: str = Header(None),
):
    try:
        if ALGORITHM_ONLY_MODE:
            raise HTTPException(
                status_code=410,
                detail="Инструмент отключен: проект работает в алгоритмическом режиме без внешних AI API.",
            )

        if AUTH_DISABLED:
            guest_db = SessionLocal()
            try:
                user_id = get_or_create_guest_user(guest_db).id
            finally:
                guest_db.close()
        else:
            if not authorization:
                raise HTTPException(status_code=401, detail="Требуется авторизация")
            token = authorization.split(" ")[1]
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user_id = payload["user_id"]

        file_name = file.filename
        # Определяем тип файла
        if file_name.lower().endswith(".fb2"):
            # Если файл FB2, обрабатываем его
            fb2_path = f"/tmp/fb2_files/{uuid.uuid4().hex}.fb2"
            with open(fb2_path, "wb") as buffer:
                buffer.write(await file.read())

            # Извлечение текста из FB2
            text_content = extract_text_from_fb2(fb2_path)
            text_file_path = fb2_path.replace(".fb2", ".txt")
        elif file_name.lower().endswith(".txt"):
            # Если файл TXT, просто сохраняем его
            text_file_path = f"/tmp/txt_files/{uuid.uuid4().hex}.txt"
            text_content = decode_uploaded_txt(await file.read())
        else:
            # Если формат не поддерживается
            raise HTTPException(
                status_code=400, detail="Поддерживаются только файлы FB2 или TXT."
            )

        # Сохранение текста для дальнейшей обработки
        with open(text_file_path, "w", encoding="utf-8") as text_file:
            text_file.write(text_content)

        # Запуск обработки запроса
        id_class, handler = await get_id_class(
            text_file_path, prompt, add_prompt, type_generation, file_name
        )

        if handler:
            # Сохраняем информацию о загруженной книге
            db = SessionLocal()
            new_book = Book(
                user_id=user_id,
                original_filename=file.filename,
                stored_filename=file.filename,
                file_path=text_file_path,
                file_size=os.path.getsize(text_file_path),
                file_type=file.filename.split(".")[-1].upper(),
                progress=0,
            )
            db.add(new_book)
            db.commit()

            return {"id_class": id_class}
        else:
            raise HTTPException(status_code=500, detail="Ошибка при создании потока.")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Ошибка при загрузке текста: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при загрузке текста.")


@app.get("/get-response/{id_class}")
async def get_response(id_class: str):
    if ALGORITHM_ONLY_MODE:
        raise HTTPException(
            status_code=410,
            detail="Инструмент отключен: проект работает в алгоритмическом режиме без внешних AI API.",
        )

    try:
        handler = class_dict.get(id_class, None)
        if handler:
            is_done, updated_messages = await handler.get_messages()
            return {"response": updated_messages, "is_done": is_done}
        raise HTTPException(status_code=404, detail="Обработчик не найден.")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Ошибка при получении ответа: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при получении ответа.")


# Функция для парсинга вопросов (если используется)
def parse_questions(text):
    questions = []
    for block in text.split("\n\n"):
        if "Вопрос:" in block and "Ответ:" in block:
            parts = block.split("\n")
            question = parts[0].replace("Вопрос:", "").strip()
            answer = parts[1].replace("Ответ:", "").strip()
            questions.append({"question": question, "answer": answer})
    return questions


@app.get("/get-image")
async def get_image(topic):
    if ALGORITHM_ONLY_MODE:
        raise HTTPException(
            status_code=410,
            detail="Инструмент отключен: проект работает в алгоритмическом режиме без внешних AI API.",
        )

    if client is None:
        raise HTTPException(
            status_code=503,
            detail="OpenAI client is not configured. Set OPENAI_API_KEY.",
        )
    completion = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": f"По тексту книги сделай промпт для генерации подходящей по смыслу и для осмысления книги. Текст: {topic}",
            },
        ],
    )
    res = completion.choices[0].message.content or ""
    print(res)
    id = uuid.uuid4().hex
    prompt = f"Generate an image of a {res}"

    image_path = await generate_image(
        prompt=prompt,
        height=512,  # Уменьшенное разрешение для экономии памяти
        width=512,
        steps=2,  # Снижение количества шагов для ускорения
        guidance=0,
        output_path=f"img_{id}.png",
    )

    return FileResponse(image_path, media_type="image/png")


@app.get("/get-audio")
async def get_audio():
    audio_path = Path(__file__).with_name("speech.mp3")
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="speech.mp3 not found")
    return FileResponse(
        str(audio_path),
        media_type="audio/mpeg",
        filename="speech.mp3",
    )


# Создаем директорию для загруженных файлов, если её нет
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Зависимость для работы с БД

# Пример функции получения текущего пользователя по токену


# Добавьте эндпоинт для загрузки файлов
@app.post("/upload")
async def upload_book(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Имя файла не передано")

        # Разрешаем только форматы, поддерживаемые интерфейсом библиотеки
        file_ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if file_ext not in {"txt", "fb2"}:
            raise HTTPException(
                status_code=400,
                detail="Поддерживаются только файлы .txt и .fb2",
            )

        # Создаем уникальное имя файла
        file_name = f"{uuid.uuid4().hex}.{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Файл пустой")

        if file_ext == "txt":
            # Нормализуем текст в UTF-8 при сохранении
            normalized_text = decode_uploaded_txt(content)
            if not normalized_text.strip():
                raise HTTPException(
                    status_code=400,
                    detail="TXT-файл не содержит читаемого текста",
                )
            with open(file_path, "w", encoding="utf-8") as buffer:
                buffer.write(normalized_text)
        else:
            # FB2 сохраняем как есть
            with open(file_path, "wb") as buffer:
                buffer.write(content)

        # Сохраняем информацию о книге
        new_book = Book(
            user_id=current_user.id,
            original_filename=file.filename,
            stored_filename=file_name,
            file_path=file_path,
            file_size=os.path.getsize(file_path),
            file_type=file_ext.upper(),
            progress=0,
            upload_date=datetime.utcnow(),
        )

        db.add(new_book)
        db.commit()

        return JSONResponse(
            {
                "id": new_book.id,
                "title": new_book.original_filename,
                "cover_url": "/static/default-cover.png",
                "progress": 0,
                "upload_date": new_book.upload_date.isoformat(),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Upload error: %s", e)
        raise HTTPException(status_code=500, detail="Ошибка при загрузке файла")


@app.get("/books")
async def get_user_books(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    books = db.query(Book).filter(Book.user_id == current_user.id).all()
    return [
        {
            "id": book.id,
            "title": book.original_filename,
            "cover_url": "/static/default-cover.png",
            "progress": book.progress,
            "upload_date": book.upload_date.isoformat(),
        }
        for book in books
    ]


@app.get("/books/{book_id}")
async def get_book_by_id(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        book = (
            db.query(Book)
            .filter(Book.id == book_id, Book.user_id == current_user.id)
            .first()
        )
        if not book:
            raise HTTPException(status_code=404, detail="Книга не найдена")

        content = extract_book_text(book)
        if content is None:
            content = ""

        return {
            "id": book.id,
            "title": book.original_filename,
            "content": content,
            "format": book.file_type.lower(),
            "progress": book.progress,
            "upload_date": book.upload_date.isoformat(),
        }
    except Exception as e:
        logging.error(f"Ошибка при получении книги: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при получении книги")


@app.get("/books/{book_id}/content")
async def get_book_content(
    book_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # Проверяем, что книга принадлежит пользователю
        book = (
            db.query(Book)
            .filter(Book.id == book_id, Book.user_id == current_user.id)
            .first()
        )

        if not book:
            raise HTTPException(status_code=404, detail="Книга не найдена")

        content = extract_book_text(book)
        return {"content": content}

    except Exception as e:
        logger.error(f"Error getting book content: {e}")
        raise HTTPException(
            status_code=500, detail="Ошибка получения содержимого книги"
        )


@app.post("/books/{book_id}/progress")
async def update_book_progress(
    book_id: int,
    progress: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        book = (
            db.query(Book)
            .filter(Book.id == book_id, Book.user_id == current_user.id)
            .first()
        )

        if not book:
            raise HTTPException(status_code=404, detail="Книга не найдена")

        book.progress = progress.get("progress", 0)
        db.commit()

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error updating book progress: {e}")
        raise HTTPException(status_code=500, detail="Ошибка обновления прогресса")


@app.delete("/books/{book_id}")
async def delete_book(
    book_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # Находим книгу, принадлежащую текущему пользователю
        book = (
            db.query(Book)
            .filter(Book.id == book_id, Book.user_id == current_user.id)
            .first()
        )

        if not book:
            raise HTTPException(status_code=404, detail="Книга не найдена")

        # Удаляем файл с диска
        try:
            if os.path.exists(book.file_path):
                os.remove(book.file_path)
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            # Продолжаем удаление записи из БД даже если файл не удалился

        # Удаляем запись из базы данных
        db.delete(book)
        db.commit()

        return {"status": "success", "message": "Книга успешно удалена"}

    except Exception as e:
        logger.error(f"Error deleting book: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при удалении книги")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)},
        headers=getattr(exc, "headers", None) or {},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",  # Меняем с 0.0.0.0 на localhost
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
