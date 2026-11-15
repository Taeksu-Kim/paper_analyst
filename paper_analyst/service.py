"""서비스 — 상태의 유일한 주인. 제품 API(app.py)는 이것만 부른다 (A2A 를 붙여도 같은 함수).

서재 = 파일(library/·lists/·ideas/) + 상태 덮어쓰기(SQLite). 후보함 = discover 결과(jsonl)를 가져와 판정.
대화 = ChatBackend 2종(chat.py) 중 대화마다 하나, 이벤트는 SQLite 에 쌓고 화면은 그걸 SSE 로 읽는다.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

from paper_analyst import library as L
from paper_analyst import resolve as R
from paper_analyst.chat import ChatBackend, ChatCtx, Tool
from paper_analyst.store import Store

STATUSES = {"to_read": "읽을 것", "fetched": "받음", "noted": "정리됨", "applied": "적용함", "hold": "보류", "excluded": "제외"}
OVERRIDES = {"to_read", "applied", "hold", "excluded"}      # 사람이 정하는 상태 (나머지는 파일에서 나옴)
DECISIONS = {"read": "읽기", "hold": "보류", "exclude": "제외"}


class NotFound(Exception):
    pass


class Busy(Exception):
    pass


class Unavailable(Exception):
    pass


class Service:
    def __init__(self, root: Path, db_path: Path, backends: dict[str, ChatBackend] | None = None,
                 abstract_fn: Callable[[str], str] | None = None,
                 fetch_fn: Callable[[str], dict] | None = None) -> None:
        self.root = root
        self.store = Store(db_path)
        self.abstract_fn = abstract_fn or _abstract_online
        self.fetch_fn = fetch_fn or _fetch_paper
        self.backends: dict[str, ChatBackend] = backends if backends is not None else {}
        self.procs: dict[int, object] = {}
        self.canceled: set[int] = set()
        self.lock = threading.Lock()
        # 재시작: 돌던 실행은 끊긴 것으로
        for r in self.store.q("SELECT id, chat_id FROM runs WHERE status='running'"):
            self.store.x("UPDATE runs SET status='interrupted', ended_at=? WHERE id=?", (time.time(), r["id"]))
            self.store.event(r["chat_id"], r["id"], "run_end", {"status": "interrupted",
                                                                 "message": "서버가 다시 켜져서 이 실행은 끊겼습니다."})

    # ── 서재 ────────────────────────────────────────────
    def library(self) -> dict:
        papers = L.scan_papers(self.root)
        states = self.store.states()
        items = []
        for p in papers.values():
            st = states.get(p.id) or ("noted" if p.has_notes else "fetched")
            items.append({**p.dict(), "status": st})
        # 읽기로 고른 후보 중 아직 안 받은 것
        for c in self.store.q("SELECT id, title FROM candidates WHERE decision='read'"):
            if c["id"] not in papers:
                st = states.get(c["id"], "to_read")
                items.append({"id": c["id"], "title": c["title"] or c["id"], "status": st, "conclusion": "",
                              "has_notes": False, "has_private": False, "noted_at": 0, "published": "", "category": ""})
        items = [i for i in items if i["status"] != "excluded"]
        counts = {k: sum(1 for i in items if i["status"] == k) for k in STATUSES}
        return {"papers": items, "docs": L.scan_docs(self.root), "counts": counts, "status_names": STATUSES}

    def paper(self, aid: str) -> dict:
        lib = {p["id"]: p for p in self.library()["papers"]}
        if aid not in lib:
            raise NotFound(aid)
        f = L.paper_files(self.root, aid)
        cand = self.store.candidate(aid)
        return {**lib[aid], "abstract": f["meta"].get("abstract") or (cand or {}).get("abstract") or "",
                "authors": f["meta"].get("authors", []), "abs_url": f"https://arxiv.org/abs/{aid}",
                "notes_html": L.to_html(f["notes"]) if f["notes"] else "",
                "private_html": L.to_html(f["private"]) if f["private"] else ""}

    def set_status(self, aid: str, status: str | None) -> dict:
        if status is not None and status not in OVERRIDES:
            raise ValueError(f"사람이 정할 수 있는 상태: {sorted(OVERRIDES)} (또는 null = 파일 기준)")
        self.store.set_state(aid, status)
        return self.paper(aid) if status != "excluded" else {"id": aid, "status": "excluded"}

    def doc(self, kind: str, name: str) -> dict:
        try:
            d = L.read_doc(self.root, kind, name)
        except FileNotFoundError as e:
            raise NotFound(name) from e
        return {"kind": kind, "name": name, "html": L.to_html(d["text"]),
                "private_html": L.to_html(d["private"]) if d["private"] else ""}

    # ── 후보함 ──────────────────────────────────────────
    def import_candidates(self) -> int:
        n = 0
        for f in sorted((self.root / "library" / "candidates").glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    c = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if c.get("id"):
                    self.store.upsert_candidate(c, f.name)
                    n += 1
        return n

    def candidates(self, view: str = "signal") -> dict:
        self.import_candidates()
        rows = self.store.candidates()
        fetched = set(L.scan_papers(self.root))
        for r in rows:
            r["in_library"] = r["id"] in fetched
        undecided = [r for r in rows if not r["decision"] and not r["in_library"]]
        signal = [r for r in undecided if r["signals"]]
        pool = signal if view == "signal" else undecided if view == "all" else [r for r in rows if r["decision"]]
        pool.sort(key=lambda r: (-len(r["signals"]), -(r["hn"] or 0), -(r["stars"] or 0), -(r["cit"] or 0),
                                 -(r["upvotes"] or 0)))
        files = sorted({r["file"] for r in rows if r["file"]})
        return {"items": pool[:300], "counts": {"signal": len(signal), "all": len(undecided),
                                                "decided": sum(1 for r in rows if r["decision"])},
                "files": files}

    def decide(self, aid: str, decision: str | None) -> dict:
        if decision is not None and decision not in DECISIONS:
            raise ValueError(f"판정: {sorted(DECISIONS)} (또는 null = 되돌리기)")
        if not self.store.candidate(aid):
            raise NotFound(aid)
        self.store.x("UPDATE candidates SET decision=?, decided_at=? WHERE id=?", (decision, time.time(), aid))
        return self.store.candidate(aid)

    def abstract(self, aid: str) -> str:
        c = self.store.candidate(aid)
        if c and c.get("abstract"):
            return c["abstract"]
        text = self.abstract_fn(aid)
        if c and text:
            self.store.x("UPDATE candidates SET abstract=? WHERE id=?", (text, aid))
        return text

    # ── 대화 ────────────────────────────────────────────
    def backends_status(self) -> list[dict]:
        out = []
        for b in self.backends.values():
            ok, why = b.available()
            out.append({"name": b.name, "label": b.label, "available": ok, "how": why})
        return out

    def chats(self) -> list[dict]:
        rows = self.store.q("SELECT * FROM chats ORDER BY updated_at DESC")
        running = {r["chat_id"] for r in self.store.q("SELECT chat_id FROM runs WHERE status='running'")}
        for r in rows:
            r["running"] = r["id"] in running
        return rows

    def create_chat(self, backend: str) -> dict:
        if backend not in self.backends:
            raise ValueError(f"세션 종류: {sorted(self.backends)}")
        now = time.time()
        cid = self.store.x("INSERT INTO chats (title, backend, created_at, updated_at) VALUES (?,?,?,?)",
                           ("새 대화", backend, now, now))
        return self._chat(cid)

    def _chat(self, cid: int) -> dict:
        r = self.store.q("SELECT * FROM chats WHERE id=?", (cid,))
        if not r:
            raise NotFound(str(cid))
        return r[0]

    def events(self, cid: int, after: int = 0) -> list[dict]:
        self._chat(cid)
        return self.store.events(cid, after)

    def _history(self, cid: int) -> list[dict]:
        hist: list[dict] = []
        for e in self.store.events(cid):
            if e["type"] == "user":
                hist.append({"role": "user", "content": e["data"]["text"]})
            elif e["type"] == "text":
                if hist and hist[-1]["role"] == "assistant":
                    hist[-1]["content"] += "\n" + e["data"]["text"]
                else:
                    hist.append({"role": "assistant", "content": e["data"]["text"]})
        return hist

    def send(self, cid: int, text: str, paper_id: str | None = None) -> dict:
        chat = self._chat(cid)
        text = (text or "").strip()
        if not text:
            raise ValueError("보낼 내용이 비어 있습니다")
        backend = self.backends.get(chat["backend"])
        if not backend:
            raise Unavailable(f"이 대화의 세션({chat['backend']})을 이 서버에서 쓸 수 없습니다")
        ok, why = backend.available()
        if not ok:
            raise Unavailable(why)
        paper = None
        if paper_id:
            p = L.scan_papers(self.root).get(paper_id)
            c = self.store.candidate(paper_id)
            paper = {"id": paper_id, "title": (p.title if p else (c or {}).get("title")) or ""}
        with self.lock:
            if cid in self.procs:
                raise Busy("이 대화는 아직 답하는 중입니다. 끝나거나 중지한 뒤 보내세요.")
            ctx = ChatCtx(session_id=chat["session_id"], history=self._history(cid), paper=paper)
            run_id = self.store.x("INSERT INTO runs (chat_id, status, started_at) VALUES (?,?,?)", (cid, "running", time.time()))
            if chat["title"] == "새 대화":
                self.store.x("UPDATE chats SET title=? WHERE id=?", (text[:40], cid))
            self.store.event(cid, run_id, "user", {"text": text, "paper": paper})
            proc = backend.start(ctx, text)
            self.procs[cid] = proc
        threading.Thread(target=self._run, args=(cid, run_id, proc), daemon=True).start()
        return {"run_id": run_id}

    def _run(self, cid: int, run_id: int, proc) -> None:
        status, cost, err = "done", None, None
        try:
            for ev in proc.events():
                t = ev.get("type")
                if t == "session":
                    self.store.x("UPDATE chats SET session_id=? WHERE id=?", (ev["session_id"], cid))
                    continue
                if t == "error":
                    status, err = "failed", ev.get("message")
                if t == "done":
                    cost = ev.get("cost")
                self.store.event(cid, run_id, t, {k: v for k, v in ev.items() if k != "type"})
        except Exception as e:  # 실행 스레드가 죽어도 화면에는 실패로 보이게
            status, err = "failed", f"실행 중 오류: {e}"
            self.store.event(cid, run_id, "error", {"message": err})
        finally:
            with self.lock:
                self.procs.pop(cid, None)
                if cid in self.canceled:
                    self.canceled.discard(cid)
                    status = "canceled"
            self.store.x("UPDATE runs SET status=?, ended_at=?, cost=?, error=? WHERE id=?",
                         (status, time.time(), cost, err, run_id))
            self.store.event(cid, run_id, "run_end", {"status": status, "cost": cost})

    def cancel(self, cid: int) -> dict:
        self._chat(cid)
        with self.lock:
            proc = self.procs.get(cid)
            if not proc:
                return {"canceled": False, "message": "진행 중인 답이 없습니다"}
            self.canceled.add(cid)
        proc.cancel()
        return {"canceled": True}

    # ── 로컬 LLM 이 쓰는 엔진 도구 ───────────────────────
    def local_tools(self) -> dict[str, Tool]:
        def list_library(status: str | None = None):
            ps = self.library()["papers"]
            if status:
                ps = [p for p in ps if p["status"] == status]
            return [{"id": p["id"], "title": p["title"][:80], "status": STATUSES[p["status"]],
                     "conclusion": p["conclusion"][:160]} for p in ps[:20]]

        def read_notes(id: str, offset: int = 0):
            f = L.paper_files(self.root, id)
            if not f["notes"]:
                return f"{id} 는 아직 정리(notes)가 없습니다."
            chunk = f["notes"][offset:offset + 2000]
            more = len(f["notes"]) > offset + 2000
            return chunk + (f"\n…(이어서: offset={offset + 2000}, 전체 {len(f['notes'])}자)" if more else "")

        def resolve_title(title: str):
            status, aid, found = R.resolve(title)
            return {"상태": status, "arxiv_id": aid, "찾은 제목": found}

        def list_candidates(limit: int = 10):
            return [{"id": c["id"], "title": (c["title"] or "")[:80], "신호": c["signals"]}
                    for c in self.candidates("signal")["items"][:limit]]

        def fetch_paper(id: str):
            return self.fetch_fn(id)

        return {
            "list_library": Tool(list_library, 'args {"status": "to_read|fetched|noted|applied|hold" 또는 생략} — 서재 목록과 결론 한 줄'),
            "read_notes": Tool(read_notes, 'args {"id": "arXiv id", "offset": 0} — 정리된 notes 를 2000자씩'),
            "resolve_title": Tool(resolve_title, 'args {"title": "논문 제목 또는 arXiv 링크"} — arXiv id 찾기'),
            "list_candidates": Tool(list_candidates, 'args {"limit": 10} — 후보함에서 신호 통과한 미판정 후보'),
            "fetch_paper": Tool(fetch_paper, 'args {"id": "arXiv id"} — 논문을 받아 서재에 넣기 (정리는 안 함)', writes=True),
        }


def _abstract_online(aid: str) -> str:
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://huggingface.co/api/papers/{aid}",
                                                           headers={"User-Agent": "paper_analyst/0.1"}), timeout=20) as r:
            s = json.loads(r.read()).get("summary")
            if s:
                return " ".join(s.split())
    except OSError:
        pass
    from paper_analyst import fetch as F
    try:
        return " ".join((F.fetch_meta(aid, None).get("abstract") or "").split())
    except Exception:  # 네트워크·형식 오류 — 화면은 "초록을 못 가져옴"으로
        return ""


def _fetch_paper(aid: str) -> dict:
    from paper_analyst import fetch as F
    return F.fetch_one(aid, parse=True, via="auto", layout_url=None, force=False)
