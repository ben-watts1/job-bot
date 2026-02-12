"""SQLite persistence layer."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


class Database:
    def __init__(self, path: str = "./db.sqlite3") -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    normalized_name TEXT NOT NULL UNIQUE,
                    careers_url TEXT NOT NULL,
                    ashby_org_slug TEXT NULL,
                    tags TEXT NULL,
                    notes TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_checked_at TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS job_items (
                    id INTEGER PRIMARY KEY,
                    company_id INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    title TEXT,
                    location TEXT,
                    team TEXT,
                    url TEXT,
                    posted_at TEXT NULL,
                    category TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(company_id, job_id),
                    FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

    def add_company(self, name: str, careers_url: str, ashby_org_slug: str | None = None) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO companies(name, normalized_name, careers_url, ashby_org_slug, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                  name=excluded.name,
                  careers_url=excluded.careers_url,
                  ashby_org_slug=excluded.ashby_org_slug,
                  updated_at=excluded.updated_at
                """,
                (name.strip(), normalize_name(name), careers_url.strip(), ashby_org_slug, now, now),
            )

    def remove_company(self, name: str) -> int:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM companies WHERE normalized_name = ?", (normalize_name(name),))
            return cur.rowcount

    def list_companies(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM companies ORDER BY name ASC")
            return cur.fetchall()

    def get_company_by_name(self, name: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM companies WHERE normalized_name = ?", (normalize_name(name),))
            return cur.fetchone()

    def get_company_by_id(self, company_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
            return cur.fetchone()

    def set_last_checked(self, company_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE companies SET last_checked_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), company_id))

    def get_state(self, key: str) -> str | None:
        with self.connect() as conn:
            cur = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO bot_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def upsert_jobs(self, company_id: int, jobs: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Upsert jobs and return (new_or_reactivated, active_seen)."""
        now = utc_now()
        seen_ids: set[str] = set()
        alerted: list[dict[str, Any]] = []
        active_payload: list[dict[str, Any]] = []

        with self.connect() as conn:
            for job in jobs:
                seen_ids.add(job["job_id"])
                active_payload.append(job)
                cur = conn.execute(
                    "SELECT id, is_active FROM job_items WHERE company_id = ? AND job_id = ?",
                    (company_id, job["job_id"]),
                )
                existing = cur.fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO job_items(
                          company_id, job_id, title, location, team, url, posted_at, category,
                          first_seen_at, last_seen_at, is_active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            company_id,
                            job["job_id"],
                            job.get("title"),
                            job.get("location"),
                            job.get("team"),
                            job.get("url"),
                            job.get("posted_at"),
                            job.get("category"),
                            now,
                            now,
                        ),
                    )
                    alerted.append(job)
                else:
                    was_inactive = int(existing["is_active"]) == 0
                    conn.execute(
                        """
                        UPDATE job_items
                        SET title=?, location=?, team=?, url=?, posted_at=?, category=?, last_seen_at=?, is_active=1
                        WHERE company_id=? AND job_id=?
                        """,
                        (
                            job.get("title"),
                            job.get("location"),
                            job.get("team"),
                            job.get("url"),
                            job.get("posted_at"),
                            job.get("category"),
                            now,
                            company_id,
                            job["job_id"],
                        ),
                    )
                    if was_inactive:
                        alerted.append(job)

            if seen_ids:
                placeholders = ",".join(["?"] * len(seen_ids))
                conn.execute(
                    f"UPDATE job_items SET is_active=0 WHERE company_id = ? AND job_id NOT IN ({placeholders})",
                    (company_id, *seen_ids),
                )
            else:
                conn.execute("UPDATE job_items SET is_active=0 WHERE company_id = ?", (company_id,))

        self.set_last_checked(company_id)
        return alerted, active_payload

    def query_jobs(self, company_id: int | None = None, category: str = "all") -> list[sqlite3.Row]:
        where = ["is_active = 1"]
        params: list[Any] = []

        if company_id is not None:
            where.append("company_id = ?")
            params.append(company_id)
        if category in ("eng", "product"):
            where.append("category = ?")
            params.append(category)

        clause = " AND ".join(where)
        sql = (
            "SELECT job_items.*, companies.name as company_name "
            "FROM job_items JOIN companies ON companies.id = job_items.company_id "
            f"WHERE {clause} ORDER BY companies.name ASC, title ASC"
        )
        with self.connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall()
