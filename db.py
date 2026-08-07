from __future__ import annotations

import sqlite3
import os
import tomllib
import json
import ssl
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("interpretation_study.db")
_SUPABASE = None
_REMOTE_CHECKED = False


def _normalize_supabase_url(value: str) -> str:
    url = str(value or "").strip().strip('"').strip("'").rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[:-8].rstrip("/")
    if "://" not in url:
        if "." not in url and "/" not in url:
            url = f"{url}.supabase.co"
        url = f"https://{url}"
    if not url.startswith(("https://", "http://")):
        raise ValueError("SUPABASE_URL 형식이 올바르지 않습니다. Project URL을 https://로 시작하게 입력하세요.")
    return url


class _Result:
    def __init__(self, data): self.data = data


class _RestTable:
    def __init__(self, client, name):
        self.client, self.name = client, name
        self.method, self.payload, self.params, self.headers = "GET", None, [], {}
        self.want_single = False
    def select(self, columns="*"): self.params.append(("select", columns)); return self
    def insert(self, payload): self.method, self.payload = "POST", payload; self.headers["Prefer"] = "return=representation"; return self
    def upsert(self, payload): self.method, self.payload = "POST", payload; self.headers["Prefer"] = "return=representation,resolution=merge-duplicates"; return self
    def update(self, payload): self.method, self.payload = "PATCH", payload; self.headers["Prefer"] = "return=representation"; return self
    def eq(self, column, value): self.params.append((column, f"eq.{value}")); return self
    def gte(self, column, value): self.params.append((column, f"gte.{value}")); return self
    def lte(self, column, value): self.params.append((column, f"lte.{value}")); return self
    def limit(self, value): self.params.append(("limit", str(value))); return self
    def order(self, column, desc=False): self.params.append(("order", f"{column}.{'desc' if desc else 'asc'}")); return self
    def single(self): self.want_single = True; self.headers["Accept"] = "application/vnd.pgrst.object+json"; return self
    def execute(self):
        url = f"{self.client.url}/rest/v1/{quote(self.name)}"
        if self.params: url += "?" + urlencode(self.params)
        body = json.dumps(self.payload).encode() if self.payload is not None else None
        headers = {"apikey": self.client.key, "Authorization": f"Bearer {self.client.key}", "Content-Type": "application/json", **self.headers}
        request = Request(url, data=body, headers=headers, method=self.method)
        try:
            import certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ssl_context = ssl.create_default_context()
        with urlopen(request, timeout=20, context=ssl_context) as response:
            raw = response.read()
        return _Result(json.loads(raw) if raw else ([] if not self.want_single else {}))


class _RestClient:
    def __init__(self, url, key): self.url, self.key = url.rstrip("/"), key
    def table(self, name): return _RestTable(self, name)


def _remote_client():
    global _SUPABASE, _REMOTE_CHECKED
    if _REMOTE_CHECKED:
        return _SUPABASE
    _REMOTE_CHECKED = True
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    secrets_path = Path(__file__).with_name(".streamlit") / "secrets.toml"
    if secrets_path.exists():
        values = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
        url = url or values.get("SUPABASE_URL", "")
        key = key or values.get("SUPABASE_SECRET_KEY", "")
    if not url or not key:
        try:
            import streamlit as st
            url = url or st.secrets.get("SUPABASE_URL", "")
            key = key or st.secrets.get("SUPABASE_SECRET_KEY", "")
        except Exception:
            pass
    if url and key:
        _SUPABASE = _RestClient(_normalize_supabase_url(url), str(key).strip())
    return _SUPABASE


def backend_name() -> str:
    return "Supabase" if _remote_client() else "SQLite"


@contextmanager
def connect(db_path: Path | str = DB_PATH):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | str = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS practices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                practice_date TEXT NOT NULL,
                activity_type TEXT NOT NULL DEFAULT 'simultaneous',
                direction TEXT NOT NULL CHECK(direction IN ('KO→JA', 'JA→KO')),
                title TEXT NOT NULL,
                topic TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                video_speed REAL NOT NULL DEFAULT 1.0,
                minutes INTEGER NOT NULL CHECK(minutes > 0),
                difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
                omission INTEGER NOT NULL DEFAULT 0,
                number_omission INTEGER NOT NULL DEFAULT 0,
                logic_error INTEGER NOT NULL DEFAULT 0,
                expression_block INTEGER NOT NULL DEFAULT 0,
                unnatural_expression INTEGER NOT NULL DEFAULT 0,
                other_notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS language_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                korean TEXT NOT NULL,
                japanese TEXT NOT NULL,
                pair_type TEXT NOT NULL CHECK(pair_type IN ('collocation','term','pattern','other')),
                source TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                mastery INTEGER NOT NULL DEFAULT 1 CHECK(mastery BETWEEN 1 AND 5),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_reviewed_at TEXT,
                review_count INTEGER NOT NULL DEFAULT 0,
                review_score REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_id INTEGER NOT NULL REFERENCES language_pairs(id) ON DELETE CASCADE,
                rating INTEGER NOT NULL CHECK(rating IN (0,1,2)),
                reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS study_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_date TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS script_feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_date TEXT NOT NULL,
                interpretation_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                title TEXT NOT NULL,
                source_script TEXT NOT NULL,
                interpreted_script TEXT NOT NULL,
                feedback TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        practice_columns = {row["name"] for row in conn.execute("PRAGMA table_info(practices)")}
        if "activity_type" not in practice_columns:
            conn.execute(
                "ALTER TABLE practices ADD COLUMN activity_type TEXT NOT NULL DEFAULT 'simultaneous'"
            )
        if "source_url" not in practice_columns:
            conn.execute("ALTER TABLE practices ADD COLUMN source_url TEXT DEFAULT ''")
        if "video_speed" not in practice_columns:
            conn.execute("ALTER TABLE practices ADD COLUMN video_speed REAL NOT NULL DEFAULT 1.0")
        defaults = {
            "exam_date": "2026-12-01",
            "weekly_ko_ja_goal": "70",
            "weekly_ja_ko_goal": "70",
            "weekly_pairs_goal": "40",
        }
        conn.executemany(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", defaults.items()
        )


def query(sql: str, params=(), db_path: Path | str = DB_PATH):
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def execute(sql: str, params=(), db_path: Path | str = DB_PATH) -> int:
    with connect(db_path) as conn:
        cursor = conn.execute(sql, params)
        return cursor.lastrowid


def get_settings(db_path: Path | str = DB_PATH) -> dict[str, str]:
    remote = _remote_client()
    if remote:
        rows = remote.table("settings").select("key,value").execute().data
        return {r["key"]: r["value"] for r in rows}
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings", db_path=db_path)}


def save_settings(values: dict[str, str], db_path: Path | str = DB_PATH) -> None:
    remote = _remote_client()
    if remote:
        remote.table("settings").upsert([{"key": k, "value": v} for k, v in values.items()]).execute()
        return
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            values.items(),
        )


def add_practice(values: dict, db_path: Path | str = DB_PATH) -> int:
    columns = (
        "practice_date", "activity_type", "direction", "title", "topic", "source_url", "video_speed", "minutes", "difficulty",
        "omission", "number_omission", "logic_error", "expression_block",
        "unnatural_expression", "other_notes",
    )
    remote = _remote_client()
    if remote:
        row = remote.table("practices").insert({c: values[c] for c in columns}).execute().data[0]
        return row["id"]
    placeholders = ",".join("?" for _ in columns)
    return execute(
        f"INSERT INTO practices ({','.join(columns)}) VALUES ({placeholders})",
        tuple(values[c] for c in columns), db_path,
    )


def add_pair(values: dict, db_path: Path | str = DB_PATH) -> int:
    remote = _remote_client()
    if remote:
        payload = {"korean": values["korean"], "japanese": values["japanese"], "pair_type": values["pair_type"], "source": values.get("source", ""), "notes": values.get("notes", ""), "mastery": values.get("mastery", 1)}
        return remote.table("language_pairs").insert(payload).execute().data[0]["id"]
    return execute(
        "INSERT INTO language_pairs(korean,japanese,pair_type,source,notes,mastery) VALUES(?,?,?,?,?,?)",
        (values["korean"], values["japanese"], values["pair_type"], values.get("source", ""),
         values.get("notes", ""), values.get("mastery", 1)), db_path,
    )


def add_note(values: dict, db_path: Path | str = DB_PATH) -> int:
    remote = _remote_client()
    if remote:
        return remote.table("study_notes").insert(values).execute().data[0]["id"]
    return execute(
        "INSERT INTO study_notes(note_date,title,content,tags) VALUES(?,?,?,?)",
        (values["note_date"], values["title"], values["content"], values.get("tags", "")),
        db_path,
    )


def add_script_feedback(values: dict, db_path: Path | str = DB_PATH) -> int:
    remote = _remote_client()
    if remote:
        return remote.table("script_feedbacks").insert(values).execute().data[0]["id"]
    return execute(
        "INSERT INTO script_feedbacks(feedback_date,interpretation_type,direction,title,source_script,interpreted_script,feedback) VALUES(?,?,?,?,?,?,?)",
        tuple(values[k] for k in ("feedback_date","interpretation_type","direction","title","source_script","interpreted_script","feedback")), db_path,
    )


def record_review(pair_id: int, rating: int, db_path: Path | str = DB_PATH) -> None:
    remote = _remote_client()
    if remote:
        pair = remote.table("language_pairs").select("*").eq("id", pair_id).single().execute().data
        count = pair["review_count"]
        score = (pair["review_score"] * count + rating) / (count + 1)
        mastery = max(1, min(5, pair["mastery"] + (1 if rating == 2 else -1 if rating == 0 else 0)))
        remote.table("reviews").insert({"pair_id": pair_id, "rating": rating}).execute()
        remote.table("language_pairs").update({"review_count": count + 1, "review_score": score, "mastery": mastery, "last_reviewed_at": datetime.now().astimezone().isoformat()}).eq("id", pair_id).execute()
        return
    with connect(db_path) as conn:
        conn.execute("INSERT INTO reviews(pair_id,rating) VALUES(?,?)", (pair_id, rating))
        conn.execute(
            """UPDATE language_pairs SET review_count=review_count+1,
               review_score=(review_score*review_count + ?)/(review_count+1),
               last_reviewed_at=CURRENT_TIMESTAMP,
               mastery=MIN(5, MAX(1, mastery + CASE WHEN ?=2 THEN 1 WHEN ?=0 THEN -1 ELSE 0 END))
               WHERE id=?""",
            (rating, rating, rating, pair_id),
        )


def review_queue(limit: int = 50, db_path: Path | str = DB_PATH):
    remote = _remote_client()
    if remote:
        rows = remote.table("language_pairs").select("*").limit(1000).execute().data
        rows.sort(key=lambda r: (r["last_reviewed_at"] is not None, r["review_score"], r["mastery"], r["last_reviewed_at"] or ""))
        return rows[:limit]
    return query(
        """SELECT * FROM language_pairs
           ORDER BY CASE WHEN last_reviewed_at IS NULL THEN 0 ELSE 1 END,
                    review_score ASC, mastery ASC, last_reviewed_at ASC
           LIMIT ?""", (limit,), db_path,
    )


def week_start(today: date | None = None) -> str:
    day = today or date.today()
    return (day.fromordinal(day.toordinal() - day.weekday())).isoformat()


def practices_between(start: str, end: str | None = None):
    remote = _remote_client()
    if remote:
        q = remote.table("practices").select("*").gte("practice_date", start)
        if end: q = q.lte("practice_date", end)
        return q.order("practice_date").execute().data
    sql = "SELECT * FROM practices WHERE practice_date>=?"; params = [start]
    if end: sql += " AND practice_date<=?"; params.append(end)
    return query(sql + " ORDER BY practice_date", params)


def all_practices():
    remote = _remote_client()
    if remote: return remote.table("practices").select("*").order("practice_date").execute().data
    return query("SELECT * FROM practices ORDER BY practice_date")


def recent_practices(limit=20):
    rows = all_practices()
    return sorted(rows, key=lambda r: (r["practice_date"], r["id"]), reverse=True)[:limit]


def all_pairs():
    remote = _remote_client()
    if remote: return remote.table("language_pairs").select("*").order("created_at").execute().data
    return query("SELECT * FROM language_pairs ORDER BY created_at")


def find_pairs(term="", pair_type=None, mastery=None):
    rows = all_pairs()
    needle = term.casefold()
    rows = [r for r in rows if needle in (r["korean"] + r["japanese"] + (r.get("source") or "")).casefold()]
    if pair_type: rows = [r for r in rows if r["pair_type"] == pair_type]
    if mastery: rows = [r for r in rows if r["mastery"] == mastery]
    return sorted(rows, key=lambda r: r["id"], reverse=True)


def all_notes():
    remote = _remote_client()
    if remote: return remote.table("study_notes").select("*").order("note_date", desc=True).execute().data
    return query("SELECT * FROM study_notes ORDER BY note_date DESC,id DESC")


def find_notes(term=""):
    needle = term.casefold()
    return [r for r in all_notes() if needle in (r["title"] + r["content"] + (r.get("tags") or "")).casefold()]


def all_script_feedbacks():
    remote = _remote_client()
    if remote: return remote.table("script_feedbacks").select("*").order("feedback_date", desc=True).execute().data
    return query("SELECT * FROM script_feedbacks ORDER BY feedback_date DESC,id DESC")
    def table(self, name): return _RestTable(self, name)


def _remote_client():
    global _SUPABASE, _REMOTE_CHECKED
    if _REMOTE_CHECKED:
        return _SUPABASE
    _REMOTE_CHECKED = True
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    secrets_path = Path(__file__).with_name(".streamlit") / "secrets.toml"
    if secrets_path.exists():
        values = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
        url = url or values.get("SUPABASE_URL", "")
        key = key or values.get("SUPABASE_SECRET_KEY", "")
    if not url or not key:
        try:
            import streamlit as st
            url = url or st.secrets.get("SUPABASE_URL", "")
            key = key or st.secrets.get("SUPABASE_SECRET_KEY", "")
        except Exception:
            pass
    if url and key:
        _SUPABASE = _RestClient(_normalize_supabase_url(url), str(key).strip())
    return _SUPABASE


def backend_name() -> str:
    return "Supabase" if _remote_client() else "SQLite"


@contextmanager
def connect(db_path: Path | str = DB_PATH):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | str = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS practices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                practice_date TEXT NOT NULL,
                activity_type TEXT NOT NULL DEFAULT 'simultaneous',
                direction TEXT NOT NULL CHECK(direction IN ('KO→JA', 'JA→KO')),
                title TEXT NOT NULL,
                topic TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                minutes INTEGER NOT NULL CHECK(minutes > 0),
                difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
                omission INTEGER NOT NULL DEFAULT 0,
                number_omission INTEGER NOT NULL DEFAULT 0,
                logic_error INTEGER NOT NULL DEFAULT 0,
                expression_block INTEGER NOT NULL DEFAULT 0,
                unnatural_expression INTEGER NOT NULL DEFAULT 0,
                other_notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS language_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                korean TEXT NOT NULL,
                japanese TEXT NOT NULL,
                pair_type TEXT NOT NULL CHECK(pair_type IN ('collocation','term','pattern','other')),
                source TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                mastery INTEGER NOT NULL DEFAULT 1 CHECK(mastery BETWEEN 1 AND 5),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_reviewed_at TEXT,
                review_count INTEGER NOT NULL DEFAULT 0,
                review_score REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_id INTEGER NOT NULL REFERENCES language_pairs(id) ON DELETE CASCADE,
                rating INTEGER NOT NULL CHECK(rating IN (0,1,2)),
                reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS study_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_date TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        practice_columns = {row["name"] for row in conn.execute("PRAGMA table_info(practices)")}
        if "activity_type" not in practice_columns:
            conn.execute(
                "ALTER TABLE practices ADD COLUMN activity_type TEXT NOT NULL DEFAULT 'simultaneous'"
            )
        if "source_url" not in practice_columns:
            conn.execute("ALTER TABLE practices ADD COLUMN source_url TEXT DEFAULT ''")
        defaults = {
            "exam_date": "2026-12-01",
            "weekly_ko_ja_goal": "70",
            "weekly_ja_ko_goal": "70",
            "weekly_pairs_goal": "40",
        }
        conn.executemany(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", defaults.items()
        )


def query(sql: str, params=(), db_path: Path | str = DB_PATH):
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def execute(sql: str, params=(), db_path: Path | str = DB_PATH) -> int:
    with connect(db_path) as conn:
        cursor = conn.execute(sql, params)
        return cursor.lastrowid


def get_settings(db_path: Path | str = DB_PATH) -> dict[str, str]:
    remote = _remote_client()
    if remote:
        rows = remote.table("settings").select("key,value").execute().data
        return {r["key"]: r["value"] for r in rows}
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings", db_path=db_path)}


def save_settings(values: dict[str, str], db_path: Path | str = DB_PATH) -> None:
    remote = _remote_client()
    if remote:
        remote.table("settings").upsert([{"key": k, "value": v} for k, v in values.items()]).execute()
        return
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            values.items(),
        )


def add_practice(values: dict, db_path: Path | str = DB_PATH) -> int:
    columns = (
        "practice_date", "activity_type", "direction", "title", "topic", "source_url", "minutes", "difficulty",
        "omission", "number_omission", "logic_error", "expression_block",
        "unnatural_expression", "other_notes",
    )
    remote = _remote_client()
    if remote:
        row = remote.table("practices").insert({c: values[c] for c in columns}).execute().data[0]
        return row["id"]
    placeholders = ",".join("?" for _ in columns)
    return execute(
        f"INSERT INTO practices ({','.join(columns)}) VALUES ({placeholders})",
        tuple(values[c] for c in columns), db_path,
    )


def add_pair(values: dict, db_path: Path | str = DB_PATH) -> int:
    remote = _remote_client()
    if remote:
        payload = {"korean": values["korean"], "japanese": values["japanese"], "pair_type": values["pair_type"], "source": values.get("source", ""), "notes": values.get("notes", ""), "mastery": values.get("mastery", 1)}
        return remote.table("language_pairs").insert(payload).execute().data[0]["id"]
    return execute(
        "INSERT INTO language_pairs(korean,japanese,pair_type,source,notes,mastery) VALUES(?,?,?,?,?,?)",
        (values["korean"], values["japanese"], values["pair_type"], values.get("source", ""),
         values.get("notes", ""), values.get("mastery", 1)), db_path,
    )


def add_note(values: dict, db_path: Path | str = DB_PATH) -> int:
    remote = _remote_client()
    if remote:
        return remote.table("study_notes").insert(values).execute().data[0]["id"]
    return execute(
        "INSERT INTO study_notes(note_date,title,content,tags) VALUES(?,?,?,?)",
        (values["note_date"], values["title"], values["content"], values.get("tags", "")),
        db_path,
    )


def record_review(pair_id: int, rating: int, db_path: Path | str = DB_PATH) -> None:
    remote = _remote_client()
    if remote:
        pair = remote.table("language_pairs").select("*").eq("id", pair_id).single().execute().data
        count = pair["review_count"]
        score = (pair["review_score"] * count + rating) / (count + 1)
        mastery = max(1, min(5, pair["mastery"] + (1 if rating == 2 else -1 if rating == 0 else 0)))
        remote.table("reviews").insert({"pair_id": pair_id, "rating": rating}).execute()
        remote.table("language_pairs").update({"review_count": count + 1, "review_score": score, "mastery": mastery, "last_reviewed_at": datetime.now().astimezone().isoformat()}).eq("id", pair_id).execute()
        return
    with connect(db_path) as conn:
        conn.execute("INSERT INTO reviews(pair_id,rating) VALUES(?,?)", (pair_id, rating))
        conn.execute(
            """UPDATE language_pairs SET review_count=review_count+1,
               review_score=(review_score*review_count + ?)/(review_count+1),
               last_reviewed_at=CURRENT_TIMESTAMP,
               mastery=MIN(5, MAX(1, mastery + CASE WHEN ?=2 THEN 1 WHEN ?=0 THEN -1 ELSE 0 END))
               WHERE id=?""",
            (rating, rating, rating, pair_id),
        )


def review_queue(limit: int = 50, db_path: Path | str = DB_PATH):
    remote = _remote_client()
    if remote:
        rows = remote.table("language_pairs").select("*").limit(1000).execute().data
        rows.sort(key=lambda r: (r["last_reviewed_at"] is not None, r["review_score"], r["mastery"], r["last_reviewed_at"] or ""))
        return rows[:limit]
    return query(
        """SELECT * FROM language_pairs
           ORDER BY CASE WHEN last_reviewed_at IS NULL THEN 0 ELSE 1 END,
                    review_score ASC, mastery ASC, last_reviewed_at ASC
           LIMIT ?""", (limit,), db_path,
    )


def week_start(today: date | None = None) -> str:
    day = today or date.today()
    return (day.fromordinal(day.toordinal() - day.weekday())).isoformat()


def practices_between(start: str, end: str | None = None):
    remote = _remote_client()
    if remote:
        q = remote.table("practices").select("*").gte("practice_date", start)
        if end: q = q.lte("practice_date", end)
        return q.order("practice_date").execute().data
    sql = "SELECT * FROM practices WHERE practice_date>=?"; params = [start]
    if end: sql += " AND practice_date<=?"; params.append(end)
    return query(sql + " ORDER BY practice_date", params)


def all_practices():
    remote = _remote_client()
    if remote: return remote.table("practices").select("*").order("practice_date").execute().data
    return query("SELECT * FROM practices ORDER BY practice_date")


def recent_practices(limit=20):
    rows = all_practices()
    return sorted(rows, key=lambda r: (r["practice_date"], r["id"]), reverse=True)[:limit]


def all_pairs():
    remote = _remote_client()
    if remote: return remote.table("language_pairs").select("*").order("created_at").execute().data
    return query("SELECT * FROM language_pairs ORDER BY created_at")


def find_pairs(term="", pair_type=None, mastery=None):
    rows = all_pairs()
    needle = term.casefold()
    rows = [r for r in rows if needle in (r["korean"] + r["japanese"] + (r.get("source") or "")).casefold()]
    if pair_type: rows = [r for r in rows if r["pair_type"] == pair_type]
    if mastery: rows = [r for r in rows if r["mastery"] == mastery]
    return sorted(rows, key=lambda r: r["id"], reverse=True)


def all_notes():
    remote = _remote_client()
    if remote: return remote.table("study_notes").select("*").order("note_date", desc=True).execute().data
    return query("SELECT * FROM study_notes ORDER BY note_date DESC,id DESC")


def find_notes(term=""):
    needle = term.casefold()
    return [r for r in all_notes() if needle in (r["title"] + r["content"] + (r.get("tags") or "")).casefold()]
