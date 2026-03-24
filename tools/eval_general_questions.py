#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import requests

TOKEN_REGEX = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
THEME_MARKERS = (
    "вера",
    "бог",
    "душ",
    "совест",
    "смир",
    "молит",
    "грех",
    "добро",
    "зло",
    "милосерд",
)

RELATION_MARKERS = (
    "отнош",
    "между",
    "друж",
    "люб",
    "конфликт",
    "вражд",
)


@dataclass
class EvalQuestion:
    text: str
    qtype: str
    expected_chapter: int | None = None


DEFAULT_QUESTIONS = [
    EvalQuestion("какой общий сюжет книги", "plot"),
    EvalQuestion("какой сюжет по итогу", "finale"),
    EvalQuestion("что делает главный герой", "actions"),
    EvalQuestion("зачем герой это делает", "motivation"),
    EvalQuestion("что происходит в начале книги", "beginning"),
    EvalQuestion("что происходит в середине книги", "middle"),
    EvalQuestion("чем заканчивается книга", "finale"),
    EvalQuestion("какие ключевые события в книге", "events"),
    EvalQuestion("какие отношения между персонажами", "relationships"),
    EvalQuestion("какая основная тема книги", "theme"),
    EvalQuestion("что герой делал во второй главе", "chapter", expected_chapter=2),
    EvalQuestion("что происходит в тринадцатой главе", "chapter", expected_chapter=13),
]


def tokenize(text: str) -> list[str]:
    return [token.lower().replace("ё", "е") for token in TOKEN_REGEX.findall(text or "")]


def lexical_overlap(a: str, b: str) -> float:
    tokens_a = set(tokenize(a))
    tokens_b = set(tokenize(b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(1, len(tokens_a))


def upload_book(base_url: str, token: str, file_path: Path) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    with file_path.open("rb") as file:
        response = requests.post(
            f"{base_url.rstrip('/')}/upload",
            headers=headers,
            files={"file": (file_path.name, file, "text/plain")},
            timeout=120,
        )
    response.raise_for_status()
    payload = response.json()
    if "id" not in payload:
        raise RuntimeError(f"Unexpected upload response: {payload}")
    return int(payload["id"])


def ask_question(
    base_url: str,
    token: str,
    book_id: int,
    question: str,
    top_k: int,
    citations_k: int,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "question": question,
        "book_ids": [book_id],
        "top_k": top_k,
        "citations_k": citations_k,
    }
    response = requests.post(
        f"{base_url.rstrip('/')}/api/books/ask",
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def evaluate_question(result: dict[str, Any], question: EvalQuestion) -> dict[str, Any]:
    answer = (result.get("answer") or "").strip()
    citations = result.get("citations") or []
    grounding_scores = [
        lexical_overlap(answer, citation.get("fragment", "") or citation.get("text", ""))
        for citation in citations
    ]
    grounding = max(grounding_scores) if grounding_scores else 0.0

    citation_chapters = [
        (citation.get("location") or {}).get("chapter")
        for citation in citations
        if isinstance(citation, dict)
    ]

    chapter_hit = None
    if question.expected_chapter is not None:
        chapter_hit = question.expected_chapter in citation_chapters

    answer_lower = answer.lower().replace("ё", "е")
    theme_signal = any(marker in answer_lower for marker in THEME_MARKERS)
    relation_signal = any(marker in answer_lower for marker in RELATION_MARKERS)

    heuristic_ok = True
    if question.qtype == "theme":
        heuristic_ok = theme_signal
    elif question.qtype == "relationships":
        heuristic_ok = relation_signal
    elif question.qtype == "chapter" and chapter_hit is not None:
        heuristic_ok = chapter_hit

    return {
        "question": question.text,
        "type": question.qtype,
        "found": bool(result.get("found")),
        "answer": answer,
        "citations_count": len(citations),
        "citation_chapters": citation_chapters,
        "grounding": round(grounding, 4),
        "chapter_hit": chapter_hit,
        "heuristic_ok": heuristic_ok,
    }


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    found_rate = mean(1.0 if row["found"] else 0.0 for row in rows) if rows else 0.0
    citation_rate = mean(row["citations_count"] for row in rows) if rows else 0.0
    grounding_avg = mean(row["grounding"] for row in rows) if rows else 0.0
    heuristic_rate = mean(1.0 if row["heuristic_ok"] else 0.0 for row in rows) if rows else 0.0

    chapter_rows = [row for row in rows if row["chapter_hit"] is not None]
    chapter_accuracy = (
        mean(1.0 if row["chapter_hit"] else 0.0 for row in chapter_rows)
        if chapter_rows
        else None
    )

    return {
        "found_rate": round(found_rate, 4),
        "avg_citations": round(citation_rate, 4),
        "avg_grounding": round(grounding_avg, 4),
        "heuristic_ok_rate": round(heuristic_rate, 4),
        "chapter_accuracy": round(chapter_accuracy, 4) if chapter_accuracy is not None else None,
    }


def print_report(book_id: int, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    print(f"Book ID: {book_id}")
    print("---- Questions ----")
    for row in rows:
        answer_preview = " ".join(row["answer"].split())[:140]
        print(
            f"- {row['question']}\n"
            f"  found={row['found']} citations={row['citations_count']} grounding={row['grounding']} "
            f"chapter_hit={row['chapter_hit']} heuristic_ok={row['heuristic_ok']}\n"
            f"  answer: {answer_preview}"
        )
    print("---- Summary ----")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate generic QA quality for BookVerse.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--token", default=os.getenv("BOOKVERSE_TOKEN", "auth-disabled"))
    parser.add_argument("--book-id", type=int, default=None)
    parser.add_argument("--book-file", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--citations-k", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path")
    args = parser.parse_args()

    if args.book_id is None and args.book_file is None:
        raise SystemExit("Set --book-id or --book-file")

    book_id = args.book_id
    if book_id is None and args.book_file is not None:
        book_id = upload_book(args.base_url, args.token, args.book_file)

    assert book_id is not None
    rows: list[dict[str, Any]] = []
    for question in DEFAULT_QUESTIONS:
        result = ask_question(
            args.base_url,
            args.token,
            book_id,
            question.text,
            args.top_k,
            args.citations_k,
        )
        rows.append(evaluate_question(result, question))

    summary = build_summary(rows)
    report = {
        "book_id": book_id,
        "summary": summary,
        "rows": rows,
    }
    print_report(book_id, rows, summary)

    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved report to {args.output}")


if __name__ == "__main__":
    main()
