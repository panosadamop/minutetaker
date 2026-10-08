"""SQLite storage with FTS5 full-text search."""
from __future__ import annotations

import json
import unicodedata
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meeting (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'Other',
  started_at TEXT,
  duration_s REAL DEFAULT 0,
  language TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  audio_path TEXT,
  mic_path TEXT,
  system_path TEXT,
  participants_hint TEXT DEFAULT '',
  agenda TEXT DEFAULT '',
  source TEXT DEFAULT '',
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS participant (
  id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  display_name TEXT NOT NULL,
  is_self INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS segment (
  id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
  participant_id TEXT REFERENCES participant(id) ON DELETE SET NULL,
  start_s REAL NOT NULL,
  end_s REAL NOT NULL,
  text TEXT NOT NULL,
  edited INTEGER NOT NULL DEFAULT 0,
  media TEXT
);
CREATE INDEX IF NOT EXISTS ix_segment_meeting ON segment(meeting_id, start_s);
CREATE TABLE IF NOT EXISTS minutes (
  meeting_id TEXT PRIMARY KEY REFERENCES meeting(id) ON DELETE CASCADE,
  template TEXT NOT NULL,
  language TEXT,
  content_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summary (
  meeting_id TEXT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (meeting_id, kind)
);
CREATE TABLE IF NOT EXISTS action_item (
  id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
  task TEXT NOT NULL,
  owner TEXT DEFAULT '',
  due TEXT DEFAULT '',
  status TEXT DEFAULT 'open'
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  meeting_id UNINDEXED, kind UNINDEXED, body UNINDEXED, norm, tokenize='unicode61 remove_diacritics 2'
);
"""


def normalize(text: str) -> str:
    """Case- and accent-insensitive form (Greek tonos, Latin diacritics). Keeps length for NFC input."""
    nfd = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in nfd if not unicodedata.combining(c)).casefold()


def excerpt(body: str, terms: list[str], width: int = 60) -> str:
    norm = normalize(body)
    pos = min([i for i in (norm.find(t) for t in terms) if i >= 0] or [0])
    a, b = max(0, pos - width), min(len(body), pos + width)
    return ("…" if a else "") + body[a:b].replace("\n", " ") + ("…" if b < len(body) else "")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self._all("PRAGMA table_info(meeting)")}
        if "source" not in cols:  # recording | media | transcript | chat ('' = before imports existed)
            self._exec("ALTER TABLE meeting ADD COLUMN source TEXT DEFAULT ''")
        if "media" not in {r["name"] for r in self._all("PRAGMA table_info(segment)")}:
            self._exec("ALTER TABLE segment ADD COLUMN media TEXT")  # voice note file, relative to meeting dir

    # ---- helpers --------------------------------------------------------
    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def _one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    # ---- meetings -------------------------------------------------------
    def create_meeting(self, title: str, platform: str = "Other", **fields) -> dict:
        mid = new_id()
        data = {"id": mid, "title": title or "Untitled meeting", "platform": platform,
                "started_at": fields.pop("started_at", None) or now_iso(),
                "created_at": now_iso(), **fields}
        cols = ",".join(data)
        self._exec(f"INSERT INTO meeting ({cols}) VALUES ({','.join('?' * len(data))})", data.values())
        return self.get_meeting(mid)

    def get_meeting(self, mid: str) -> Optional[dict]:
        return self._one("SELECT * FROM meeting WHERE id=?", (mid,))

    def list_meetings(self) -> list[dict]:
        return self._all("SELECT * FROM meeting ORDER BY started_at DESC")

    UPDATABLE = {"title", "platform", "started_at", "duration_s", "language", "status",
                 "audio_path", "mic_path", "system_path", "participants_hint", "agenda", "error"}

    def update_meeting(self, mid: str, **fields) -> Optional[dict]:
        fields = {k: v for k, v in fields.items() if k in self.UPDATABLE}
        if fields:
            sets = ",".join(f"{k}=?" for k in fields)
            self._exec(f"UPDATE meeting SET {sets} WHERE id=?", [*fields.values(), mid])
        return self.get_meeting(mid)

    def delete_meeting(self, mid: str) -> None:
        self._exec("DELETE FROM search_fts WHERE meeting_id=?", (mid,))
        self._exec("DELETE FROM meeting WHERE id=?", (mid,))

    # ---- participants & segments ---------------------------------------
    def replace_transcript(self, mid: str, participants: list[dict], segments: list[dict]) -> None:
        """participants: [{label, display_name, is_self}]; segments: [{label, start, end, text, media?}]"""
        with self._lock:
            c = self.conn
            c.execute("DELETE FROM segment WHERE meeting_id=?", (mid,))
            c.execute("DELETE FROM participant WHERE meeting_id=?", (mid,))
            ids = {}
            for p in participants:
                pid = new_id()
                ids[p["label"]] = pid
                c.execute("INSERT INTO participant VALUES (?,?,?,?,?)",
                          (pid, mid, p["label"], p.get("display_name") or p["label"], int(p.get("is_self", 0))))
            for s in segments:
                c.execute("INSERT INTO segment (id, meeting_id, participant_id, start_s, end_s, text, edited, media) "
                          "VALUES (?,?,?,?,?,?,0,?)", (new_id(), mid, ids.get(s["label"]), float(s["start"]),
                                                      float(s["end"]), s["text"].strip(), s.get("media")))
            c.commit()
        self.reindex(mid)

    def participants(self, mid: str) -> list[dict]:
        return self._all("SELECT * FROM participant WHERE meeting_id=? ORDER BY is_self DESC, label", (mid,))

    def rename_participant(self, pid: str, display_name: str) -> None:
        self._exec("UPDATE participant SET display_name=? WHERE id=?", (display_name, pid))

    def segments(self, mid: str) -> list[dict]:
        return self._all(
            """SELECT s.*, p.display_name AS speaker, p.label AS speaker_label, p.is_self
               FROM segment s LEFT JOIN participant p ON p.id = s.participant_id
               WHERE s.meeting_id=? ORDER BY s.start_s, s.rowid""", (mid,))

    def update_segment(self, sid: str, text: Optional[str] = None, participant_id: Optional[str] = None) -> None:
        if text is not None:
            self._exec("UPDATE segment SET text=?, edited=1 WHERE id=?", (text, sid))
        if participant_id is not None:
            self._exec("UPDATE segment SET participant_id=?, edited=1 WHERE id=?", (participant_id, sid))
        row = self._one("SELECT meeting_id FROM segment WHERE id=?", (sid,))
        if row:
            self.reindex(row["meeting_id"])

    def set_segment_texts(self, mid: str, texts: dict[str, str]) -> None:
        """Machine-produced text (e.g. voice note transcription): not flagged as a user edit."""
        with self._lock:
            for sid, text in texts.items():
                self.conn.execute("UPDATE segment SET text=? WHERE id=? AND meeting_id=?", (text, sid, mid))
            self.conn.commit()
        self.reindex(mid)

    def clear_media(self, mid: str) -> None:
        self._exec("UPDATE segment SET media=NULL WHERE meeting_id=?", (mid,))

    # ---- minutes / summaries -------------------------------------------
    def save_minutes(self, mid: str, template: str, language: str, content: dict) -> None:
        self._exec("INSERT OR REPLACE INTO minutes VALUES (?,?,?,?,?)",
                   (mid, template, language, json.dumps(content, ensure_ascii=False), now_iso()))
        with self._lock:
            self.conn.execute("DELETE FROM action_item WHERE meeting_id=?", (mid,))
            for a in content.get("action_items", []):
                self.conn.execute("INSERT INTO action_item VALUES (?,?,?,?,?,?)",
                                  (new_id(), mid, a.get("task", ""), a.get("owner", ""), a.get("due", ""),
                                   a.get("status", "open")))
            self.conn.commit()
        self.reindex(mid)

    def get_minutes(self, mid: str) -> Optional[dict]:
        row = self._one("SELECT * FROM minutes WHERE meeting_id=?", (mid,))
        if not row:
            return None
        row["content"] = json.loads(row.pop("content_json"))
        return row

    def save_summary(self, mid: str, kind: str, content: str) -> None:
        self._exec("INSERT OR REPLACE INTO summary VALUES (?,?,?,?)", (mid, kind, content, now_iso()))
        self.reindex(mid)

    def summaries(self, mid: str) -> dict[str, str]:
        return {r["kind"]: r["content"] for r in self._all("SELECT * FROM summary WHERE meeting_id=?", (mid,))}

    def action_items(self, mid: str) -> list[dict]:
        return self._all("SELECT * FROM action_item WHERE meeting_id=?", (mid,))

    # ---- search ---------------------------------------------------------
    def reindex(self, mid: str) -> None:
        m = self.get_meeting(mid)
        if not m:
            return
        with self._lock:
            c = self.conn
            c.execute("DELETE FROM search_fts WHERE meeting_id=?", (mid,))
            
            def add(kind, body):
                c.execute("INSERT INTO search_fts VALUES (?,?,?,?)", (mid, kind, body, normalize(body)))

            add("title", m["title"])
            for s in c.execute("SELECT text FROM segment WHERE meeting_id=?", (mid,)).fetchall():
                add("transcript", s["text"])
            row = c.execute("SELECT content_json FROM minutes WHERE meeting_id=?", (mid,)).fetchone()
            if row:
                content = json.loads(row["content_json"])
                add("minutes", " ".join(_flatten(content)))
            for s in c.execute("SELECT content FROM summary WHERE meeting_id=?", (mid,)).fetchall():
                add("summary", s["content"])
            c.commit()

    def search(self, q: str, limit: int = 50) -> list[dict]:
        terms = [normalize(t.replace('"', "")) for t in q.split() if t.strip()]
        if not terms:
            return []
        match = " ".join(f'"{t}"*' for t in terms)
        rows = self._all(
            """SELECT f.meeting_id, f.kind, f.body, m.title, m.started_at, m.platform
               FROM search_fts f JOIN meeting m ON m.id = f.meeting_id
               WHERE search_fts MATCH ? ORDER BY rank LIMIT ?""", (match, limit))
        for r in rows:
            r["snippet"] = excerpt(r.pop("body"), terms)
        return rows


def _flatten(v) -> list[str]:
    if isinstance(v, dict):
        return [x for val in v.values() for x in _flatten(val)]
    if isinstance(v, list):
        return [x for val in v for x in _flatten(val)]
    return [str(v)] if v else []
