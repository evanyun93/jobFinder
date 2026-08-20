"""Postgres 스토리지 (Supabase).

SQLite 에서 옮겨왔다. README 에 "표준 SQL 만 써서 그대로 이관 가능"이라고
적혀 있었지만 실제로는 아래가 전부 SQLite 전용이라 손봐야 했다:

    ?                                 -> %s
    INTEGER PRIMARY KEY AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY
    datetime('now')                   -> now()
    datetime('now', '-36 hours')      -> now() - make_interval(hours => %s)
    INSERT OR IGNORE                  -> ON CONFLICT DO NOTHING
    SELECT * ... GROUP BY dedup_key   -> SELECT DISTINCT ON (dedup_key)
    active INTEGER 0/1                -> active BOOLEAN

마지막 GROUP BY 가 특히 조용한 함정이었다. SQLite 는 그룹당 아무 행이나
집어주지만 Postgres 는 문법 오류로 거절한다. DISTINCT ON 으로 옮기면서
'같은 공고 중 가장 최근 것'으로 선택 기준까지 명시했다.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from . import regions
from .config import cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id     TEXT        UNIQUE NOT NULL,
    active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS filters (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    regions     TEXT        NOT NULL DEFAULT '[]',
    keywords    TEXT        NOT NULL DEFAULT '[]',
    excludes    TEXT        NOT NULL DEFAULT '[]',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source      TEXT        NOT NULL,
    source_id   TEXT        NOT NULL,
    dedup_key   TEXT        NOT NULL,
    title       TEXT        NOT NULL,
    company     TEXT        NOT NULL,
    region      TEXT        NOT NULL DEFAULT '',
    area        TEXT        NOT NULL DEFAULT '',
    url         TEXT        NOT NULL DEFAULT '',
    salary      TEXT        NOT NULL DEFAULT '',
    career      TEXT        NOT NULL DEFAULT '',
    education   TEXT        NOT NULL DEFAULT '',
    posted_at   TEXT        NOT NULL DEFAULT '',
    closes_at   TEXT        NOT NULL DEFAULT '',
    haystack    TEXT        NOT NULL DEFAULT '',
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_dedup   ON jobs (dedup_key);
CREATE INDEX IF NOT EXISTS idx_jobs_fetched ON jobs (fetched_at);
CREATE INDEX IF NOT EXISTS idx_jobs_area    ON jobs (area);

CREATE TABLE IF NOT EXISTS deliveries (
    user_id   BIGINT      NOT NULL,
    dedup_key TEXT        NOT NULL,
    sent_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, dedup_key)
);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


@contextmanager
def conn():
    if not cfg.database_url:
        raise RuntimeError(
            "DATABASE_URL 이 없습니다. Supabase 연결문자열을 넣으세요.\n"
            "  서버리스에서는 반드시 Transaction pooler(6543) 를 쓸 것 - "
            "직접 접속(5432)은 커넥션이 금방 고갈됩니다.")
    # prepare_threshold=None: Supavisor 의 transaction 모드는 prepared statement
    # 를 지원하지 않는다. psycopg3 는 같은 쿼리를 5번 실행하면 자동으로 prepare
    # 하므로, 끄지 않으면 한동안 잘 돌다가 어느 날 갑자기 터진다.
    c = psycopg.connect(cfg.database_url, row_factory=dict_row,
                        prepare_threshold=None, connect_timeout=10)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.execute(SCHEMA)


# ---------- kv ----------

def kv_get(key: str, default: str | None = None) -> str | None:
    with conn() as c:
        row = c.execute("SELECT v FROM kv WHERE k = %s", (key,)).fetchone()
    return row["v"] if row else default


def kv_set(key: str, value: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO kv(k, v) VALUES(%s, %s) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, value),
        )


# ---------- users / filters ----------

def upsert_user(chat_id: str) -> int:
    with conn() as c:
        # DO UPDATE 는 충돌한 경우에도 행을 돌려주므로 RETURNING 하나로 끝난다
        # (SQLite 판은 INSERT 후 SELECT 를 따로 했다).
        row = c.execute(
            "INSERT INTO users(chat_id) VALUES(%s) "
            "ON CONFLICT(chat_id) DO UPDATE SET active = TRUE "
            "RETURNING id",
            (str(chat_id),),
        ).fetchone()
        uid = row["id"]
        c.execute("INSERT INTO filters(user_id) VALUES(%s) "
                  "ON CONFLICT(user_id) DO NOTHING", (uid,))
    return uid


def deactivate_user(chat_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET active = FALSE WHERE chat_id = %s",
                  (str(chat_id),))


def get_filter(chat_id: str) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(
            "SELECT u.id AS user_id, u.chat_id, f.regions, f.keywords, f.excludes "
            "FROM users u JOIN filters f ON f.user_id = u.id WHERE u.chat_id = %s",
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
            f"UPDATE filters SET {field} = %s, updated_at = now() "
            "WHERE user_id = (SELECT id FROM users WHERE chat_id = %s)",
            (json.dumps(values, ensure_ascii=False), str(chat_id)),
        )


def active_filters() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            "SELECT u.id AS user_id, u.chat_id, f.regions, f.keywords, f.excludes "
            "FROM users u JOIN filters f ON f.user_id = u.id WHERE u.active"
        ).fetchall()
    return [_row_to_filter(r) for r in rows]


def _row_to_filter(row: dict) -> dict[str, Any]:
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
    with conn() as c, c.cursor() as cur:
        cur.executemany(
            "INSERT INTO jobs(source, source_id, dedup_key, title, company, region, area, "
            "url, salary, career, education, posted_at, closes_at, haystack) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(source, source_id) DO NOTHING",
            rows,
        )
        # ON CONFLICT DO NOTHING 이라 rowcount 는 '실제로 들어간' 행만 센다.
        # SQLite 판의 COUNT(*) 전후 비교보다 정확하고 왕복도 두 번 아낀다.
        return cur.rowcount


def unsent_jobs_for(user_id: int, since_hours: int = 36) -> list[dict]:
    """아직 이 사용자에게 보내지 않은, 최근에 수집된 공고.

    DISTINCT ON 은 ORDER BY 가 dedup_key 로 시작해야 해서, 표시용 정렬
    (지역 -> 게시일)은 바깥 쿼리에서 한 번 더 한다.
    """
    with conn() as c:
        return c.execute(
            "SELECT * FROM ("
            "  SELECT DISTINCT ON (j.dedup_key) j.* FROM jobs j"
            "  WHERE j.fetched_at >= now() - make_interval(hours => %s)"
            "    AND j.area <> ''"
            "    AND NOT EXISTS (SELECT 1 FROM deliveries d"
            "                    WHERE d.user_id = %s AND d.dedup_key = j.dedup_key)"
            "  ORDER BY j.dedup_key, j.posted_at DESC, j.id DESC"
            ") t "
            "ORDER BY t.area, t.posted_at DESC, t.id DESC",
            (since_hours, user_id),
        ).fetchall()


def mark_delivered(user_id: int, dedup_keys: Iterable[str]) -> None:
    keys = [(user_id, k) for k in dedup_keys]
    if not keys:
        return
    with conn() as c, c.cursor() as cur:
        cur.executemany(
            "INSERT INTO deliveries(user_id, dedup_key) VALUES(%s, %s) "
            "ON CONFLICT DO NOTHING",
            keys,
        )
