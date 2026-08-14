from __future__ import annotations

import sqlite3
import os
import tomllib
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("interpretation_study.db")
_SUPABASE = None
_REMOTE_CHECKED = False
_SSL_CONTEXT = None


def _ssl_context():
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            import certifi
            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


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
    def delete(self): self.method, self.payload = "DELETE", None; self.headers["Prefer"] = "return=representation"; return self
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
            with urlopen(request, timeout=20, context=_ssl_context()) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"Supabase 요청 오류({exc.code}): {detail[:600]}") from exc
        except URLError as exc:
            raise RuntimeError(f"Supabase 연결 실패: {exc.reason}") from exc
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
                direction TEXT NOT NULL CHECK(direction IN ('KO→JA', 'JA→KO', '없음')),
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
                important INTEGER NOT NULL DEFAULT 0 CHECK(important IN (0,1)),
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
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                todo_date TEXT NOT NULL,
                content TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
            CREATE TABLE IF NOT EXISTS script_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                script_text TEXT NOT NULL,
                highlights TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sight_translation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                practice_date TEXT NOT NULL,
                direction TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS study_materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content_html TEXT NOT NULL DEFAULT '',
                language_direction TEXT NOT NULL DEFAULT '한일',
                interpretation_mode TEXT NOT NULL DEFAULT '동시',
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
        if "video_speed" not in practice_columns:
            conn.execute("ALTER TABLE practices ADD COLUMN video_speed REAL NOT NULL DEFAULT 1.0")
        pair_columns = {row["name"] for row in conn.execute("PRAGMA table_info(language_pairs)")}
        if "important" not in pair_columns:
            conn.execute("ALTER TABLE language_pairs ADD COLUMN important INTEGER NOT NULL DEFAULT 0")
        material_columns = {row["name"] for row in conn.execute("PRAGMA table_info(study_materials)")}
        if "language_direction" not in material_columns:
            conn.execute("ALTER TABLE study_materials ADD COLUMN language_direction TEXT NOT NULL DEFAULT '한일'")
        if "interpretation_mode" not in material_columns:
            conn.execute("ALTER TABLE study_materials ADD COLUMN interpretation_mode TEXT NOT NULL DEFAULT '동시'")
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
        payload = {"korean": values["korean"], "japanese": values["japanese"], "pair_type": values.get("pair_type", "other"), "source": values.get("source", ""), "notes": values.get("notes", ""), "important": bool(values.get("important", False)), "mastery": values.get("mastery", 1)}
        return remote.table("language_pairs").insert(payload).execute().data[0]["id"]
    return execute(
        "INSERT INTO language_pairs(korean,japanese,pair_type,source,notes,important,mastery) VALUES(?,?,?,?,?,?,?)",
        (values["korean"], values["japanese"], values.get("pair_type", "other"), values.get("source", ""),
         values.get("notes", ""), int(bool(values.get("important", False))), values.get("mastery", 1)), db_path,
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


def add_todo(content: str, todo_date: str, db_path: Path | str = DB_PATH) -> int:
    payload = {"todo_date": todo_date, "content": content, "completed": False}
    remote = _remote_client()
    if remote:
        return remote.table("todos").insert(payload).execute().data[0]["id"]
    return execute(
        "INSERT INTO todos(todo_date,content,completed) VALUES(?,?,0)",
        (todo_date, content), db_path,
    )


def todos_for_date(todo_date: str, db_path: Path | str = DB_PATH):
    remote = _remote_client()
    if remote:
        return remote.table("todos").select("*").eq("todo_date", todo_date).order("id").execute().data
    return query("SELECT * FROM todos WHERE todo_date=? ORDER BY id", (todo_date,), db_path)


def set_todo_completed(todo_id: int, completed: bool, db_path: Path | str = DB_PATH) -> None:
    remote = _remote_client()
    if remote:
        remote.table("todos").update({"completed": bool(completed)}).eq("id", todo_id).execute()
        return
    execute("UPDATE todos SET completed=? WHERE id=?", (int(bool(completed)), todo_id), db_path)


def delete_todo(todo_id: int, db_path: Path | str = DB_PATH) -> None:
    remote = _remote_client()
    if remote:
        remote.table("todos").delete().eq("id", todo_id).execute()
        return
    execute("DELETE FROM todos WHERE id=?", (todo_id,), db_path)


def add_script_feedback(values: dict, db_path: Path | str = DB_PATH) -> int:
    remote = _remote_client()
    if remote:
        return remote.table("script_feedbacks").insert(values).execute().data[0]["id"]
    return execute(
        "INSERT INTO script_feedbacks(feedback_date,interpretation_type,direction,title,source_script,interpreted_script,feedback) VALUES(?,?,?,?,?,?,?)",
        tuple(values[k] for k in ("feedback_date","interpretation_type","direction","title","source_script","interpreted_script","feedback")), db_path,
    )


def add_study_material(title: str, content_html: str, language_direction: str, interpretation_mode: str, db_path: Path | str = DB_PATH) -> int:
    payload = {"title": title, "content_html": content_html, "language_direction": language_direction, "interpretation_mode": interpretation_mode}
    remote = _remote_client()
    if remote: return remote.table("study_materials").insert(payload).execute().data[0]["id"]
    return execute("INSERT INTO study_materials(title,content_html,language_direction,interpretation_mode) VALUES(?,?,?,?)", (title, content_html, language_direction, interpretation_mode), db_path)


def all_study_materials(db_path: Path | str = DB_PATH):
    remote = _remote_client()
    if remote: return remote.table("study_materials").select("*").order("id", desc=True).execute().data
    return query("SELECT * FROM study_materials ORDER BY id DESC", db_path=db_path)


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
    remote = _remote_client()
    if remote:
        return remote.table("practices").select("*").order("practice_date", desc=True).limit(limit).execute().data
    return query("SELECT * FROM practices ORDER BY practice_date DESC,id DESC LIMIT ?", (limit,))


def all_pairs(db_path: Path | str = DB_PATH):
    remote = _remote_client()
    if remote: return remote.table("language_pairs").select("*").order("created_at").execute().data
    return query("SELECT * FROM language_pairs ORDER BY created_at", db_path=db_path)


def pairs_created_since(start: str, db_path: Path | str = DB_PATH) -> int:
    remote = _remote_client()
    if remote:
        return len(remote.table("language_pairs").select("id").gte("created_at", start).execute().data)
    return int(query("SELECT COUNT(*) AS count FROM language_pairs WHERE created_at>=?", (start,), db_path)[0]["count"])


def find_pairs(term="", pair_type=None, mastery=None, important_only=False, db_path: Path | str = DB_PATH):
    rows = all_pairs(db_path)
    needle = term.casefold()
    rows = [r for r in rows if needle in (r["korean"] + r["japanese"] + (r.get("source") or "")).casefold()]
    if pair_type: rows = [r for r in rows if r["pair_type"] == pair_type]
    if mastery: rows = [r for r in rows if r["mastery"] == mastery]
    if important_only: rows = [r for r in rows if bool(r.get("important", False))]
    return sorted(rows, key=lambda r: r["id"], reverse=True)


def all_notes():
    remote = _remote_client()
    if remote: return remote.table("study_notes").select("*").order("note_date", desc=True).execute().data
    return query("SELECT * FROM study_notes ORDER BY note_date DESC,id DESC")


def recent_notes(limit=3, db_path: Path | str = DB_PATH):
    remote = _remote_client()
    if remote:
        return remote.table("study_notes").select("*").order("note_date", desc=True).limit(limit).execute().data
    return query("SELECT * FROM study_notes ORDER BY note_date DESC,id DESC LIMIT ?", (limit,), db_path)


def find_notes(term=""):
    needle = term.casefold()
    return [r for r in all_notes() if needle in (r["title"] + r["content"] + (r.get("tags") or "")).casefold()]


def all_script_feedbacks(limit=None):
    remote = _remote_client()
    if remote:
        query_builder = remote.table("script_feedbacks").select("*").order("id", desc=True)
        if limit is not None: query_builder = query_builder.limit(limit)
        return query_builder.execute().data
    sql = "SELECT * FROM script_feedbacks ORDER BY feedback_date DESC,id DESC"
    return query(sql + (" LIMIT ?" if limit is not None else ""), (limit,) if limit is not None else ())


def add_script_review(title: str, script_text: str, db_path: Path | str = DB_PATH) -> int:
    payload = {"title": title, "script_text": script_text, "highlights": "[]"}
    remote = _remote_client()
    if remote: return remote.table("script_reviews").insert(payload).execute().data[0]["id"]
    return execute("INSERT INTO script_reviews(title,script_text,highlights) VALUES(?,?,?)", (title,script_text,"[]"), db_path)


def all_script_reviews():
    remote = _remote_client()
    if remote: return remote.table("script_reviews").select("*").order("id", desc=True).execute().data
    return query("SELECT * FROM script_reviews ORDER BY id DESC")


def add_sight_translation(direction: str, practice_date: str | None = None, db_path: Path | str = DB_PATH) -> int:
    payload = {"practice_date": practice_date or date.today().isoformat(), "direction": direction}
    remote = _remote_client()
    if remote: return remote.table("sight_translation_events").insert(payload).execute().data[0]["id"]
    return execute("INSERT INTO sight_translation_events(practice_date,direction) VALUES(?,?)", (payload["practice_date"],direction), db_path)


def sight_translation_events(start: str, end: str | None = None, db_path: Path | str = DB_PATH):
    remote = _remote_client()
    if remote:
        q = remote.table("sight_translation_events").select("*").gte("practice_date", start)
        if end: q = q.lte("practice_date", end)
        return q.execute().data
    sql="SELECT * FROM sight_translation_events WHERE practice_date>=?"; params=[start]
    if end: sql+=" AND practice_date<=?"; params.append(end)
    return query(sql, params, db_path=db_path)


EDITABLE_COLUMNS = {
    "practices": {"practice_date","activity_type","direction","title","topic","source_url","video_speed","minutes","difficulty","omission","number_omission","logic_error","expression_block","unnatural_expression","other_notes"},
    "language_pairs": {"korean","japanese","pair_type","source","notes","important","mastery"},
    "study_notes": {"note_date","title","content","tags"},
    "todos": {"todo_date","content","completed"},
    "script_feedbacks": {"feedback_date","interpretation_type","direction","title","source_script","interpreted_script","feedback"},
    "study_materials": {"title","content_html","language_direction","interpretation_mode"},
    "script_reviews": {"title","script_text","highlights"},
    "settings": {"value"},
}


def table_rows(table: str):
    if table not in EDITABLE_COLUMNS:
        raise ValueError("수정할 수 없는 데이터 유형입니다.")
    remote = _remote_client()
    order = "key" if table == "settings" else "id"
    if remote:
        return remote.table(table).select("*").order(order, desc=table != "settings").execute().data
    return query(f"SELECT * FROM {table} ORDER BY {order} {'DESC' if table != 'settings' else 'ASC'}")


def update_record(table: str, record_id, values: dict, db_path: Path | str = DB_PATH) -> None:
    if table not in EDITABLE_COLUMNS:
        raise ValueError("수정할 수 없는 데이터 유형입니다.")
    clean = {k: v for k, v in values.items() if k in EDITABLE_COLUMNS[table]}
    if not clean:
        return
    id_column = "key" if table == "settings" else "id"
    remote = _remote_client()
    if remote:
        remote.table(table).update(clean).eq(id_column, record_id).execute()
        return
    assignments = ",".join(f"{column}=?" for column in clean)
    execute(f"UPDATE {table} SET {assignments} WHERE {id_column}=?", (*clean.values(), record_id), db_path)
