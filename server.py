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
import time
import copy
import zlib
import hashlib
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.exc import IntegrityError
from passlib.hash import bcrypt
from datetime import datetime
import jwt

# Удалим старую базу и создадим новую

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# В проекте используется только локальная алгоритмическая логика (без внешних AI API).
client = None

SECRET_KEY = os.getenv("BOOKVERSE_SECRET_KEY", "change-me-in-env")
AUTH_DISABLED = os.getenv("BOOKVERSE_DISABLE_AUTH", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALGORITHM_ONLY_MODE = os.getenv("BOOKVERSE_ALGO_ONLY", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LOCAL_LLM_ENABLED = os.getenv("BOOKVERSE_LOCAL_LLM_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LOCAL_LLM_BASE_URL = os.getenv("BOOKVERSE_LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434").rstrip(
    "/"
)
LOCAL_LLM_MODEL = os.getenv("BOOKVERSE_LOCAL_LLM_MODEL", "gemma3:1b")
LOCAL_LLM_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv(
        "BOOKVERSE_LOCAL_LLM_FALLBACK_MODELS",
        "gemma3:1b",
    ).split(",")
    if model.strip()
]
LOCAL_LLM_TIMEOUT_SEC = float(os.getenv("BOOKVERSE_LOCAL_LLM_TIMEOUT_SEC", "90"))
LOCAL_LLM_MAX_CITATIONS = int(os.getenv("BOOKVERSE_LOCAL_LLM_MAX_CITATIONS", "6"))

SUMMARY_WORD_LIMITS = {
    "high": 95,
    "medium": 170,
    "low": 250,
}
QUIZ_DIFFICULTY_MASKS = {
    "easy": 1,
    "medium": 2,
    "hard": 3,
}

VAGUE_ANSWER_MARKERS = (
    "что-то",
    "чем-то",
    "как-то",
    "каким-то образом",
    "в целом",
    "в общем",
    "занимается чем-то",
    "делает что-то",
    "происходит само собой",
    "что ему нравится",
)


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
    raise HTTPException(
        status_code=410,
        detail="Инструмент отключен: проект работает без сторонних AI API.",
    )


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
    raise RuntimeError("Legacy AI endpoint disabled: no external API mode is enabled.")


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
DB_PATH = Path(__file__).resolve().with_name("bookverse.db")
engine = create_engine(f"sqlite:///{DB_PATH}")
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
    guest_user = (
        db.query(User)
        .filter((User.username == "guest") | (User.email == "guest@bookverse.local"))
        .first()
    )
    if guest_user:
        return guest_user

    guest_user = User(
        username="guest",
        email="guest@bookverse.local",
        password_hash="auth-disabled",
    )
    db.add(guest_user)
    try:
        db.commit()
        db.refresh(guest_user)
        return guest_user
    except IntegrityError:
        # Защита от гонок: если параллельный запрос уже создал guest.
        db.rollback()
        existing = (
            db.query(User)
            .filter((User.username == "guest") | (User.email == "guest@bookverse.local"))
            .first()
        )
        if existing:
            return existing

    username = "guest1"
    email = "guest1@bookverse.local"
    suffix = 1
    while db.query(User).filter(User.username == username).first() or db.query(User).filter(
        User.email == email
    ).first():
        suffix += 1
        username = f"guest{suffix}"
        email = f"guest{suffix}@bookverse.local"

    fallback_guest = User(
        username=username,
        email=email,
        password_hash="auth-disabled",
    )
    db.add(fallback_guest)
    db.commit()
    db.refresh(fallback_guest)
    return fallback_guest


CASE_STORAGE_DIR = Path("case_books")
CASE_META_FILE = CASE_STORAGE_DIR / "index.json"
CASE_CHUNK_CACHE: dict[str, dict[str, Any]] = {}
USER_BOOK_CHUNK_CACHE: dict[str, dict[str, Any]] = {}
SEARCH_RESULT_CACHE: dict[str, dict[str, Any]] = {}
ASK_RESULT_CACHE: dict[str, dict[str, Any]] = {}
TOKEN_REGEX = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
MIN_FRAGMENT_SCORE = 0.08
RRF_K = int(os.getenv("BOOKVERSE_RRF_K", "60"))
SEARCH_CACHE_TTL_SEC = int(os.getenv("BOOKVERSE_SEARCH_CACHE_TTL_SEC", "600"))
ASK_CACHE_TTL_SEC = int(os.getenv("BOOKVERSE_ASK_CACHE_TTL_SEC", "600"))
RESULT_CACHE_MAX_ITEMS = int(os.getenv("BOOKVERSE_RESULT_CACHE_MAX_ITEMS", "250"))
NGRAM_SIZE = int(os.getenv("BOOKVERSE_NGRAM_SIZE", "3"))
HASH_EMBEDDING_DIM = int(os.getenv("BOOKVERSE_HASH_EMBEDDING_DIM", "384"))
CACHE_SCHEMA_VERSION = os.getenv("BOOKVERSE_CACHE_SCHEMA_VERSION", "2026-03-23-v2")
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
    strict_phrase: bool = Field(default=False)
    whole_words: bool = Field(default=False)
    chapter_number: int | None = Field(default=None, ge=1, le=5000)


class CaseAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    citations_k: int = Field(default=3, ge=1, le=5)
    answer_mode: str = Field(default="hybrid", max_length=32)
    local_model: str | None = Field(default=None, max_length=120)


class UserSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    book_ids: list[int] = Field(default_factory=list)
    strict_phrase: bool = Field(default=False)
    whole_words: bool = Field(default=False)
    chapter_number: int | None = Field(default=None, ge=1, le=5000)


class UserAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    citations_k: int = Field(default=3, ge=1, le=5)
    book_ids: list[int] = Field(default_factory=list)
    answer_mode: str = Field(default="hybrid", max_length=32)
    local_model: str | None = Field(default=None, max_length=120)


class UserSummaryRequest(BaseModel):
    compression_level: str = Field(default="medium", max_length=16)
    preferences: str | None = Field(default=None, max_length=300)
    top_k: int = Field(default=8, ge=3, le=20)
    citations_k: int = Field(default=4, ge=1, le=8)
    book_ids: list[int] = Field(default_factory=list)
    answer_mode: str = Field(default="hybrid", max_length=32)
    local_model: str | None = Field(default=None, max_length=120)


class UserQuizRequest(BaseModel):
    question_count: int = Field(default=6, ge=3, le=20)
    difficulty: str = Field(default="medium", max_length=16)
    preferences: str | None = Field(default=None, max_length=300)
    top_k: int = Field(default=14, ge=6, le=40)
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
            normalized_text = normalize_retrieval_text(normalized_chunk)
            char_ngrams = build_char_ngrams(normalized_text)
            embedding, embedding_norm = build_hash_embedding(terms)

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
                    "normalized_text": normalized_text,
                    "char_ngrams": char_ngrams,
                    "hash_embedding": embedding,
                    "hash_embedding_norm": embedding_norm,
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


def invalidate_result_caches() -> None:
    SEARCH_RESULT_CACHE.clear()
    ASK_RESULT_CACHE.clear()


def normalize_retrieval_text(text: str) -> str:
    lowered = str(text or "").lower().replace("ё", "е")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def build_char_ngrams(text: str, n: int = NGRAM_SIZE) -> set[str]:
    normalized = normalize_retrieval_text(text)
    if not normalized:
        return set()

    compact = normalized.replace(" ", "")
    if len(compact) <= n:
        return {compact} if compact else set()
    return {compact[idx : idx + n] for idx in range(0, len(compact) - n + 1)}


def char_ngram_jaccard(query_ngrams: set[str], chunk_ngrams: set[str]) -> float:
    if not query_ngrams or not chunk_ngrams:
        return 0.0
    union = query_ngrams | chunk_ngrams
    if not union:
        return 0.0
    return len(query_ngrams & chunk_ngrams) / len(union)


def build_hash_embedding(terms: list[str], dim: int = HASH_EMBEDDING_DIM) -> tuple[dict[int, float], float]:
    if not terms:
        return {}, 0.0

    raw_counts = Counter(terms)
    vector: dict[int, float] = {}
    for term, count in raw_counts.items():
        token = term.encode("utf-8", errors="ignore")
        if not token:
            continue
        idx = zlib.crc32(token) % max(8, dim)
        sign = -1.0 if (zlib.crc32(b"s:" + token) & 1) else 1.0
        weight = (1.0 + math.log(1.0 + count)) * sign
        vector[idx] = vector.get(idx, 0.0) + weight

    norm = math.sqrt(sum(value * value for value in vector.values()))
    return vector, norm


def sparse_cosine_similarity(
    left_vector: dict[int, float],
    left_norm: float,
    right_vector: dict[int, float],
    right_norm: float,
) -> float:
    if left_norm <= 1e-9 or right_norm <= 1e-9:
        return 0.0

    if len(left_vector) > len(right_vector):
        left_vector, right_vector = right_vector, left_vector
        left_norm, right_norm = right_norm, left_norm

    dot = 0.0
    for idx, value in left_vector.items():
        dot += value * right_vector.get(idx, 0.0)
    if dot <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def sources_signature(sources: list[tuple[Any, str, list[dict[str, Any]]]]) -> str:
    parts: list[str] = []
    for book_id, _, chunks in sorted(sources, key=lambda row: str(row[0])):
        chunk_count = len(chunks)
        max_end = max((int(chunk.get("end", 0)) for chunk in chunks), default=0)
        chapter_count = len({chunk.get("chapter_number") for chunk in chunks if chunk.get("chapter_number")})
        parts.append(f"{book_id}:{chunk_count}:{max_end}:{chapter_count}")

    digest_raw = "|".join(parts).encode("utf-8", errors="ignore")
    return hashlib.sha1(digest_raw).hexdigest()[:20]


def make_cache_key(prefix: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(serialized.encode("utf-8", errors="ignore")).hexdigest()
    return f"{prefix}:{digest}"


def cache_get(cache: dict[str, dict[str, Any]], key: str, ttl_sec: int) -> Any | None:
    entry = cache.get(key)
    if not entry:
        return None

    created_at = float(entry.get("created_at", 0.0))
    if created_at <= 0 or (time.time() - created_at) > max(1, ttl_sec):
        cache.pop(key, None)
        return None

    return copy.deepcopy(entry.get("value"))


def cache_set(
    cache: dict[str, dict[str, Any]],
    key: str,
    value: Any,
    max_items: int = RESULT_CACHE_MAX_ITEMS,
) -> None:
    now_ts = time.time()
    cache[key] = {
        "created_at": now_ts,
        "value": copy.deepcopy(value),
    }

    overflow = len(cache) - max(1, max_items)
    if overflow <= 0:
        return

    oldest_keys = sorted(cache.items(), key=lambda row: float(row[1].get("created_at", 0.0)))[:overflow]
    for stale_key, _ in oldest_keys:
        cache.pop(stale_key, None)


def build_search_cache_key(
    scope: str,
    query: str,
    top_k: int,
    source_sig: str,
    strict_phrase: bool = False,
    whole_words: bool = False,
    chapter_number: int | None = None,
) -> str:
    return make_cache_key(
        "search",
        {
            "scope": scope,
            "query": normalize_retrieval_text(query),
            "top_k": int(top_k),
            "sig": source_sig,
            "strict_phrase": bool(strict_phrase),
            "whole_words": bool(whole_words),
            "chapter_number": int(chapter_number) if chapter_number is not None else None,
            "schema": CACHE_SCHEMA_VERSION,
        },
    )


def build_ask_cache_key(
    scope: str,
    question: str,
    top_k: int,
    citations_k: int,
    answer_mode: str,
    local_model: str | None,
    source_sig: str,
) -> str:
    return make_cache_key(
        "ask",
        {
            "scope": scope,
            "question": normalize_retrieval_text(question),
            "top_k": int(top_k),
            "citations_k": int(citations_k),
            "answer_mode": str(answer_mode or "hybrid"),
            "local_model": str(local_model or "").strip().lower(),
            "sig": source_sig,
            "schema": CACHE_SCHEMA_VERSION,
        },
    )


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


def rerank_candidates_with_rrf(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []

    metric_names = ("bm25_score", "ngram_score", "semantic_score")
    rank_maps: dict[str, dict[tuple[Any, int], int]] = {}

    for metric in metric_names:
        ordered = sorted(
            candidates,
            key=lambda item: float(item.get(metric, 0.0)),
            reverse=True,
        )
        rank_maps[metric] = {
            (item.get("book_id"), int((item.get("location") or {}).get("char_start", 0))): rank + 1
            for rank, item in enumerate(ordered)
        }

    reranked: list[dict[str, Any]] = []
    for item in candidates:
        item_key = (item.get("book_id"), int((item.get("location") or {}).get("char_start", 0)))
        rrf_score = 0.0
        for metric in metric_names:
            rank = rank_maps.get(metric, {}).get(item_key, len(candidates))
            rrf_score += 1.0 / (RRF_K + rank)

        context_bonus = float(item.get("context_bonus", 0.0))
        final_score = rrf_score + max(-0.25, min(0.35, context_bonus * 0.45))
        item["score"] = round(final_score * 10.0, 4)
        reranked.append(item)

    reranked.sort(key=lambda row: row.get("score", 0.0), reverse=True)
    return reranked


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
        item.pop("bm25_score", None)
        item.pop("ngram_score", None)
        item.pop("semantic_score", None)
        item.pop("context_bonus", None)
        item.pop("gate_score", None)

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


def normalize_strict_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ё", "е")).strip()


def contains_exact_phrase(text: str, phrase: str) -> bool:
    normalized_text = normalize_strict_text(text)
    normalized_phrase = normalize_strict_text(phrase)
    if not normalized_phrase:
        return True
    return normalized_phrase in normalized_text


def contains_all_whole_words(text: str, query: str) -> bool:
    normalized_text = normalize_strict_text(text)
    tokens = [token.lower().replace("ё", "е") for token in TOKEN_REGEX.findall(str(query or ""))]
    if not tokens:
        return True

    for token in tokens:
        pattern = rf"(?<![A-Za-zА-Яа-яЁё0-9]){re.escape(token)}(?![A-Za-zА-Яа-яЁё0-9])"
        if not re.search(pattern, normalized_text, flags=re.IGNORECASE):
            return False
    return True


def rank_fragments_for_sources(
    query: str,
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
    relaxed: bool = False,
    chapter_number: int | None = None,
    strict_phrase: bool = False,
    whole_words: bool = False,
) -> list[dict[str, Any]]:
    query_terms = tokenize_terms(query)
    raw_query_tokens = [token.lower().replace("ё", "е") for token in TOKEN_REGEX.findall(query)]
    if not query_terms and raw_query_tokens:
        query_terms = [normalize_token(token) for token in raw_query_tokens if token]
    if not query_terms and not strict_phrase and not whole_words:
        return []

    query_normalized = normalize_retrieval_text(query)
    query_ngrams = build_char_ngrams(query_normalized)
    query_embedding, query_embedding_norm = build_hash_embedding(query_terms)
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

    if is_generic_unfocused_question(query_terms) and not relaxed and not (strict_phrase or whole_words):
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

            if strict_phrase and not contains_exact_phrase(text, query):
                continue
            if whole_words and not contains_all_whole_words(text, query):
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

            bm25_score = score_chunk(
                query,
                query_terms,
                query_counter,
                chunk,
                idf_map,
                avg_doc_len,
            )
            if bm25_score <= 0 and not relaxed:
                continue

            ngram_score = char_ngram_jaccard(query_ngrams, chunk.get("char_ngrams", set()))
            semantic_score = sparse_cosine_similarity(
                query_embedding,
                query_embedding_norm,
                chunk.get("hash_embedding", {}),
                float(chunk.get("hash_embedding_norm", 0.0)),
            )

            context_bonus = 0.0
            if position_preference != "any":
                max_end = max_end_by_book.get(book_id) or 1
                position_ratio = chunk.get("start", 0) / max(1, max_end)
                context_bonus += chunk_position_bonus(position_ratio, position_preference)

            context_bonus += chapter_proximity_bonus(requested_chapter, chunk.get("chapter_number"))
            context_bonus -= noise_penalty

            strict_bonus = 0.0
            if strict_phrase:
                strict_bonus += 0.34
            if whole_words:
                strict_bonus += 0.2

            gate_score = (
                bm25_score
                + ngram_score * 0.22
                + semantic_score * 0.24
                + context_bonus
                + strict_bonus
            )
            if gate_score < MIN_FRAGMENT_SCORE:
                continue

            candidates.append(
                {
                    "book_id": book_id,
                    "book_title": book_title,
                    "fragment": chunk["text"],
                    "score": round(gate_score, 6),
                    "bm25_score": round(bm25_score, 6),
                    "ngram_score": round(ngram_score, 6),
                    "semantic_score": round(semantic_score, 6),
                    "context_bonus": round(context_bonus, 6),
                    "gate_score": round(gate_score, 6),
                    "location": build_location_payload(chunk),
                    "_terms": chunk_terms,
                }
            )

    reranked = rerank_candidates_with_rrf(candidates)
    return select_diverse_fragments(reranked, top_k)


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
    strict_phrase: bool = False,
    whole_words: bool = False,
):
    return rank_fragments_for_sources(
        query,
        build_user_sources(books),
        top_k,
        relaxed=relaxed,
        chapter_number=chapter_number,
        strict_phrase=strict_phrase,
        whole_words=whole_words,
    )


def rank_case_fragments(
    query: str,
    top_k: int,
    relaxed: bool = False,
    chapter_number: int | None = None,
    strict_phrase: bool = False,
    whole_words: bool = False,
):
    return rank_fragments_for_sources(
        query,
        build_case_sources(),
        top_k,
        relaxed=relaxed,
        chapter_number=chapter_number,
        strict_phrase=strict_phrase,
        whole_words=whole_words,
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

GOAL_MARKERS = (
    "хоч",
    "мечта",
    "стрем",
    "цель",
    "желал",
    "желает",
    "намер",
    "хотел",
    "чтобы",
    "для того",
    "ради",
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


def trim_sentence_for_card(text: str, max_len: int = 180) -> str:
    clean = normalize_sentence_text(str(text or "").replace("\n", " "))
    if len(clean) <= max_len:
        return clean
    return f"{clean[: max_len - 3].rstrip()}..."


def collect_focus_rows_from_citations(
    focus_name: str,
    citations: list[dict[str, Any]],
    max_items: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    focus_key = normalize_name_token(focus_name) if focus_name else ""

    for citation in citations:
        location = citation.get("location") or {}
        chapter = location.get("chapter")
        fragment = str(citation.get("fragment") or "")
        sentences = extract_clean_sentences(fragment)
        if not sentences:
            fallback = trim_sentence_for_card(fragment)
            if fallback:
                sentences = [fallback]

        for sentence in sentences:
            text = trim_sentence_for_card(sentence, max_len=220)
            if not text:
                continue
            text_key = text.lower().replace("ё", "е")
            if text_key in seen:
                continue
            sentence_terms = set(tokenize_terms(text))
            mentions_focus = bool(focus_key and focus_key in sentence_terms)
            if focus_key and not mentions_focus:
                continue
            seen.add(text_key)
            rows.append({"text": text, "chapter": chapter})
            if len(rows) >= max_items:
                return rows

    if rows:
        return rows

    for citation in citations:
        location = citation.get("location") or {}
        text = trim_sentence_for_card(citation.get("fragment", ""), max_len=220)
        if not text:
            continue
        rows.append({"text": text, "chapter": location.get("chapter")})
        if len(rows) >= max_items:
            break
    return rows


def collect_character_goals(rows: list[dict[str, Any]], max_items: int = 3) -> list[str]:
    goals: list[str] = []
    seen: set[str] = set()
    for row in rows:
        text = str(row.get("text") or "")
        lowered = text.lower().replace("ё", "е")
        if not any(marker in lowered for marker in GOAL_MARKERS):
            continue
        compact = trim_sentence_for_card(text, max_len=120)
        key = compact.lower().replace("ё", "е")
        if not compact or key in seen:
            continue
        seen.add(key)
        goals.append(compact)
        if len(goals) >= max_items:
            break
    return goals


def build_character_evolution(rows: list[dict[str, Any]]) -> str:
    if len(rows) < 2:
        return ""

    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("chapter") if row.get("chapter") is not None else 10**9,
            row.get("text", ""),
        ),
    )
    first = ordered[0]
    last = ordered[-1]
    if first.get("text") == last.get("text") and len(ordered) > 1:
        last = ordered[-2]

    first_chapter = first.get("chapter")
    last_chapter = last.get("chapter")
    first_prefix = f"В начале (гл. {first_chapter})" if first_chapter is not None else "В начале"
    last_prefix = f"Позже (гл. {last_chapter})" if last_chapter is not None else "Позже"
    return (
        f"{first_prefix}: {trim_sentence_for_card(first.get('text', ''), max_len=130)} "
        f"{last_prefix}: {trim_sentence_for_card(last.get('text', ''), max_len=130)}"
    ).strip()


def collect_chapter_refs(citations: list[dict[str, Any]], max_items: int = 8) -> list[int]:
    refs: list[int] = []
    seen: set[int] = set()
    for citation in citations:
        chapter = (citation.get("location") or {}).get("chapter")
        if chapter is None:
            continue
        chapter_value = int(chapter)
        if chapter_value in seen:
            continue
        seen.add(chapter_value)
        refs.append(chapter_value)
        if len(refs) >= max_items:
            break
    return sorted(refs)


def build_timeline_items_for_response(
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    citations: list[dict[str, Any]],
    focus_name: str = "",
    max_items: int = 6,
) -> list[dict[str, Any]]:
    timeline_seed: list[dict[str, Any]] = citations[:]

    if focus_name:
        focus_query = f"{focus_name} ключевые события поступки".strip()
        focus_fragments, _ = rank_fragments_with_fallback(focus_query, sources, max_items * 2)
        timeline_seed = merge_fragments(focus_fragments, timeline_seed, max_items * 3)

    if len(timeline_seed) < max_items:
        overview = build_overview_fragments_for_sources(
            sources,
            max_items * 2,
            chapter_number=None,
            prefer_end=False,
            intent="events",
        )
        timeline_seed = merge_fragments(timeline_seed, overview, max_items * 3)

    ordered = sort_fragments_chronologically(timeline_seed)
    items: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for fragment in ordered:
        location = fragment.get("location") or {}
        chapter = location.get("chapter")
        sentences = extract_clean_sentences(fragment.get("fragment", ""))
        event_text = trim_sentence_for_card(sentences[0] if sentences else fragment.get("fragment", ""), max_len=220)
        if not event_text:
            continue
        fingerprint = (chapter, event_text.lower().replace("ё", "е"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        label = f"Глава {chapter}" if chapter is not None else f"Эпизод {len(items) + 1}"
        items.append(
            {
                "chapter": chapter,
                "label": label,
                "event": event_text,
                "book_title": fragment.get("book_title"),
            }
        )
        if len(items) >= max_items:
            break

    return items


def build_character_graph_payload(
    relation_graph: dict[str, Any],
    focus_name: str = "",
    max_edges: int = 10,
) -> dict[str, Any]:
    edges_raw = relation_graph.get("edges") or []
    nodes_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    focus_key = normalize_name_token(focus_name) if focus_name else ""

    for edge in edges_raw[:max_edges]:
        left = str(edge.get("a") or "").strip()
        right = str(edge.get("b") or "").strip()
        if not left or not right:
            continue
        left_key = normalize_name_token(left)
        right_key = normalize_name_token(right)
        nodes_map.setdefault(
            left,
            {"id": left, "label": left, "is_focus": bool(focus_key and left_key == focus_key)},
        )
        nodes_map.setdefault(
            right,
            {"id": right, "label": right, "is_focus": bool(focus_key and right_key == focus_key)},
        )
        edges.append(
            {
                "source": left,
                "target": right,
                "weight": int(edge.get("weight") or 1),
                "example": trim_sentence_for_card(edge.get("example", ""), max_len=160),
            }
        )

    nodes = list(nodes_map.values())
    return {
        "nodes": nodes,
        "edges": edges,
    }


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
            soft_pool = [
                item
                for item in working_candidates
                if item.get("text", "")
                and not is_dialogue_heavy_sentence(item.get("text", ""))
            ]
            if not soft_pool:
                soft_pool = [item for item in working_candidates if item.get("text", "")]
            if not soft_pool:
                return ""

            soft_pool.sort(
                key=lambda row: (
                    row.get("base_score", 0.0),
                    len(tokenize_terms(row.get("text", ""))),
                ),
                reverse=True,
            )
            soft_selected = soft_pool[:2]
            selected_text = " ".join(item.get("text", "") for item in soft_selected).strip()
            if not selected_text:
                return ""

            focus_in_selected = bool(
                focus_key
                and any(focus_key in set(item.get("name_keys", [])) for item in soft_selected)
            )
            if focus_name and (focus_confirmed or focus_in_selected):
                return (
                    f"Явного портретного описания героя {focus_name} в тексте немного, "
                    f"но его образ раскрывается через эпизоды: {selected_text}"
                ).strip()
            return (
                "Явного портретного описания героя в тексте немного, "
                f"но образ раскрывается через эпизоды: {selected_text}"
            ).strip()
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

        def collect_action_scored(require_focus: bool) -> list[tuple[float, dict[str, Any]]]:
            scored_rows: list[tuple[float, dict[str, Any]]] = []
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
                if require_focus and focus_set and not has_focus and overlap < 0.2 and action_hits < 2:
                    continue
                if dialogue_penalty > 0 and action_hits < 2 and overlap < 0.2:
                    continue
                scored_rows.append((score, item))
            return scored_rows

        action_scored = collect_action_scored(require_focus=True)
        if not action_scored and focus_set:
            # Если фокусный персонаж определён неточно, делаем второй проход без жёсткой привязки.
            action_scored = collect_action_scored(require_focus=False)

        if action_scored:
            selected = pick_top_scored_items(action_scored, 2, preserve_chronology=True)
        else:
            action_like = [
                item
                for item in timeline
                if count_marker_hits(item.get("terms", []), ACTION_MARKERS) > 0
                and not is_dialogue_heavy_sentence(item.get("text", ""))
            ]
            if action_like:
                selected = sample_timeline_items(action_like, 2, prefer_end=False)
            else:
                non_dialogue = [
                    item for item in timeline if not is_dialogue_heavy_sentence(item.get("text", ""))
                ]
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

        if not fragments and chapter_number is not None and intent != "chapter":
            fragments = build_overview_fragments_for_sources(
                sources,
                max(1, top_k),
                chapter_number=None,
                prefer_end=prefer_end,
                intent=overview_intent,
            )

        if intent == "chapter" and chapter_number is not None and not fragments:
            return "", []

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
    strict_phrase: bool = False,
    whole_words: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    fragments = rank_fragments_for_sources(
        query,
        sources,
        top_k,
        relaxed=False,
        chapter_number=chapter_number,
        strict_phrase=strict_phrase,
        whole_words=whole_words,
    )
    if fragments:
        return fragments, False

    fragments = rank_fragments_for_sources(
        query,
        sources,
        top_k,
        relaxed=True,
        chapter_number=chapter_number,
        strict_phrase=strict_phrase,
        whole_words=whole_words,
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
            strict_phrase=strict_phrase,
            whole_words=whole_words,
        )

    return fragments, True


def search_fragments_in_sources(
    query: str,
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
    top_k: int,
    strict_phrase: bool = False,
    whole_words: bool = False,
    chapter_number: int | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    chapter_number = chapter_number if chapter_number is not None else extract_requested_chapter(query)
    query_terms = tokenize_terms(query)

    if strict_phrase or whole_words:
        fragments, _ = rank_fragments_with_fallback(
            query,
            sources,
            top_k,
            chapter_number=chapter_number,
            strict_phrase=strict_phrase,
            whole_words=whole_words,
        )
        if fragments:
            return fragments, None
        return [], "Совпадения по строгим фильтрам не найдены."

    if is_generic_unfocused_question(query_terms) or is_explicit_general_question(query):
        intent = detect_generic_intent(query)
        if intent == "name_lookup":
            ranked_query = f"{query} {INTENT_HINT_QUERIES.get('name_lookup', '')}".strip()
            fragments, _ = rank_fragments_with_fallback(
                ranked_query,
                sources,
                top_k,
                chapter_number=chapter_number,
                strict_phrase=strict_phrase,
                whole_words=whole_words,
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
        strict_phrase=strict_phrase,
        whole_words=whole_words,
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
        if intent_guess == "chapter":
            requested_chapter = extract_requested_chapter(question)
            if requested_chapter is not None:
                return (
                    False,
                    f"Не удалось найти явные фрагменты по главе {requested_chapter}. Уточните номер главы или формулировку.",
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


def build_ask_metadata(
    question: str,
    citations: list[dict[str, Any]],
    sources: list[tuple[Any, str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    intent = detect_generic_intent(question)
    main_characters = detect_main_characters_from_fragments(citations, top_n=3) if citations else []
    if not main_characters:
        main_characters = detect_main_characters_from_sources(sources, top_n=3)
    focus_name = main_characters[0] if main_characters else ""
    relation_graph = build_character_relation_graph_from_sources(
        sources,
        top_characters=8,
        min_edge_weight=1,
    )

    metadata: dict[str, Any] = {
        "intent": intent,
        "main_characters": main_characters,
        "timeline": build_timeline_items_for_response(
            sources,
            citations,
            focus_name=focus_name,
            max_items=6,
        ),
        "character_graph": build_character_graph_payload(
            relation_graph,
            focus_name=focus_name,
            max_edges=10,
        ),
    }

    if main_characters:
        focus_key = normalize_name_token(focus_name)
        selected_note = ""
        focus_rows = collect_focus_rows_from_citations(focus_name, citations, max_items=12)
        goals = collect_character_goals(focus_rows, max_items=3)
        chapter_refs = collect_chapter_refs(citations, max_items=8)
        evolution = build_character_evolution(focus_rows)

        for citation in citations:
            fragment = normalize_sentence_text((citation.get("fragment") or "").replace("\n", " "))
            if not fragment:
                continue
            normalized_fragment = fragment.lower().replace("ё", "е")
            if focus_key and focus_key in normalized_fragment:
                selected_note = fragment[:280]
                break
            if not selected_note:
                selected_note = fragment[:280]

        if not selected_note:
            selected_note = "Собрано по найденным цитатам из книги."

        metadata["character_card"] = {
            "name": focus_name,
            "focus": intent,
            "role": "",
            "traits": [],
            "actions": [],
            "relations": [],
            "goals": goals,
            "evolution": evolution,
            "chapter_refs": chapter_refs,
            "note": selected_note,
        }

    return metadata


MALE_GENDER_PATTERNS = (
    r"\bон\b",
    r"\bего\b",
    r"\bему\b",
    r"\bним\b",
    r"\bнего\b",
    r"\bмужчин\w*\b",
    r"\bстарик\w*\b",
    r"\bюнош\w*\b",
    r"\bпарен\w*\b",
    r"\bмонах\w*\b",
    r"\bкапитан\w*\b",
    r"\bотец\b",
    r"\bсын\w*\b",
    r"\bбрат\w*\b",
    r"\bгосподин\w*\b",
)

FEMALE_GENDER_PATTERNS = (
    r"\bона\b",
    r"\bее\b",
    r"\bеё\b",
    r"\bей\b",
    r"\bне[йю]\b",
    r"\bженщин\w*\b",
    r"\bдевушк\w*\b",
    r"\bстарух\w*\b",
    r"\bмонахин\w*\b",
    r"\bмать\b",
    r"\bдоч\w*\b",
    r"\bсестр\w*\b",
    r"\bгоспож\w*\b",
)

MALE_NAME_ENDING_EXCEPTIONS = {
    "илья",
    "никита",
    "кузьма",
    "лука",
    "фома",
    "савва",
    "миша",
    "паша",
    "саша",
}


def normalize_gender_value(raw_value: str | None) -> str:
    value = str(raw_value or "").strip().lower().replace("ё", "е")
    if value in {"male", "m", "man", "masculine", "м", "муж", "мужской", "он"}:
        return "male"
    if value in {"female", "f", "woman", "feminine", "ж", "жен", "женский", "она"}:
        return "female"
    return "unknown"


def gender_label(value: str) -> str:
    normalized = normalize_gender_value(value)
    if normalized == "male":
        return "мужской"
    if normalized == "female":
        return "женский"
    return "не определен"


def sentence_mentions_focus_name(sentence: str, focus_name: str) -> bool:
    normalized_sentence = sentence.lower().replace("ё", "е")
    focus_key = normalize_name_token(focus_name)
    if focus_key and re.search(rf"\b{re.escape(focus_key)}\w*\b", normalized_sentence):
        return True

    for term in tokenize_terms(focus_name):
        if len(term) < 3:
            continue
        if re.search(rf"\b{re.escape(term)}\w*\b", normalized_sentence):
            return True
    return False


def count_gender_markers(text: str) -> tuple[int, int]:
    normalized = text.lower().replace("ё", "е")
    male_hits = sum(len(re.findall(pattern, normalized)) for pattern in MALE_GENDER_PATTERNS)
    female_hits = sum(len(re.findall(pattern, normalized)) for pattern in FEMALE_GENDER_PATTERNS)
    return male_hits, female_hits


def infer_character_gender(
    focus_name: str,
    citations: list[dict[str, Any]],
) -> tuple[str, int]:
    focus_sentences: list[str] = []
    fallback_sentences: list[str] = []

    for citation in citations:
        raw_fragment = str(citation.get("fragment") or "")
        if not raw_fragment.strip():
            continue
        sentences = extract_clean_sentences(raw_fragment) or [normalize_sentence_text(raw_fragment)]
        for sentence in sentences:
            clean = normalize_sentence_text(sentence)
            if not clean:
                continue
            fallback_sentences.append(clean)
            if sentence_mentions_focus_name(clean, focus_name):
                focus_sentences.append(clean)

    selected_sentences = focus_sentences if focus_sentences else fallback_sentences
    male_hits = 0
    female_hits = 0
    for sentence in selected_sentences:
        sentence_male, sentence_female = count_gender_markers(sentence)
        male_hits += sentence_male
        female_hits += sentence_female

    # Слабая эвристика по окончанию имени, только когда явных маркеров мало.
    focus_word = (focus_name or "").strip().split()[-1].lower().replace("ё", "е") if focus_name else ""
    if focus_word:
        if (
            focus_word.endswith(("а", "я"))
            and focus_word not in MALE_NAME_ENDING_EXCEPTIONS
            and male_hits <= female_hits + 1
        ):
            female_hits += 1
        elif not focus_word.endswith(("а", "я")) and female_hits <= male_hits + 1:
            male_hits += 1

    if male_hits >= female_hits + 2:
        return "male", male_hits - female_hits
    if female_hits >= male_hits + 2:
        return "female", female_hits - male_hits
    return "unknown", abs(male_hits - female_hits)


def strip_markdown_fences(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    clean = strip_markdown_fences(text)
    if not clean:
        return None
    try:
        parsed = json.loads(clean)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def extract_labeled_value(text: str, labels: tuple[str, ...]) -> str:
    if not text:
        return ""
    label_group = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:^|\n)\s*(?:{label_group})\s*[:\-]\s*([^\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return normalize_sentence_text(match.group(1))


def parse_gender_from_text(raw_value: str, fallback_gender: str) -> str:
    normalized = str(raw_value or "").strip().lower().replace("ё", "е")
    if not normalized:
        return normalize_gender_value(fallback_gender)
    if any(marker in normalized for marker in ("male", "муж", "man", "masculine")):
        return "male"
    if any(marker in normalized for marker in ("female", "жен", "woman", "feminine")):
        return "female"
    return normalize_gender_value(fallback_gender)


def parse_character_card_from_text(
    raw_text: str,
    focus_name: str,
    fallback_gender: str,
) -> dict[str, Any] | None:
    clean = strip_markdown_fences(raw_text)
    if not clean:
        return None

    compact_text = clean.replace("\r", "\n")
    name_value = extract_labeled_value(compact_text, ("name", "имя", "герой", "персонаж"))
    if name_value and normalize_name_token(name_value) != normalize_name_token(focus_name):
        name_value = focus_name
    elif not name_value:
        name_value = focus_name

    role_value = extract_labeled_value(compact_text, ("role", "роль"))
    traits_raw = extract_labeled_value(compact_text, ("traits", "черты"))
    actions_raw = extract_labeled_value(compact_text, ("actions", "действия"))
    goals_raw = extract_labeled_value(compact_text, ("goals", "цели"))
    relations_raw = extract_labeled_value(compact_text, ("relations", "связи", "отношения"))
    evolution_raw = extract_labeled_value(compact_text, ("evolution", "эволюция", "изменения"))
    note_value = extract_labeled_value(compact_text, ("note", "описание", "summary", "итог"))
    gender_raw = extract_labeled_value(compact_text, ("gender", "пол"))

    if not note_value:
        candidate_lines: list[str] = []
        for line in compact_text.splitlines():
            cleaned_line = normalize_sentence_text(line.strip(" -*•\t"))
            if not cleaned_line:
                continue
            lowered = cleaned_line.lower().replace("ё", "е")
            if re.match(
                r"^(name|имя|gender|пол|role|роль|traits|черты|actions|действия|goals|цели|relations|связи|отношения|evolution|эволюция|изменения|note|описание|summary|итог)\s*[:\-]",
                lowered,
            ):
                continue
            if cleaned_line in {"{", "}"}:
                continue
            candidate_lines.append(cleaned_line)
        if candidate_lines:
            note_value = " ".join(candidate_lines[:2])

    if not note_value:
        return None

    return {
        "name": name_value,
        "gender": parse_gender_from_text(gender_raw, fallback_gender),
        "role": role_value,
        "traits": normalize_card_list(str(traits_raw).replace("•", ","), max_items=3),
        "actions": normalize_card_list(str(actions_raw).replace("•", ","), max_items=3),
        "goals": normalize_card_list(str(goals_raw).replace("•", ","), max_items=3),
        "relations": normalize_card_list(str(relations_raw).replace("•", ","), max_items=3),
        "evolution": normalize_sentence_text(str(evolution_raw or "")),
        "note": note_value,
    }


def build_character_card_llm_prompt(
    question: str,
    intent: str,
    focus_name: str,
    base_note: str,
    citations: list[dict[str, Any]],
    detected_gender: str,
) -> str:
    source_blocks = build_prompt_citation_blocks(citations)
    sources_text = "\n\n".join(source_blocks) if source_blocks else "(цитаты отсутствуют)"
    safe_question = str(question or "").strip()
    safe_base_note = str(base_note or "").strip()
    safe_focus_name = str(focus_name or "").strip()
    safe_intent = str(intent or "").strip()
    gender_hint = gender_label(detected_gender)

    return (
        "Сформируй карточку героя по цитатам.\n"
        "Нельзя добавлять факты вне цитат.\n"
        "Пиши кратко и естественно на русском.\n"
        "Старайся использовать имя героя вместо местоимений, чтобы не ошибиться в роде.\n"
        "Избегай общих слов вроде «чем-то», «как-то», «в целом».\n"
        f"Предварительная эвристика по полу: {gender_hint}.\n"
        "Верни ТОЛЬКО JSON без markdown:\n"
        "{\"name\":\"...\",\"gender\":\"male|female|unknown\",\"role\":\"...\",\"traits\":[\"...\"],"
        "\"actions\":[\"...\"],\"goals\":[\"...\"],\"relations\":[\"...\"],"
        "\"evolution\":\"...\",\"note\":\"...\"}\n"
        "- role: короткая роль героя (до 60 символов).\n"
        "- traits/actions/goals/relations: по 1-3 коротких пункта.\n"
        "- evolution: 1-2 фразы, как меняется герой между главами.\n"
        "- note: 1-3 предложения, максимум 320 символов, с 1 конкретным действием героя.\n"
        "- name: не меняй, если в цитатах нет явного другого варианта.\n\n"
        f"Вопрос:\n{safe_question}\n\n"
        f"Интент:\n{safe_intent}\n\n"
        f"Герой:\n{safe_focus_name}\n\n"
        f"Алгоритмический черновик карточки:\n{safe_base_note}\n\n"
        f"Цитаты:\n{sources_text}\n"
    )


def is_character_card_note_grounded(note_text: str, citations: list[dict[str, Any]]) -> bool:
    normalized = str(note_text or "").strip()
    if not normalized:
        return False
    if has_direct_quote_overlap(normalized, citations):
        return True

    note_terms = [term for term in tokenize_terms(normalized) if len(term) >= 4]
    if not note_terms:
        return False
    citation_terms = collect_citation_terms(citations)
    if not citation_terms:
        return False
    return len(set(note_terms) & citation_terms) >= 1


def align_text_gender(text: str, target_gender: str) -> str:
    content = str(text or "")
    if not content:
        return ""

    normalized_gender = normalize_gender_value(target_gender)
    if normalized_gender == "male":
        replacements = (
            (r"\bона\b", "он"),
            (r"\bОна\b", "Он"),
            (r"\bеё\b", "его"),
            (r"\bЕё\b", "Его"),
            (r"\bее\b", "его"),
            (r"\bЕе\b", "Его"),
            (r"\bей\b", "ему"),
            (r"\bЕй\b", "Ему"),
            (r"\bней\b", "нем"),
            (r"\bНей\b", "Нем"),
            (r"\bнею\b", "ним"),
            (r"\bНею\b", "Ним"),
            (r"\bсама\b", "сам"),
            (r"\bСама\b", "Сам"),
        )
    elif normalized_gender == "female":
        replacements = (
            (r"\bон\b", "она"),
            (r"\bОн\b", "Она"),
            (r"\bего\b", "ее"),
            (r"\bЕго\b", "Ее"),
            (r"\bему\b", "ей"),
            (r"\bЕму\b", "Ей"),
            (r"\bним\b", "нею"),
            (r"\bНим\b", "Нею"),
            (r"\bнего\b", "нее"),
            (r"\bНего\b", "Нее"),
            (r"\bсам\b", "сама"),
            (r"\bСам\b", "Сама"),
        )
    else:
        return content

    result = content
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    return result


def normalize_card_list(raw_value: Any, max_items: int = 3, max_len: int = 70) -> list[str]:
    if isinstance(raw_value, str):
        values = [part.strip() for part in re.split(r"[,\n;]+", raw_value) if part.strip()]
    elif isinstance(raw_value, list):
        values = [str(item).strip() for item in raw_value if str(item).strip()]
    else:
        values = []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_sentence_text(value)
        if not normalized:
            continue
        key = normalized.lower().replace("ё", "е")
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized[:max_len])
        if len(cleaned) >= max_items:
            break
    return cleaned


def keep_grounded_card_items(items: list[str], citations: list[dict[str, Any]]) -> list[str]:
    if not items:
        return []
    citation_terms = collect_citation_terms(citations)
    if not citation_terms:
        return []

    grounded: list[str] = []
    for item in items:
        item_terms = {term for term in tokenize_terms(item) if len(term) >= 3}
        if not item_terms:
            continue
        if len(item_terms & citation_terms) >= 1:
            grounded.append(item)
    return grounded


def enhance_character_card_with_llm(
    question: str,
    citations: list[dict[str, Any]],
    metadata: dict[str, Any],
    requested_model: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    payload = metadata.get("character_card")
    if not isinstance(payload, dict):
        return metadata, None

    focus_name = str(payload.get("name") or "").strip()
    if not focus_name:
        return metadata, None

    base_note = str(payload.get("note") or "").strip()
    intent = str(metadata.get("intent") or payload.get("focus") or "plot")
    detected_gender, detected_confidence = infer_character_gender(focus_name, citations)

    # Даже без LLM сохраняем оценку пола, чтобы UI не вводил в заблуждение.
    payload["gender"] = detected_gender
    payload["gender_label"] = gender_label(detected_gender)
    payload["mode"] = payload.get("mode") or "algorithm"
    payload["role"] = str(payload.get("role") or "").strip()
    payload["traits"] = normalize_card_list(payload.get("traits") or [])
    payload["actions"] = normalize_card_list(payload.get("actions") or [])
    payload["goals"] = normalize_card_list(payload.get("goals") or [])
    payload["relations"] = normalize_card_list(payload.get("relations") or [])
    payload["evolution"] = trim_sentence_for_card(payload.get("evolution", ""), max_len=260)
    payload["chapter_refs"] = sorted(
        {
            int(chapter)
            for chapter in (payload.get("chapter_refs") or [])
            if str(chapter).isdigit()
        }
    )[:8]
    payload["note"] = align_text_gender(base_note, detected_gender) if base_note else base_note
    metadata["character_card"] = payload

    if not LOCAL_LLM_ENABLED or not citations:
        return metadata, None

    prompt = build_character_card_llm_prompt(
        question=question,
        intent=intent,
        focus_name=focus_name,
        base_note=base_note,
        citations=citations,
        detected_gender=detected_gender,
    )
    raw_card_text, llm_note = request_local_llm(
        prompt,
        requested_model=requested_model,
        temperature=0.2,
        num_predict=240,
    )
    if not raw_card_text:
        return metadata, llm_note

    parsed = extract_first_json_object(raw_card_text)
    parsed_from_text = False
    if not parsed:
        parsed = parse_character_card_from_text(
            raw_card_text,
            focus_name=focus_name,
            fallback_gender=detected_gender,
        )
        parsed_from_text = bool(parsed)
    if not parsed:
        return metadata, "LLM вернула неструктурированный ответ, оставлена алгоритмическая карточка."

    llm_name = str(parsed.get("name") or focus_name).strip()
    if normalize_name_token(llm_name) != normalize_name_token(focus_name):
        llm_name = focus_name

    llm_gender = normalize_gender_value(str(parsed.get("gender") or ""))
    final_gender = llm_gender if llm_gender != "unknown" else detected_gender
    if detected_gender != "unknown" and detected_confidence >= 1 and llm_gender != detected_gender:
        final_gender = detected_gender

    llm_note_text = normalize_sentence_text(str(parsed.get("note") or "").replace("\n", " "))
    if not llm_note_text:
        return metadata, "LLM не заполнила описание карточки, оставлена алгоритмическая карточка."

    if not is_character_card_note_grounded(llm_note_text, citations):
        evidence_text, _ = extract_evidence_sentence(
            " ".join(str(citation.get("fragment") or "") for citation in citations),
            {term for term in tokenize_terms(question) if len(term) >= 3},
            {term for term in tokenize_terms(focus_name) if len(term) >= 3},
        )
        llm_note_text = normalize_sentence_text(evidence_text)
        if not llm_note_text:
            return metadata, "LLM-карточка не прошла проверку по цитатам, оставлена алгоритмическая карточка."

    llm_note_text = align_text_gender(llm_note_text, final_gender)
    if len(llm_note_text) > 320:
        llm_note_text = llm_note_text[:317].rstrip() + "..."

    llm_role = normalize_sentence_text(str(parsed.get("role") or ""))
    if len(llm_role) > 60:
        llm_role = llm_role[:57].rstrip() + "..."
    llm_traits = keep_grounded_card_items(normalize_card_list(parsed.get("traits"), max_items=3), citations)
    llm_actions = keep_grounded_card_items(normalize_card_list(parsed.get("actions"), max_items=3), citations)
    llm_goals = keep_grounded_card_items(normalize_card_list(parsed.get("goals"), max_items=3), citations)
    llm_relations = keep_grounded_card_items(normalize_card_list(parsed.get("relations"), max_items=3), citations)
    llm_evolution = trim_sentence_for_card(str(parsed.get("evolution") or ""), max_len=260)
    if llm_evolution and not is_character_card_note_grounded(llm_evolution, citations):
        llm_evolution = ""
    if not llm_role:
        llm_role = str(payload.get("role") or "").strip()
    if not llm_traits:
        llm_traits = normalize_card_list(payload.get("traits"), max_items=3)
    if not llm_actions:
        llm_actions = normalize_card_list(payload.get("actions"), max_items=3)
    if not llm_goals:
        llm_goals = normalize_card_list(payload.get("goals"), max_items=3)
    if not llm_relations:
        llm_relations = normalize_card_list(payload.get("relations"), max_items=3)
    if not llm_evolution:
        llm_evolution = trim_sentence_for_card(payload.get("evolution", ""), max_len=260)

    chapter_refs = sorted(
        {
            int(chapter)
            for chapter in (payload.get("chapter_refs") or collect_chapter_refs(citations, max_items=8))
            if str(chapter).isdigit()
        }
    )[:8]

    metadata["character_card"] = {
        "name": llm_name,
        "focus": intent,
        "role": llm_role,
        "traits": llm_traits,
        "actions": llm_actions,
        "goals": llm_goals,
        "relations": llm_relations,
        "evolution": llm_evolution,
        "chapter_refs": chapter_refs,
        "note": llm_note_text,
        "gender": final_gender,
        "gender_label": gender_label(final_gender),
        "mode": "llm",
    }
    success_note = (
        "Карточка героя сгенерирована локальной LLM по цитатам."
        if not parsed_from_text
        else "Карточка героя сгенерирована локальной LLM (разбор свободного ответа) по цитатам."
    )
    if llm_note:
        success_note = f"{success_note} {llm_note}".strip()
    return metadata, success_note


def normalize_answer_mode(raw_mode: str | None) -> str:
    # В пользовательском продукте оставлен только гибридный режим.
    _ = raw_mode
    return "hybrid"


def format_citation_location(citation: dict[str, Any]) -> str:
    location = citation.get("location") or {}
    parts: list[str] = []
    book_title = str(citation.get("book_title") or "").strip()
    if book_title:
        parts.append(book_title)

    chapter = location.get("chapter")
    if chapter is not None:
        parts.append(f"глава {chapter}")

    line_start = location.get("line_start")
    line_end = location.get("line_end")
    if line_start and line_end:
        parts.append(f"строки {line_start}-{line_end}")

    return ", ".join(parts) if parts else "Источник"


def build_prompt_citation_blocks(citations: list[dict[str, Any]]) -> list[str]:
    source_blocks: list[str] = []
    for index, citation in enumerate(citations[: max(1, LOCAL_LLM_MAX_CITATIONS)], start=1):
        fragment = str(citation.get("fragment") or "").strip()
        if not fragment:
            continue
        location = format_citation_location(citation)
        source_blocks.append(f"[{index}] {location}\n{fragment}")
    return source_blocks


def build_local_llm_prompt(question: str, citations: list[dict[str, Any]]) -> str:
    source_blocks = build_prompt_citation_blocks(citations)

    sources_text = "\n\n".join(source_blocks) if source_blocks else "(цитаты отсутствуют)"
    safe_question = str(question or "").strip()

    return (
        "Ты помощник по книгам. Отвечай только по цитатам из контекста ниже.\n"
        "Нельзя добавлять факты, которых нет в цитатах.\n"
        "Если данных недостаточно, ответь: "
        "\"В загруженных книгах недостаточно данных для точного ответа.\".\n\n"
        f"Вопрос пользователя:\n{safe_question}\n\n"
        f"Цитаты:\n{sources_text}\n\n"
        "Формат ответа:\n"
        "1) Короткий ответ на русском.\n"
        "2) Без перечисления внутренних рассуждений.\n"
    )


def build_intent_specific_hybrid_instruction(intent: str) -> str:
    normalized_intent = str(intent or "").strip().lower()
    if normalized_intent == "actions":
        return (
            "- Дай 2-3 конкретных действия героя из цитат.\n"
            "- Используй глаголы действия (сделал, пошел, сказал, решил, увидел и т.д.).\n"
            "- Запрещены размытые формулировки вроде «делает что-то», «чем-то занимается»."
        )
    if normalized_intent == "motivation":
        return (
            "- Укажи причину и действие: что сделал герой и почему.\n"
            "- Каждый тезис должен опираться на цитату."
        )
    if normalized_intent == "character_description":
        return (
            "- Укажи 2-3 наблюдаемых черты героя, прямо подтвержденных цитатами.\n"
            "- Избегай психологических догадок, которых нет в тексте."
        )
    if normalized_intent == "relationships":
        return (
            "- Назови участников отношений и тип связи (друг, союзник, конфликт и т.п.), "
            "только если это видно из цитат."
        )
    if normalized_intent in {"plot", "beginning", "middle", "finale", "arc"}:
        return (
            "- Опиши ход событий конкретно: завязка, развитие, итог (или нужный участок книги).\n"
            "- Не заменяй факты общими словами."
        )
    if normalized_intent == "chapter":
        return "- Отвечай только по указанной главе и не выходи за ее пределы."
    return "- Дай конкретный ответ по цитатам без размытых формулировок."


def build_hybrid_llm_prompt(
    question: str,
    citations: list[dict[str, Any]],
    base_answer: str,
) -> str:
    source_blocks = build_prompt_citation_blocks(citations)
    sources_text = "\n\n".join(source_blocks) if source_blocks else "(цитаты отсутствуют)"
    safe_question = str(question or "").strip()
    safe_base_answer = str(base_answer or "").strip()
    intent = detect_generic_intent(question)
    intent_hint = build_intent_specific_hybrid_instruction(intent)

    return (
        "Ты помощник по книгам в гибридном режиме.\n"
        "Ниже дан алгоритмический черновик ответа и цитаты-основания.\n"
        "Нужно улучшить ответ и обязательно переформулировать его более естественно.\n"
        "Используй только факты из цитат, ничего не добавляй от себя.\n"
        "Если пол персонажа неочевиден, избегай местоимений он/она и используй имя.\n"
        "Добавь 1 короткую прямую цитату из источника в кавычках «...».\n"
        "Запрещены фразы «что-то», «как-то», «в целом», «делает что-то».\n"
        "Если данных недостаточно, ответь строго: "
        "\"В загруженных книгах недостаточно данных для точного ответа.\".\n\n"
        f"Вопрос:\n{safe_question}\n\n"
        f"Интент:\n{intent}\n\n"
        f"Требования по интенту:\n{intent_hint}\n\n"
        f"Алгоритмический черновик:\n{safe_base_answer}\n\n"
        f"Цитаты:\n{sources_text}\n\n"
        "Формат:\n"
        "1) Короткий, связный ответ на русском (2-4 предложения).\n"
        "2) Без новых фактов вне цитат.\n"
    )


def request_local_llm(
    prompt: str,
    requested_model: str | None = None,
    temperature: float = 0.2,
    num_predict: int = 256,
) -> tuple[str | None, str | None]:
    if not LOCAL_LLM_ENABLED:
        return None, "Локальная LLM отключена в настройках сервера."

    def build_model_candidates() -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for model in [str(requested_model or "").strip(), LOCAL_LLM_MODEL, *LOCAL_LLM_FALLBACK_MODELS]:
            clean = str(model or "").strip()
            if not clean:
                continue
            lowered = clean.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            ordered.append(clean)
        return ordered

    model_candidates = build_model_candidates()
    requested_clean = str(requested_model or "").strip()
    last_note: str | None = None

    for index, model in enumerate(model_candidates):
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_obj = urllib_request.Request(
            f"{LOCAL_LLM_BASE_URL}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib_request.urlopen(request_obj, timeout=LOCAL_LLM_TIMEOUT_SEC) as response:
                raw = response.read().decode("utf-8", errors="replace")

            answer = ""
            try:
                data = json.loads(raw)
                answer = str(data.get("response") or "").strip()
            except json.JSONDecodeError:
                # На случай, если сервер вернул JSONL (построчные чанки), собираем текст ответа вручную.
                fragments: list[str] = []
                for line in raw.splitlines():
                    cleaned = line.strip()
                    if not cleaned:
                        continue
                    try:
                        line_obj = json.loads(cleaned)
                    except json.JSONDecodeError:
                        continue
                    chunk = str(line_obj.get("response") or "")
                    if chunk:
                        fragments.append(chunk)
                answer = "".join(fragments).strip()

            if not answer:
                last_note = f"Локальная LLM '{model}' вернула пустой ответ."
                continue

            switched_model = bool(requested_clean) and model.lower() != requested_clean.lower()
            success_note = (
                f"Исходная модель '{requested_clean}' не сработала, использована более легкая '{model}'."
                if switched_model
                else None
            )
            return answer, success_note
        except HTTPError as error:
            error_body = ""
            try:
                error_body = error.read().decode("utf-8", errors="replace")
            except OSError:
                error_body = ""

            lower_body = error_body.lower()
            if error.code in {400, 404} and "model" in lower_body and "not found" in lower_body:
                last_note = (
                    f"Модель '{model}' не найдена в Ollama. Выполни: ollama pull {model}"
                )
                continue

            if error.code == 400 and error_body:
                last_note = (
                    f"Локальная LLM '{model}' отклонила запрос (HTTP 400), пробую резервную модель."
                )
                if index + 1 < len(model_candidates):
                    continue
                return None, last_note

            last_note = (
                f"Локальная LLM '{model}' недоступна (HTTP {error.code}), использован алгоритмический режим."
            )
            if index + 1 < len(model_candidates) and error.code in {400, 404, 429, 500, 502, 503, 504}:
                continue
            return None, last_note
        except TimeoutError:
            last_note = (
                f"Таймаут модели '{model}'. Для M1 используй более легкую модель (например, gemma3:1b)."
            )
            if index + 1 < len(model_candidates):
                continue
            return None, last_note
        except URLError:
            return None, "Нет подключения к локальной LLM, использован алгоритмический режим."
        except (json.JSONDecodeError, OSError, ValueError):
            last_note = (
                f"Некорректный ответ модели '{model}', пробую резервную модель."
            )
            if index + 1 < len(model_candidates):
                continue
            return None, last_note

    return None, last_note or "Локальная LLM недоступна, использован алгоритмический режим."


def collect_citation_terms(citations: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for citation in citations[: max(1, LOCAL_LLM_MAX_CITATIONS)]:
        fragment = str(citation.get("fragment") or "")
        terms.update(tokenize_terms(fragment))
    return terms


def required_grounding_overlap(answer_term_count: int) -> int:
    if answer_term_count <= 8:
        return 1
    if answer_term_count <= 20:
        return 2
    return 3


def normalized_term_set(text: str) -> set[str]:
    return {term for term in tokenize_terms(text) if len(term) >= 4}


def term_jaccard_similarity(text_a: str, text_b: str) -> float:
    terms_a = normalized_term_set(text_a)
    terms_b = normalized_term_set(text_b)
    if not terms_a and not terms_b:
        return 1.0
    if not terms_a or not terms_b:
        return 0.0
    return len(terms_a & terms_b) / max(1, len(terms_a | terms_b))


def is_too_similar_to_base_answer(base_answer: str, candidate_answer: str) -> bool:
    base_norm = str(base_answer or "").strip().lower().replace("ё", "е")
    cand_norm = str(candidate_answer or "").strip().lower().replace("ё", "е")
    if not base_norm or not cand_norm:
        return False
    if base_norm == cand_norm:
        return True
    return term_jaccard_similarity(base_norm, cand_norm) >= 0.9


def build_hybrid_rewrite_prompt(
    question: str,
    citations: list[dict[str, Any]],
    base_answer: str,
    first_answer: str,
) -> str:
    source_blocks = build_prompt_citation_blocks(citations)
    sources_text = "\n\n".join(source_blocks) if source_blocks else "(цитаты отсутствуют)"
    safe_question = str(question or "").strip()
    safe_base_answer = str(base_answer or "").strip()
    safe_first_answer = str(first_answer or "").strip()

    return (
        "Перепиши ответ еще раз в другом стиле, но по тем же цитатам.\n"
        "Нельзя выдумывать факты и нельзя выходить за пределы цитат.\n"
        "Нужно сделать формулировку заметно отличающейся от черновика.\n\n"
        f"Вопрос:\n{safe_question}\n\n"
        f"Черновик алгоритма:\n{safe_base_answer}\n\n"
        f"Первая версия LLM:\n{safe_first_answer}\n\n"
        f"Цитаты:\n{sources_text}\n"
    )


def build_grounding_fix_prompt(
    question: str,
    citations: list[dict[str, Any]],
    draft_answer: str,
) -> str:
    source_blocks = build_prompt_citation_blocks(citations)
    sources_text = "\n\n".join(source_blocks) if source_blocks else "(цитаты отсутствуют)"
    safe_question = str(question or "").strip()
    safe_draft_answer = str(draft_answer or "").strip()
    return (
        "Исправь ответ так, чтобы он строго опирался на цитаты ниже.\n"
        "Обязательно добавь 1 короткую прямую цитату из источника в кавычках «...».\n"
        "Нельзя добавлять новые факты, которых нет в цитатах.\n"
        "Если данных недостаточно, ответь строго: "
        "\"В загруженных книгах недостаточно данных для точного ответа.\".\n\n"
        f"Вопрос:\n{safe_question}\n\n"
        f"Черновой ответ:\n{safe_draft_answer}\n\n"
        f"Цитаты:\n{sources_text}\n"
    )


def build_specificity_fix_prompt(
    question: str,
    citations: list[dict[str, Any]],
    draft_answer: str,
) -> str:
    source_blocks = build_prompt_citation_blocks(citations)
    sources_text = "\n\n".join(source_blocks) if source_blocks else "(цитаты отсутствуют)"
    safe_question = str(question or "").strip()
    safe_draft_answer = str(draft_answer or "").strip()
    intent = detect_generic_intent(question)
    intent_hint = build_intent_specific_hybrid_instruction(intent)
    return (
        "Исправь ответ так, чтобы он был конкретным и проверяемым по цитатам.\n"
        "Нельзя использовать размытые формулировки: «что-то», «как-то», «в целом», "
        "«занимается чем-то», «делает что-то».\n"
        "Укажи факты и действия, которые действительно есть в цитатах.\n"
        "Добавь 1 короткую прямую цитату «...» из источника.\n"
        "Если данных недостаточно, ответь строго: "
        "\"В загруженных книгах недостаточно данных для точного ответа.\".\n\n"
        f"Интент: {intent}\n"
        f"Требования по интенту:\n{intent_hint}\n\n"
        f"Вопрос:\n{safe_question}\n\n"
        f"Текущий слишком общий ответ:\n{safe_draft_answer}\n\n"
        f"Цитаты:\n{sources_text}\n"
    )


def has_vague_wording(answer: str) -> bool:
    normalized = str(answer or "").lower().replace("ё", "е")
    if not normalized:
        return False
    return any(marker in normalized for marker in VAGUE_ANSWER_MARKERS)


def is_answer_too_generic(
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
    base_answer: str = "",
) -> bool:
    normalized = str(answer or "").strip().lower().replace("ё", "е")
    if not normalized:
        return True
    if is_insufficient_data_answer(answer):
        return False

    answer_terms = {term for term in tokenize_terms(answer) if len(term) >= 3}
    if len(answer_terms) < 4:
        return True

    citation_terms = collect_citation_terms(citations)
    overlap = len(answer_terms & citation_terms)
    overlap_ratio = overlap / max(1, len(answer_terms))
    quote_overlap = has_direct_quote_overlap(answer, citations)
    vague = has_vague_wording(answer)
    intent = detect_generic_intent(question)

    if overlap == 0 and not quote_overlap:
        return True
    if overlap_ratio < 0.12 and not quote_overlap:
        return True
    if vague and overlap_ratio < 0.26 and not quote_overlap:
        return True

    if intent in {"actions", "motivation", "character_description", "relationships"}:
        answer_sentences = extract_clean_sentences(answer)
        if len(answer_sentences) < 2 and not quote_overlap:
            return True
        focus_names = detect_main_characters_from_fragments(citations, top_n=2) if citations else []
        normalized_answer_text = normalized
        if focus_names:
            has_focus_name = any(
                normalize_name_token(name) in normalized_answer_text
                for name in focus_names
            )
            if not has_focus_name and not quote_overlap:
                return True

    if base_answer:
        base_similarity = term_jaccard_similarity(base_answer, answer)
        if base_similarity < 0.18 and overlap_ratio < 0.22 and not quote_overlap:
            return True

    return False


def build_answer_quality_metadata(
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_metadata = metadata or {}
    reasons: list[str] = []

    if not citations:
        return {
            "confidence": 0.08,
            "confidence_label": "низкая",
            "confidence_reasons": ["Нет цитат-оснований для проверки ответа."],
        }

    citation_count = len(citations)
    grounding_score = float(safe_metadata.get("grounding_score") or 0.0)
    grounding_status = str(safe_metadata.get("grounding_status") or "unknown")
    has_quote = has_direct_quote_overlap(answer, citations)
    generic = is_answer_too_generic(question, answer, citations)
    insufficient = is_insufficient_data_answer(answer)

    score = 0.12
    score += min(0.24, citation_count * 0.06)
    score += min(0.34, max(0.0, grounding_score) * 0.5)
    if has_quote:
        score += 0.14
    else:
        reasons.append("В ответе нет прямой короткой цитаты из источника.")

    if grounding_status == "weak":
        reasons.append("Слабое совпадение ответа с цитатами.")
        score -= 0.16

    if generic:
        reasons.append("Формулировка слишком общая относительно найденных цитат.")
        score -= 0.18

    if insufficient:
        reasons.append("По найденным фрагментам данных недостаточно для точного вывода.")
        score = min(score, 0.28)

    intent = str(safe_metadata.get("intent") or detect_generic_intent(question))
    answer_terms_count = len(tokenize_terms(answer))
    if intent in {"actions", "motivation", "character_description", "relationships"} and answer_terms_count < 10:
        reasons.append("Ответ слишком короткий для выбранного типа вопроса.")
        score -= 0.09

    if citation_count <= 1:
        reasons.append("Опора на малое число цитат.")
        score -= 0.08

    score = max(0.01, min(0.97, score))
    if score >= 0.75:
        label = "высокая"
    elif score >= 0.45:
        label = "средняя"
    else:
        label = "низкая"

    return {
        "confidence": round(score, 3),
        "confidence_label": label,
        "confidence_reasons": reasons[:4],
    }


def has_direct_quote_overlap(answer: str, citations: list[dict[str, Any]]) -> bool:
    quoted_parts = re.findall(r"[«\"]([^«»\"]{8,220})[»\"]", str(answer or ""))
    if not quoted_parts:
        return False

    source_text = " ".join(str(item.get("fragment") or "") for item in citations)
    normalized_source = re.sub(r"\s+", " ", source_text.lower().replace("ё", "е")).strip()
    if not normalized_source:
        return False

    for part in quoted_parts:
        cleaned = re.sub(r"\s+", " ", part.lower().replace("ё", "е")).strip(" .,:;!?-")
        if len(cleaned) < 8:
            continue
        if cleaned in normalized_source:
            return True
    return False


def is_answer_grounded_by_citations(answer: str, citations: list[dict[str, Any]]) -> bool:
    normalized = str(answer or "").strip().lower().replace("ё", "е")
    if not normalized:
        return False
    if "недостаточно данных" in normalized:
        return True
    if has_direct_quote_overlap(answer, citations):
        return True

    answer_terms = [term for term in tokenize_terms(answer) if len(term) >= 4]
    if not answer_terms:
        return False

    citation_terms = collect_citation_terms(citations)
    if not citation_terms:
        return False

    overlap = len(set(answer_terms) & citation_terms)
    required = required_grounding_overlap(len(set(answer_terms)))
    return overlap >= required


def extract_evidence_sentence(
    fragment_text: str,
    answer_terms: set[str],
    question_terms: set[str],
) -> tuple[str, float]:
    sentences = extract_clean_sentences(fragment_text)
    if not sentences:
        fallback = normalize_sentence_text(str(fragment_text or "").replace("\n", " "))
        if not fallback:
            return "", 0.0
        fallback_terms = set(tokenize_terms(fallback))
        overlap = len((answer_terms | question_terms) & fallback_terms) / max(
            1,
            len(answer_terms | question_terms),
        )
        return fallback[:320], round(overlap, 4)

    best_sentence = ""
    best_score = -1.0
    target_terms = answer_terms | question_terms
    for sentence in sentences:
        sentence_terms = set(tokenize_terms(sentence))
        overlap = len(target_terms & sentence_terms) / max(1, len(target_terms))
        quote_bonus = 0.1 if re.search(r"[«\"].{6,160}[»\"]", sentence) else 0.0
        score = overlap + quote_bonus
        if score > best_score:
            best_score = score
            best_sentence = sentence

    return best_sentence[:320], round(max(0.0, best_score), 4)


def enrich_citations_with_grounding(
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not citations:
        return [], {
            "grounding_status": "no_citations",
            "grounding_score": 0.0,
            "grounding_warning": "Цитаты для проверки grounding отсутствуют.",
        }

    question_terms = {term for term in tokenize_terms(question) if len(term) >= 3}
    answer_terms = {term for term in tokenize_terms(answer) if len(term) >= 3}
    grounded: list[dict[str, Any]] = []
    evidence_scores: list[float] = []

    for item in citations:
        enriched = copy.deepcopy(item)
        fragment_text = str(enriched.get("fragment") or "")
        evidence_text, evidence_score = extract_evidence_sentence(
            fragment_text,
            answer_terms,
            question_terms,
        )
        if evidence_text:
            enriched["evidence_text"] = evidence_text
            enriched["evidence_score"] = evidence_score
            evidence_scores.append(evidence_score)

        grounded.append(enriched)

    avg_score = round(sum(evidence_scores) / max(1, len(evidence_scores)), 4)
    warning = None
    normalized_answer = str(answer or "").lower().replace("ё", "е")
    if not has_direct_quote_overlap(answer, grounded) and any(
        marker in normalized_answer for marker in ("никогда", "всегда", "единственн", "точно", "безусловно")
    ):
        warning = "Ответ содержит сильные обобщения без прямой цитаты; проверьте формулировку."

    status = "ok"
    if avg_score < 0.12:
        status = "weak"
        if not warning:
            warning = "Низкое совпадение ответа с цитатами-основаниями."

    return grounded, {
        "grounding_status": status,
        "grounding_score": avg_score,
        "grounding_warning": warning,
    }


def is_insufficient_data_answer(text: str) -> bool:
    normalized = str(text or "").strip().lower().replace("ё", "е")
    return "недостаточно данных" in normalized


def build_base_rewrite_prompt(
    question: str,
    base_answer: str,
    citations: list[dict[str, Any]] | None = None,
) -> str:
    safe_question = str(question or "").strip()
    safe_base_answer = str(base_answer or "").strip()
    source_blocks = build_prompt_citation_blocks(citations or [])
    sources_text = "\n\n".join(source_blocks) if source_blocks else ""
    quote_requirement = (
        "Добавь 1 короткую прямую цитату «...» из источников.\n"
        if sources_text
        else ""
    )
    sources_block = f"\n\nЦитаты:\n{sources_text}\n" if sources_text else ""
    return (
        "Перефразируй ответ естественным русским языком.\n"
        "Нельзя добавлять новые факты, числа, имена или события.\n"
        "Избегай размытых формулировок («что-то», «в целом», «как-то»).\n"
        f"{quote_requirement}"
        "Сохрани смысл исходного ответа.\n\n"
        f"Вопрос:\n{safe_question}\n\n"
        f"Исходный ответ:\n{safe_base_answer}\n"
        f"{sources_block}"
    )


def rewrite_base_answer_with_llm(
    question: str,
    base_answer: str,
    citations: list[dict[str, Any]] | None = None,
    requested_model: str | None = None,
) -> tuple[str | None, str | None]:
    if not str(base_answer or "").strip():
        return None, None
    citations = citations or []
    prompt = build_base_rewrite_prompt(question, base_answer, citations)
    rewritten_answer, note = request_local_llm(
        prompt,
        requested_model=requested_model,
        temperature=0.35,
        num_predict=220,
    )
    if not rewritten_answer:
        return None, note
    if is_too_similar_to_base_answer(base_answer, rewritten_answer):
        return None, "LLM-этап не дал заметного улучшения формулировки."
    if citations and not is_answer_grounded_by_citations(rewritten_answer, citations):
        return None, "LLM-рерайт не прошел проверку по цитатам."
    if citations and is_answer_too_generic(question, rewritten_answer, citations, base_answer):
        return None, "LLM-рерайт получился слишком общим."
    return rewritten_answer, "LLM-этап применен (рерайт алгоритмического ответа)."


def generate_local_llm_answer(
    question: str,
    citations: list[dict[str, Any]],
    requested_model: str | None = None,
) -> tuple[str | None, str | None]:
    if not citations:
        return None, "Нет цитат для локальной LLM, использован алгоритмический режим."
    prompt = build_local_llm_prompt(question, citations)
    return request_local_llm(
        prompt,
        requested_model=requested_model,
        temperature=0.2,
        num_predict=256,
    )


def generate_hybrid_llm_answer(
    question: str,
    citations: list[dict[str, Any]],
    base_answer: str,
    requested_model: str | None = None,
) -> tuple[str | None, str | None]:
    if not citations:
        return None, "Нет цитат для гибридного режима, использован алгоритмический ответ."

    prompt = build_hybrid_llm_prompt(question, citations, base_answer)
    llm_answer, note = request_local_llm(
        prompt,
        requested_model=requested_model,
        temperature=0.3,
        num_predict=280,
    )
    if not llm_answer:
        rewritten, rewrite_note = rewrite_base_answer_with_llm(
            question,
            base_answer,
            citations,
            requested_model=requested_model,
        )
        if rewritten:
            return rewritten, rewrite_note
        return None, note or rewrite_note

    if is_insufficient_data_answer(llm_answer) and not is_insufficient_data_answer(base_answer):
        rewritten, rewrite_note = rewrite_base_answer_with_llm(
            question,
            base_answer,
            citations,
            requested_model=requested_model,
        )
        if rewritten:
            return rewritten, rewrite_note
        return None, "LLM вернула слишком общий отказ, использован алгоритмический ответ."

    if is_too_similar_to_base_answer(base_answer, llm_answer):
        rewrite_prompt = build_hybrid_rewrite_prompt(
            question,
            citations,
            base_answer,
            llm_answer,
        )
        rewritten_answer, rewritten_note = request_local_llm(
            rewrite_prompt,
            requested_model=requested_model,
            temperature=0.45,
            num_predict=280,
        )
        if rewritten_answer:
            llm_answer = rewritten_answer
            if rewritten_note:
                note = rewritten_note

    if is_answer_too_generic(question, llm_answer, citations, base_answer):
        specificity_prompt = build_specificity_fix_prompt(
            question,
            citations,
            llm_answer,
        )
        specific_answer, specific_note = request_local_llm(
            specificity_prompt,
            requested_model=requested_model,
            temperature=0.2,
            num_predict=280,
        )
        if specific_answer and not is_answer_too_generic(question, specific_answer, citations, base_answer):
            llm_answer = specific_answer
            if specific_note:
                note = specific_note
        else:
            rewritten, rewrite_note = rewrite_base_answer_with_llm(
                question,
                base_answer,
                citations,
                requested_model=requested_model,
            )
            if rewritten:
                return rewritten, rewrite_note
            return None, "Ответ LLM получился слишком общим, использован алгоритмический режим."

    if not is_answer_grounded_by_citations(llm_answer, citations):
        grounding_prompt = build_grounding_fix_prompt(
            question,
            citations,
            llm_answer,
        )
        grounded_answer, grounded_note = request_local_llm(
            grounding_prompt,
            requested_model=requested_model,
            temperature=0.2,
            num_predict=260,
        )
        if grounded_answer and is_answer_grounded_by_citations(grounded_answer, citations):
            llm_answer = grounded_answer
            if grounded_note:
                note = grounded_note
        else:
            rewritten, rewrite_note = rewrite_base_answer_with_llm(
                question,
                base_answer,
                citations,
                requested_model=requested_model,
            )
            if rewritten:
                return rewritten, rewrite_note
            return None, "Гибридный ответ LLM не прошел проверку по цитатам, использован алгоритмический режим."

    if is_answer_too_generic(question, llm_answer, citations, base_answer):
        rewritten, rewrite_note = rewrite_base_answer_with_llm(
            question,
            base_answer,
            citations,
            requested_model=requested_model,
        )
        if rewritten:
            return rewritten, rewrite_note
        return None, "Итоговый ответ LLM остался слишком общим, использован алгоритмический режим."

    success_note = "LLM-этап применен."
    if is_too_similar_to_base_answer(base_answer, llm_answer):
        success_note = "LLM-этап применен, но итог близок к алгоритмическому ответу."
    if note:
        success_note = f"{success_note} {note}"

    return llm_answer, success_note


def apply_intent_answer_template(question: str, intent: str, answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return text

    normalized = text.lower().replace("ё", "е")
    if "недостаточно данных" in normalized or "не найден" in normalized:
        return text

    normalized_intent = str(intent or "").strip().lower()
    chapter_number = extract_requested_chapter(question)

    template_prefixes = {
        "plot": "Краткий сюжет:",
        "events": "Ключевые события:",
        "actions": "Действия героя:",
        "motivation": "Мотивация героя:",
        "relationships": "Связи персонажей:",
        "character_description": "Описание героя:",
        "protagonist": "Главный герой:",
        "theme": "Тема книги:",
        "arc": "Линия героя:",
        "beginning": "Начало книги:",
        "middle": "Середина книги:",
        "finale": "Финал книги:",
    }
    if normalized_intent == "chapter":
        prefix = (
            f"По главе {chapter_number}:"
            if chapter_number is not None
            else "По выбранной главе:"
        )
    else:
        prefix = template_prefixes.get(normalized_intent, "")

    if not prefix:
        return text

    normalized_prefix = prefix.lower().replace("ё", "е").rstrip(":")
    if normalized.startswith(normalized_prefix):
        return text
    return f"{prefix} {text}"


def apply_answer_mode(
    question: str,
    citations: list[dict[str, Any]],
    base_answer: str,
    answer_mode: str | None,
    local_model: str | None = None,
) -> tuple[str, str, str | None]:
    _ = answer_mode
    mode = "hybrid"

    llm_answer, note = generate_hybrid_llm_answer(
        question,
        citations,
        base_answer,
        requested_model=local_model,
    )
    if llm_answer:
        return llm_answer, "hybrid", note

    return base_answer, "hybrid", note


def normalize_compression_level(raw_level: str | None) -> str:
    level = str(raw_level or "").strip().lower()
    if level in {"high", "medium", "low"}:
        return level
    return "medium"


def normalize_quiz_difficulty(raw_difficulty: str | None) -> str:
    difficulty = str(raw_difficulty or "").strip().lower()
    if difficulty in {"easy", "medium", "hard"}:
        return difficulty
    return "medium"


def trim_to_word_limit(text: str, word_limit: int) -> str:
    if not text:
        return ""
    words = text.split()
    if len(words) <= word_limit:
        return text.strip()
    return f"{' '.join(words[:word_limit]).strip()}..."


def build_summary_question(preferences: str | None = None) -> str:
    base = (
        "Кратко перескажи общий сюжет книги и ключевые события, "
        "сохраняя фактическую точность."
    )
    extra = str(preferences or "").strip()
    if not extra:
        return base
    return f"{base} Учти пожелания: {extra}"


def extract_quiz_sentence_rows(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_sentences: set[str] = set()

    for fragment in fragments:
        location = fragment.get("location") or {}
        for sentence in extract_clean_sentences(fragment.get("fragment", "")):
            terms = tokenize_terms(sentence)
            if len(terms) < 6 or len(terms) > 42:
                continue
            if is_dialogue_heavy_sentence(sentence):
                continue

            fingerprint = sentence.lower().replace("ё", "е")
            if fingerprint in seen_sentences:
                continue
            seen_sentences.add(fingerprint)

            rows.append(
                {
                    "sentence": sentence,
                    "terms": terms,
                    "fragment": fragment,
                    "chapter": location.get("chapter"),
                    "line_start": location.get("line_start", 10**9),
                }
            )

    rows.sort(
        key=lambda item: (
            item.get("chapter") if item.get("chapter") is not None else 10**9,
            item.get("line_start", 10**9),
        )
    )
    return rows


def pick_mask_terms(terms: list[str], count: int) -> list[str]:
    unique_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        clean = term.strip().lower().replace("ё", "е")
        if not clean or clean in seen:
            continue
        if clean in RUS_STOPWORDS or clean.isdigit() or len(clean) < 4:
            continue
        seen.add(clean)
        unique_terms.append(clean)

    ranked = sorted(unique_terms, key=lambda value: (len(value), value), reverse=True)
    return ranked[: max(1, count)]


def mask_sentence_by_terms(sentence: str, mask_terms: list[str]) -> tuple[str, list[str]]:
    masked_sentence = sentence
    answers: list[str] = []

    for term in mask_terms:
        pattern = rf"(?<![A-Za-zА-Яа-яЁё0-9]){re.escape(term)}(?![A-Za-zА-Яа-яЁё0-9])"
        captured: list[str] = []

        def replacer(match: re.Match[str]) -> str:
            if captured:
                return match.group(0)
            captured.append(match.group(0))
            return "_____"

        masked_sentence = re.sub(
            pattern,
            replacer,
            masked_sentence,
            count=1,
            flags=re.IGNORECASE,
        )
        if captured:
            answers.append(captured[0])

    return masked_sentence, answers


def build_quiz_items_from_fragments(
    fragments: list[dict[str, Any]],
    question_count: int,
    difficulty: str,
) -> list[dict[str, Any]]:
    rows = extract_quiz_sentence_rows(fragments)
    if not rows:
        return []

    mask_count = QUIZ_DIFFICULTY_MASKS.get(difficulty, 2)
    items: list[dict[str, Any]] = []

    for row in rows:
        sentence = row.get("sentence", "")
        terms = row.get("terms", [])
        fragment = row.get("fragment") or {}
        mask_terms = pick_mask_terms(terms, mask_count)
        masked_sentence, answers = mask_sentence_by_terms(sentence, mask_terms)

        if answers:
            question = (
                f"Заполните пропуск: {masked_sentence}"
                if len(answers) == 1
                else f"Заполните пропуски: {masked_sentence}"
            )
            answer = ", ".join(answers)
        else:
            preview = sentence if len(sentence) <= 170 else f"{sentence[:167]}..."
            question = f"О чем говорится в фрагменте: «{preview}»?"
            answer = preview

        items.append(
            {
                "question": question,
                "answer": answer,
                "citation": fragment,
            }
        )
        if len(items) >= question_count:
            break

    return items


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
    invalidate_result_caches()

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

    source_sig = sources_signature(sources)
    cache_key = build_search_cache_key(
        "case",
        request.query,
        request.top_k,
        source_sig,
        strict_phrase=request.strict_phrase,
        whole_words=request.whole_words,
        chapter_number=request.chapter_number,
    )
    cached_response = cache_get(SEARCH_RESULT_CACHE, cache_key, SEARCH_CACHE_TTL_SEC)
    if isinstance(cached_response, dict):
        return cached_response

    fragments, message = search_fragments_in_sources(
        request.query,
        sources,
        request.top_k,
        strict_phrase=request.strict_phrase,
        whole_words=request.whole_words,
        chapter_number=request.chapter_number,
    )
    if not fragments:
        response = {
            "found": False,
            "message": message,
            "fragments": [],
        }
        cache_set(SEARCH_RESULT_CACHE, cache_key, response)
        return response

    response = {"found": True, "fragments": fragments}
    cache_set(SEARCH_RESULT_CACHE, cache_key, response)
    return response


@app.post("/api/case/ask")
async def ask_case_question(request: CaseAskRequest):
    sources = build_case_sources()
    if not sources:
        return {
            "found": False,
            "answer": "Сначала загрузите хотя бы одну книгу в формате .txt",
            "citations": [],
        }

    source_sig = sources_signature(sources)
    cache_key = build_ask_cache_key(
        "case",
        request.question,
        request.top_k,
        request.citations_k,
        request.answer_mode,
        request.local_model,
        source_sig,
    )
    cached_response = cache_get(ASK_RESULT_CACHE, cache_key, ASK_CACHE_TTL_SEC)
    if isinstance(cached_response, dict):
        return cached_response

    found, answer, citations = answer_question_in_sources(
        request.question,
        sources,
        request.top_k,
        request.citations_k,
    )
    effective_mode = normalize_answer_mode(request.answer_mode)
    metadata = (
        build_ask_metadata(request.question, citations, sources)
        if found
        else {"intent": detect_generic_intent(request.question), "main_characters": []}
    )
    if found:
        answer, effective_mode, mode_note = apply_answer_mode(
            request.question,
            citations,
            answer,
            request.answer_mode,
            request.local_model,
        )
        answer = apply_intent_answer_template(
            request.question,
            str(metadata.get("intent") or ""),
            answer,
        )
        if mode_note:
            metadata["answer_mode_note"] = mode_note
        metadata, card_note = enhance_character_card_with_llm(
            request.question,
            citations,
            metadata,
            request.local_model,
        )
        if card_note:
            previous = str(metadata.get("answer_mode_note") or "").strip()
            metadata["answer_mode_note"] = (
                f"{previous} {card_note}".strip() if previous else card_note
            )
        citations, grounding_meta = enrich_citations_with_grounding(
            request.question,
            answer,
            citations,
        )
        metadata.update(grounding_meta)
        metadata.update(
            build_answer_quality_metadata(
                request.question,
                answer,
                citations,
                metadata,
            )
        )
    metadata["answer_mode"] = effective_mode
    response = {
        "found": found,
        "answer": answer,
        "citations": citations,
        **metadata,
    }
    cache_set(ASK_RESULT_CACHE, cache_key, response)
    return response


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
    source_sig = sources_signature(sources)
    scope = f"user:{current_user.id}"
    cache_key = build_search_cache_key(
        scope,
        request.query,
        request.top_k,
        source_sig,
        strict_phrase=request.strict_phrase,
        whole_words=request.whole_words,
        chapter_number=request.chapter_number,
    )
    cached_response = cache_get(SEARCH_RESULT_CACHE, cache_key, SEARCH_CACHE_TTL_SEC)
    if isinstance(cached_response, dict):
        return cached_response

    fragments, message = search_fragments_in_sources(
        request.query,
        sources,
        request.top_k,
        strict_phrase=request.strict_phrase,
        whole_words=request.whole_words,
        chapter_number=request.chapter_number,
    )
    if not fragments:
        response = {
            "found": False,
            "message": message,
            "fragments": [],
        }
        cache_set(SEARCH_RESULT_CACHE, cache_key, response)
        return response

    response = {"found": True, "fragments": fragments}
    cache_set(SEARCH_RESULT_CACHE, cache_key, response)
    return response


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
    source_sig = sources_signature(sources)
    scope = f"user:{current_user.id}"
    cache_key = build_ask_cache_key(
        scope,
        request.question,
        request.top_k,
        request.citations_k,
        request.answer_mode,
        request.local_model,
        source_sig,
    )
    cached_response = cache_get(ASK_RESULT_CACHE, cache_key, ASK_CACHE_TTL_SEC)
    if isinstance(cached_response, dict):
        return cached_response

    found, answer, citations = answer_question_in_sources(
        request.question,
        sources,
        request.top_k,
        request.citations_k,
    )
    effective_mode = normalize_answer_mode(request.answer_mode)
    metadata = (
        build_ask_metadata(request.question, citations, sources)
        if found
        else {"intent": detect_generic_intent(request.question), "main_characters": []}
    )
    if found:
        answer, effective_mode, mode_note = apply_answer_mode(
            request.question,
            citations,
            answer,
            request.answer_mode,
            request.local_model,
        )
        answer = apply_intent_answer_template(
            request.question,
            str(metadata.get("intent") or ""),
            answer,
        )
        if mode_note:
            metadata["answer_mode_note"] = mode_note
        metadata, card_note = enhance_character_card_with_llm(
            request.question,
            citations,
            metadata,
            request.local_model,
        )
        if card_note:
            previous = str(metadata.get("answer_mode_note") or "").strip()
            metadata["answer_mode_note"] = (
                f"{previous} {card_note}".strip() if previous else card_note
            )
        citations, grounding_meta = enrich_citations_with_grounding(
            request.question,
            answer,
            citations,
        )
        metadata.update(grounding_meta)
        metadata.update(
            build_answer_quality_metadata(
                request.question,
                answer,
                citations,
                metadata,
            )
        )
    metadata["answer_mode"] = effective_mode
    response = {
        "found": found,
        "answer": answer,
        "citations": citations,
        **metadata,
    }
    cache_set(ASK_RESULT_CACHE, cache_key, response)
    return response


@app.post("/api/books/summary")
async def summarize_user_books(
    request: UserSummaryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    books = resolve_user_books(db, current_user, request.book_ids)
    if not books:
        return {
            "found": False,
            "summary": "Не найдено загруженных книг для составления конспекта.",
            "citations": [],
        }

    sources = build_user_sources(books)
    compression_level = normalize_compression_level(request.compression_level)
    word_limit = SUMMARY_WORD_LIMITS.get(compression_level, SUMMARY_WORD_LIMITS["medium"])

    summary_question = build_summary_question(request.preferences)
    summary_text, citations = build_generic_answer_for_sources(
        summary_question,
        sources,
        request.top_k,
        request.citations_k,
    )
    if not summary_text:
        return {
            "found": False,
            "summary": "Не удалось собрать краткий конспект по загруженным книгам.",
            "citations": [],
            "compression_level": compression_level,
            "answer_mode": "hybrid",
        }

    base_summary = trim_to_word_limit(summary_text, word_limit)
    final_summary, effective_mode, mode_note = apply_answer_mode(
        summary_question,
        citations,
        base_summary,
        request.answer_mode,
        request.local_model,
    )
    final_summary = trim_to_word_limit(final_summary, word_limit)

    response = {
        "found": True,
        "summary": final_summary,
        "citations": citations,
        "compression_level": compression_level,
        "answer_mode": effective_mode,
    }
    if mode_note:
        response["answer_mode_note"] = mode_note
    return response


@app.post("/api/books/quiz")
async def generate_user_quiz(
    request: UserQuizRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    books = resolve_user_books(db, current_user, request.book_ids)
    if not books:
        return {
            "found": False,
            "message": "Не найдено загруженных книг для викторины.",
            "questions": [],
        }

    sources = build_user_sources(books)
    quiz_query_parts = [
        "ключевые события герои важные факты",
        str(request.preferences or "").strip(),
    ]
    quiz_query = " ".join(part for part in quiz_query_parts if part).strip()

    top_k = max(request.top_k, request.question_count * 3)
    fragments, message = search_fragments_in_sources(quiz_query, sources, top_k)
    if not fragments:
        fragments = build_overview_fragments_for_sources(
            sources,
            top_k,
            chapter_number=None,
            prefer_end=False,
            intent="plot",
        )

    if not fragments:
        return {
            "found": False,
            "message": message or "Не удалось подобрать фрагменты для викторины.",
            "questions": [],
        }

    difficulty = normalize_quiz_difficulty(request.difficulty)
    questions = build_quiz_items_from_fragments(
        fragments,
        request.question_count,
        difficulty,
    )
    if not questions:
        return {
            "found": False,
            "message": "Не удалось сформировать вопросы по выбранной книге.",
            "questions": [],
        }

    return {
        "found": True,
        "difficulty": difficulty,
        "questions": questions,
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


# Legacy-эндпоинты оставлены только как явный отказ, чтобы не было скрытых внешних API вызовов.
@app.post("/upload-pdf/")
async def upload_pdf_legacy():
    raise HTTPException(
        status_code=410,
        detail="Legacy endpoint removed. Use /upload and /api/books/*.",
    )


@app.get("/get-response/{id_class}")
async def get_response_legacy(id_class: str):
    raise HTTPException(
        status_code=410,
        detail="Legacy endpoint removed. Use /api/books/ask.",
    )


@app.get("/get-image")
async def get_image_legacy(topic: str):
    raise HTTPException(
        status_code=410,
        detail="Image generation is disabled: no external API mode.",
    )


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
        invalidate_result_caches()

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
        USER_BOOK_CHUNK_CACHE.pop(str(book_id), None)
        invalidate_result_caches()

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
