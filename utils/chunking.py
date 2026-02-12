"""Helpers for Telegram-safe message chunking."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


MAX_TELEGRAM_MESSAGE = 3500


def chunk_text(text: str, limit: int = MAX_TELEGRAM_MESSAGE) -> List[str]:
    """Split text into Telegram-safe chunks on line boundaries when possible."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            # hard split very large line
            if current:
                chunks.append("".join(current).rstrip())
                current = []
                current_len = 0
            for idx in range(0, len(line), limit):
                chunks.append(line[idx : idx + limit].rstrip())
            continue

        if current_len + len(line) > limit:
            chunks.append("".join(current).rstrip())
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)

    if current:
        chunks.append("".join(current).rstrip())

    return chunks


def write_report_file(contents: str, base_name: str = "jobs_report") -> Path:
    """Write a text report file for sending as Telegram document."""
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in base_name).strip("_")
    safe = safe or "jobs_report"
    path = Path(f"{safe}.txt")
    path.write_text(contents, encoding="utf-8")
    return path


def iter_chunks(texts: Iterable[str], limit: int = MAX_TELEGRAM_MESSAGE) -> Iterable[str]:
    """Chunk an iterable of text blocks preserving order."""
    for text in texts:
        yield from chunk_text(text, limit=limit)
