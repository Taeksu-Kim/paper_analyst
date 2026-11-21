"""상태 저장 (SQLite 한 파일) — 논문 상태 덮어쓰기, 후보함, 대화·실행·이벤트. 서비스만 쓴다."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_state (id TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY, title TEXT, src TEXT, signals TEXT, stars INT, hn INT, cit INT, upvotes INT,
  file TEXT, imported_at REAL, decision TEXT, decided_at REAL, abstract TEXT);
CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT, backend TEXT NOT NULL, session_id TEXT,
  created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, chat_id INT, status TEXT, started_at REAL, ended_at REAL,
  cost REAL, error TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, chat_id INT, run_id INT, type TEXT, data TEXT, at REAL);
CREATE INDEX IF NOT EXISTS events_chat ON events(chat_id, id);
CREATE TABLE IF NOT EXISTS paper_tags (id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (id, tag));
CREATE TABLE IF NOT EXISTS links (id INTEGER PRIMARY KEY, src TEXT NOT NULL, dst TEXT NOT NULL, kind TEXT NOT NULL,
  note TEXT, created_at REAL, UNIQUE (src, dst));
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    # 논문 상태
    def states(self) -> dict[str, str]:
        return {r["id"]: r["status"] for r in self.q("SELECT id, status FROM paper_state")}

    def set_state(self, aid: str, status: str | None) -> None:
        if status is None:
            self.x("DELETE FROM paper_state WHERE id=?", (aid,))
        else:
            self.x("INSERT INTO paper_state VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                   "updated_at=excluded.updated_at", (aid, status, time.time()))

    # 후보
    def upsert_candidates(self, rows: list[tuple[dict, str]]) -> None:
        """(후보, 파일 이름) 여러 개를 한 트랜잭션으로 — 줄마다 커밋하면 458줄에 10초 걸렸다 (측정 2026-11-21)."""
        with self.lock:
            self.db.executemany("""INSERT INTO candidates (id,title,src,signals,stars,hn,cit,upvotes,file,imported_at)
                  VALUES (?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET title=COALESCE(excluded.title,title), src=excluded.src,
                    signals=excluded.signals, stars=MAX(COALESCE(stars,0),COALESCE(excluded.stars,0)),
                    hn=MAX(COALESCE(hn,0),COALESCE(excluded.hn,0)), cit=MAX(COALESCE(cit,0),COALESCE(excluded.cit,0)),
                    upvotes=MAX(COALESCE(upvotes,0),COALESCE(excluded.upvotes,0)), file=excluded.file""",
                [(c["id"], c.get("title"), json.dumps(c.get("src", [])), json.dumps(c.get("signals", [])),
                  c.get("stars"), c.get("hn_points"), c.get("cit"), c.get("upvotes"), file, time.time())
                 for c, file in rows])
            self.db.commit()

    def candidates(self) -> list[dict]:
        rows = self.q("SELECT * FROM candidates")
        for r in rows:
            r["src"], r["signals"] = json.loads(r["src"] or "[]"), json.loads(r["signals"] or "[]")
        return rows

    def candidate(self, aid: str) -> dict | None:
        r = self.q("SELECT * FROM candidates WHERE id=?", (aid,))
        return r[0] if r else None

    # 대화
    def event(self, chat_id: int, run_id: int | None, typ: str, data: dict) -> int:
        eid = self.x("INSERT INTO events (chat_id,run_id,type,data,at) VALUES (?,?,?,?,?)",
                     (chat_id, run_id, typ, json.dumps(data, ensure_ascii=False), time.time()))
        self.x("UPDATE chats SET updated_at=? WHERE id=?", (time.time(), chat_id))
        return eid

    def events(self, chat_id: int, after: int = 0) -> list[dict]:
        rows = self.q("SELECT id,run_id,type,data,at FROM events WHERE chat_id=? AND id>? ORDER BY id", (chat_id, after))
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows
