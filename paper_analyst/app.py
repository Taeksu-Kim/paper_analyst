"""제품 API + 화면. `create_app(root, *, backends, abstract_fn, fetch_fn)` — 테스트는 가짜를 주입한다."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from paper_analyst.chat import ChatBackend
from paper_analyst.service import Busy, NotFound, Service, Unavailable

STATIC = Path(__file__).parent / "static"


class StatusIn(BaseModel):
    status: str | None


class DecisionIn(BaseModel):
    decision: str | None


class ChatIn(BaseModel):
    backend: str


class MessageIn(BaseModel):
    text: str
    paper_id: str | None = None


def create_app(root: Path, *, backends: dict[str, ChatBackend] | None = None, db_path: Path | None = None,
               abstract_fn: Callable[[str], str] | None = None, fetch_fn: Callable[[str], dict] | None = None) -> FastAPI:
    svc = Service(root, db_path or root / "data" / "paper_analyst.db", backends, abstract_fn, fetch_fn)
    if backends is None:   # 실제 서버: 두 세션 모두 (꺼져 있으면 화면에서 잠김)
        from paper_analyst.chat import ClaudeBackend, LocalBackend
        svc.backends = {"claude": ClaudeBackend(root), "local": LocalBackend(svc.local_tools())}
    app = FastAPI(title="paper_analyst")
    app.state.svc = svc

    def guard(fn, *a):
        try:
            return fn(*a)
        except NotFound as e:
            raise HTTPException(404, f"찾을 수 없음: {e}") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Busy as e:
            raise HTTPException(409, str(e)) from e
        except Unavailable as e:
            raise HTTPException(503, str(e)) from e

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        from paper_analyst import profile as P
        try:
            prof = P.load()
            p = {"name": prof["name"], "description": prof.get("description", ""), "language": prof.get("reader", {}).get("language", "ko")}
        except SystemExit as e:
            p = {"name": None, "error": str(e)}
        return {"profile": p, "backends": svc.backends_status()}

    @app.get("/api/library")
    def library():
        return svc.library()

    @app.get("/api/papers/{aid}")
    def paper(aid: str):
        return guard(svc.paper, aid)

    @app.put("/api/papers/{aid}/status")
    def set_status(aid: str, body: StatusIn):
        return guard(svc.set_status, aid, body.status)

    @app.get("/api/docs/{kind}/{name}")
    def doc(kind: str, name: str):
        return guard(svc.doc, kind, name)

    @app.get("/api/candidates")
    def candidates(view: str = "signal"):
        return svc.candidates(view)

    @app.get("/api/candidates/{aid}/abstract")
    def abstract(aid: str):
        return {"id": aid, "abstract": guard(svc.abstract, aid)}

    @app.put("/api/candidates/{aid}/decision")
    def decide(aid: str, body: DecisionIn):
        return guard(svc.decide, aid, body.decision)

    @app.get("/api/chats")
    def chats():
        return svc.chats()

    @app.post("/api/chats")
    def create_chat(body: ChatIn):
        return guard(svc.create_chat, body.backend)

    @app.post("/api/chats/{cid}/messages", status_code=202)
    def send(cid: int, body: MessageIn):
        return guard(svc.send, cid, body.text, body.paper_id)

    @app.post("/api/chats/{cid}/cancel")
    def cancel(cid: int):
        return guard(svc.cancel, cid)

    @app.get("/api/chats/{cid}/events")
    def events(cid: int, after: int = 0):
        return guard(svc.events, cid, after)

    @app.get("/api/chats/{cid}/stream")
    async def stream(cid: int, request: Request, after: int = 0):
        guard(svc.events, cid, 0)
        last = int(request.headers.get("last-event-id") or after)

        async def gen():
            nonlocal last
            idle = 0
            while not await request.is_disconnected():
                evs = svc.events(cid, last)
                for e in evs:
                    last = e["id"]
                    yield f"id: {e['id']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                idle = 0 if evs else idle + 1
                if idle and idle % 30 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.4)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app
