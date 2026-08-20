"""SQLite 스토리지. 스키마가 단순해서 MVP는 SQLite로 충분하고,
그대로 PostgreSQL 로 옮길 수 있게 표준 SQL 만 쓴다."""
import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from . import regions
from .config import cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         TEXT UNIQUE NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS filters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    regions       TEXT NOT NULL DEFAULT '[]',
    keywords      TEXT NOT NULL DEFAULT '[]',
    excludes      TEXT NOT NULL DEFAULT '[]',
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    dedup_key     TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    region        TEXT NOT NULL DEFAULT '',
    area          TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    salary        TEXT NOT NULL DEFAULT '',
    career        TEXT NOT NULL DEFAULT '',
    education     TEXT NOT NULL DEFAULT '',
    posted_at     TEXT NOT NULL DEFAULT '',
    closes_at     TEXT NOT NULL DEFAULT '',
    haystack      TEXT NOT NULL DEFAULT '',
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_dedup   ON jobs(dedup_key);
CREATE INDEX IF NOT EXISTS idx_jobs_fetched ON jobs(fetched_at);
CREATE INDEX IF NOT EXISTS idx_jobs_area    ON jobs(area);

-- 같은 공고를 두 번 보내지 않기 위한 발송 원장
CREATE TABLE IF NOT EXISTS deliveries (
    user_id   INTEGER NOT NULL,
    dedup_key TEXT NOT NULL,
    sent_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, dedup_key)
);

-- 봇 롱폴링 오프셋 등 잡다한 상태
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(cfg.db_path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


# ---------- kv ----------

def kv_get(key: str, default: str | None = None) -> str | None:
    with conn() as c:
        row = c.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    return row["v"] if row else default


def kv_set(key: str, value: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, value),
        )


# ---------- users / filters ----------

def upsert_user(chat_id: str) -> int:
    with conn() as c:
        c.execute(
            "INSERT INTO users(chat_id) VALUES(?) "
            "ON CONFLICT(chat_id) DO UPDATE SET active = 1",
            (str(chat_id),),
        )
        row = c.execute("SELECT id FROM users WHERE chat_id = ?", (str(chat_id),)).fetchone()
        uid = row["id"]
        c.execute("INSERT OR IGNORE INTO filters(user_id) VALUES(?)", (uid,))
    return uid


def deactivate_user(chat_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET active = 0 WHERE chat_id = ?", (str(chat_id),))


def get_filter(chat_id: str) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(
            "SELECT u.id AS user_id, u.chat_id, f.regions, f.keywords, f.excludes "
            "FROM users u JOIN filters f ON f.user_id = u.id WHERE u.chat_id = ?",
            (str(chat_id),),
        ).fetchone()
    if not row:
        return None
    return _row_to_filter(row)


def set_filter_field(chat_id: str, field: str, values: list[str]) -> None:
    if field not in ("regions", "keywords", "excludes"):
        raise ValueError(field)
    with conn() as c:
        c.execute(
            f"UPDATE filters SET {field} = ?, updated_at = datetime('now') "
            "WHERE user_id = (SELECT id FROM users WHERE chat_id = ?)",
            (json.dumps(values, ensure_ascii=False), str(chat_id)),
        )


def active_filters() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            "SELECT u.id AS user_id, u.chat_id, f.regions, f.keywords, f.excludes "
            "FROM users u JOIN filters f ON f.user_id = u.id WHERE u.active = 1"
        ).fetchall()
    return [_row_to_filter(r) for r in rows]


def _row_to_filter(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "chat_id": row["chat_id"],
        "regions": json.loads(row["regions"]),
        "keywords": json.loads(row["keywords"]),
        "excludes": json.loads(row["excludes"]),
    }


# ---------- jobs ----------

def upsert_jobs(jobs: Iterable[Any]) -> int:
    """Job 객체들을 저장하고 새로 들어간 건수를 돌려준다."""
    rows = [
        (
            j.source, j.source_id, j.dedup_key, j.title, j.company, j.region,
            regions.area_of(j.region) or "", j.url, j.salary, j.career,
            j.education, j.posted_at, j.closes_at, j.haystack(),
        )
        for j in jobs
    ]
    if not rows:
        return 0
    with conn() as c:
        before = c.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        c.executemany(
            "INSERT INTO jobs(source, source_id, dedup_key, title, company, region, area, "
            "url, salary, career, education, posted_at, closes_at, haystack) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source, source_id) DO NOTHING",
            rows,
        )
        after = c.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    return after - before


def unsent_jobs_for(user_id: int, since_hours: int = 36) -> list[sqlite3.Row]:
    """아직 이 사용자에게 보내지 않은, 최근에 수집된 공고."""
    with conn() as c:
        return c.execute(
            "SELECT * FROM jobs j "
            "WHERE j.fetched_at >= datetime('now', ?) "
            "  AND j.area != '' "
            "  AND NOT EXISTS (SELECT 1 FROM deliveries d "
            "                  WHERE d.user_id = ? AND d.dedup_key = j.dedup_key) "
            "GROUP BY j.dedup_key "
            "ORDER BY j.area, j.posted_at DESC, j.id DESC",
            (f"-{since_hours} hours", user_id),
        ).fetchall()


def mark_delivered(user_id: int, dedup_keys: Iterable[str]) -> None:
    with conn() as c:
        c.executemany(
            "INSERT OR IGNORE INTO deliveries(user_id, dedup_key) VALUES(?, ?)",
            [(user_id, k) for k in dedup_keys],
        )
