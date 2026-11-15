"""제품 API 진입점 테스트 — 모델·네트워크만 가짜. python -m pytest tests -q"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paper_analyst.app import create_app
from paper_analyst.chat import ChatCtx


def make_root(tmp: Path) -> Path:
    d = tmp / "library" / "papers" / "2603.28052"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"title": "Meta-Harness", "published": "2026-03-30", "abstract": "abs"}))
    (d / "notes.md").write_text("# Meta-Harness\n\n## 결론\n**원본 기록을 주면 더 낫다.**\n- **가져갈 것:** 원본 trace\n"
                                "- **믿어도 되는 결과:** 표 3\n\n## 관심 주제와의 연결\n- **agent harness:** 직접. RAG 도.\n"
                                "- LLMs Corrupt 와 같은 방향\n")
    (d / "notes.private.md").write_text("# 개인\n- 내 작업 연결\n")
    d2 = tmp / "library" / "papers" / "2604.15597"
    d2.mkdir(parents=True)
    (d2 / "meta.json").write_text(json.dumps({"title": "LLMs Corrupt"}))
    cand = tmp / "library" / "candidates"
    cand.mkdir(parents=True)
    rows = [{"id": "2610.14162", "title": "Next-Concept", "src": ["hf", "hn"], "stars": 1872, "hn_points": 181, "signals": ["stars", "hn"]},
            {"id": "2610.00906", "title": "ActiveSaddler", "src": ["hf"], "upvotes": 53, "signals": []},
            {"id": "2603.28052", "title": "Meta-Harness", "src": ["s2"], "cit": 387, "signals": ["cit"]}]
    (cand / "x.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (tmp / "lists").mkdir()
    (tmp / "lists" / "a.md").write_text("# 목록 A\n| x | y |\n|---|---|\n| 1 | 2 |\n")
    (tmp / "lists" / "b.private.md").write_text("# 비공개 목록\n")
    return tmp


class FakeProc:
    def __init__(self, backend, ctx: ChatCtx, text: str):
        self.b, self.ctx, self.text, self.stop = backend, ctx, text, threading.Event()

    def events(self):
        sid = self.ctx.session_id or f"s-{len(self.b.starts)}"
        yield {"type": "session", "session_id": sid}
        if "느리게" in self.text:
            for _ in range(100):
                if self.stop.is_set():
                    return
                time.sleep(0.02)
        yield {"type": "tool", "id": "t1", "name": "Write", "summary": "library/papers/2604.15597/notes.md"}
        (self.b.root / "library" / "papers" / "2604.15597" / "notes.md").write_text("## 결론\n**새로 정리됨.**\n")
        yield {"type": "tool_done", "id": "t1", "ok": True, "summary": ""}
        yield {"type": "library_changed"}
        yield {"type": "text", "text": f"답: {self.text}"}
        yield {"type": "done", "cost": 0.01}

    def cancel(self):
        self.stop.set()


class FakeBackend:
    def __init__(self, name, root, ok=True):
        self.name, self.label, self.root, self.ok, self.starts = name, name, root, ok, []

    def available(self):
        return (True, "") if self.ok else (False, "꺼져 있음 — 켜는 법")

    def start(self, ctx, text):
        self.starts.append((ctx.session_id, text, ctx.paper, list(ctx.history)))
        return FakeProc(self, ctx, text)


@pytest.fixture
def env(tmp_path):
    root = make_root(tmp_path)
    calls = []
    backends = {"claude": FakeBackend("claude", root), "local": FakeBackend("local", root, ok=False)}
    mk = lambda: TestClient(create_app(root, backends=backends, db_path=root / "data" / "t.db",
                                       abstract_fn=lambda a: calls.append(a) or f"초록 {a}",
                                       topics=["agent harness", "retrieval augmented generation", "LLM serving"]))
    return root, backends, calls, mk


def wait_idle(c, cid, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if not next(x for x in c.get("/api/chats").json() if x["id"] == cid)["running"]:
            return c.get(f"/api/chats/{cid}/events").json()
        time.sleep(0.05)
    raise AssertionError("실행이 끝나지 않음")


def test_library_and_status(env):
    root, _, _, mk = env
    c = mk()
    lib = c.get("/api/library").json()
    by = {p["id"]: p for p in lib["papers"]}
    assert by["2603.28052"]["status"] == "noted" and by["2603.28052"]["conclusion"] == "원본 기록을 주면 더 낫다."
    assert by["2604.15597"]["status"] == "fetched"
    assert {d["name"] for d in lib["docs"]} == {"a", "b.private"}
    p = c.get("/api/papers/2603.28052").json()
    assert "<strong>" in p["notes_html"] and "내 작업 연결" in p["private_html"]
    assert c.put("/api/papers/2603.28052/status", json={"status": "applied"}).json()["status"] == "applied"
    assert c.put("/api/papers/2603.28052/status", json={"status": "noted"}).status_code == 400   # 파일 기준 상태는 못 고름
    assert c.put("/api/papers/2603.28052/status", json={"status": None}).json()["status"] == "noted"
    assert c.get("/api/papers/9999.99999").status_code == 404
    assert "<table>" in c.get("/api/docs/lists/a").json()["html"]
    assert c.get("/api/docs/lists/..%2Fsecret").status_code == 404


def test_candidates(env):
    _, _, calls, mk = env
    c = mk()
    r = c.get("/api/candidates").json()
    assert [x["id"] for x in r["items"]] == ["2610.14162"]          # 서재에 있는 2603.28052 는 빠짐
    assert r["counts"] == {"signal": 1, "all": 2, "decided": 0}
    c.get("/api/candidates").json()                                   # 두 번 가져와도 중복 없음
    assert c.get("/api/candidates?view=all").json()["counts"]["all"] == 2
    assert c.get("/api/candidates/2610.14162/abstract").json()["abstract"] == "초록 2610.14162"
    c.get("/api/candidates/2610.14162/abstract")
    assert calls == ["2610.14162"]                                    # 캐시
    assert c.put("/api/candidates/2610.14162/decision", json={"decision": "read"}).status_code == 200
    lib = {p["id"]: p for p in c.get("/api/library").json()["papers"]}
    assert lib["2610.14162"]["status"] == "to_read"
    assert c.get("/api/candidates").json()["counts"]["signal"] == 0
    assert c.put("/api/candidates/2610.14162/decision", json={"decision": "bad"}).status_code == 400
    assert c.put("/api/candidates/0000.00000/decision", json={"decision": "read"}).status_code == 404


def test_chat_two_turns_busy_cancel_restart(env):
    root, backends, _, mk = env
    c = mk()
    cid = c.post("/api/chats", json={"backend": "claude"}).json()["id"]
    assert c.post(f"/api/chats/{cid}/messages", json={"text": "  "}).status_code == 400
    assert c.post(f"/api/chats/{cid}/messages", json={"text": "정리해줘", "paper_id": "2604.15597"}).status_code == 202
    evs = wait_idle(c, cid)
    types = [e["type"] for e in evs]
    assert types == ["user", "tool", "tool_done", "library_changed", "text", "done", "run_end"]
    assert {p["id"]: p for p in c.get("/api/library").json()["papers"]}["2604.15597"]["status"] == "noted"
    # 2턴: 같은 세션 이어감 + 이전 기록
    c.post(f"/api/chats/{cid}/messages", json={"text": "다음"})
    wait_idle(c, cid)
    s = backends["claude"].starts
    assert s[0][0] is None and s[0][2]["title"] == "LLMs Corrupt" and s[1][0] == "s-1"
    assert [h["role"] for h in s[1][3]] == ["user", "assistant"]
    assert c.get("/api/chats").json()[0]["title"] == "정리해줘"
    # 중복 전송 → 409, 중지
    c.post(f"/api/chats/{cid}/messages", json={"text": "느리게 해줘"})
    assert c.post(f"/api/chats/{cid}/messages", json={"text": "또"}).status_code == 409
    assert c.post(f"/api/chats/{cid}/cancel").json()["canceled"] is True
    evs = wait_idle(c, cid)
    assert evs[-1]["type"] == "run_end" and evs[-1]["data"]["status"] == "canceled"
    assert c.post(f"/api/chats/{cid}/cancel").json()["canceled"] is False
    # 재시작 중 끊긴 실행 + 재시작 후 같은 대화 이어가기
    c.post(f"/api/chats/{cid}/messages", json={"text": "느리게 다시"})
    c2 = mk()   # 같은 DB 로 새 서버
    evs = c2.get(f"/api/chats/{cid}/events").json()
    assert any(e["type"] == "run_end" and e["data"]["status"] == "interrupted" for e in evs)
    wait_idle(c, cid)  # 원래 스레드 정리
    assert c2.post(f"/api/chats/{cid}/messages", json={"text": "이어서"}).status_code == 202
    wait_idle(c2, cid)
    assert backends["claude"].starts[-1][0] == "s-1"


def test_backend_unavailable_and_stream(env):
    _, _, _, mk = env
    c = mk()
    st = {b["name"]: b for b in c.get("/api/status").json()["backends"]}
    assert st["claude"]["available"] and not st["local"]["available"] and st["local"]["how"]
    cid = c.post("/api/chats", json={"backend": "local"}).json()["id"]
    r = c.post(f"/api/chats/{cid}/messages", json={"text": "안녕"})
    assert r.status_code == 503 and "켜는 법" in r.json()["detail"]
    assert c.post("/api/chats", json={"backend": "nope"}).status_code == 400
    assert c.get("/api/chats/999/events").status_code == 404


def test_library_v2_tags_links_memo_compare(env):
    root, _, _, mk = env
    c = mk()
    p = c.get("/api/papers/2603.28052").json()
    assert p["suggest_tags"] == ["agent harness", "retrieval augmented generation"]     # 약어 RAG 도 잡음
    assert [s["id"] for s in p["suggest_links"]] == ["2604.15597"]
    # 태그: 공백 정리·중복 제거, 제안에서 빠짐, 서재 집계
    assert c.put("/api/papers/2603.28052/tags", json={"tags": [" agent  harness", "agent harness", "", "내 태그"]}).json()["tags"] == ["agent harness", "내 태그"]
    assert c.get("/api/papers/2603.28052").json()["suggest_tags"] == ["retrieval augmented generation"]
    assert c.get("/api/library").json()["tags"] == {"agent harness": 1, "내 태그": 1}
    assert c.put("/api/papers/0000.00000/tags", json={"tags": ["x"]}).status_code == 404
    # 연결: 추가 → 양쪽에서 보임, 제안에서 빠짐, 중복·자기 자신·잘못된 종류 거부, 삭제
    r = c.post("/api/links", json={"src": "2603.28052", "dst": "2604.15597", "kind": "agrees", "note": "원본 보존"})
    assert r.status_code == 200
    lid = r.json()["id"]
    assert c.get("/api/papers/2603.28052").json()["suggest_links"] == []
    back = c.get("/api/papers/2604.15597").json()["links"]
    assert back[0]["direction"] == "in" and back[0]["other"] == "2603.28052" and back[0]["kind_name"] == "같은 방향"
    assert c.post("/api/links", json={"src": "2604.15597", "dst": "2603.28052", "kind": "related"}).status_code == 400
    assert c.post("/api/links", json={"src": "2603.28052", "dst": "2603.28052", "kind": "related"}).status_code == 400
    assert c.post("/api/links", json={"src": "2603.28052", "dst": "2604.15597", "kind": "nope"}).status_code == 400
    assert c.post("/api/links", json={"src": "2603.28052", "dst": "9999.99999", "kind": "related"}).status_code == 404
    assert c.delete(f"/api/links/{lid}").status_code == 200 and c.delete(f"/api/links/{lid}").status_code == 404
    # 메모: 파일로 저장(git 제외 이름), 비우면 삭제, 받지 않은 논문은 거부
    assert c.put("/api/papers/2603.28052/memo", json={"text": "내 생각\n- 시험해 볼 것"}).status_code == 200
    assert (root / "library/papers/2603.28052/memo.private.md").read_text() == "내 생각\n- 시험해 볼 것\n"
    assert c.get("/api/papers/2603.28052").json()["memo"].startswith("내 생각")
    c.put("/api/papers/2603.28052/memo", json={"text": "   "})
    assert not (root / "library/papers/2603.28052/memo.private.md").exists()
    c.get("/api/candidates")
    c.put("/api/candidates/2610.14162/decision", json={"decision": "read"})
    assert c.put("/api/papers/2610.14162/memo", json={"text": "x"}).status_code == 400
    # 비교: 결론 항목 분해, 같은 id 두 번은 한 번, 없는 id 404
    cmp = c.get("/api/compare?ids=2603.28052,2604.15597,2603.28052").json()
    assert [x["id"] for x in cmp] == ["2603.28052", "2604.15597"]
    assert [x["label"] for x in cmp[0]["parts"]] == ["가져갈 것", "믿어도 되는 결과"] and cmp[1]["parts"] == []
    assert c.get("/api/compare?ids=2603.28052,9999.99999").status_code == 404


def test_posts(env):
    root, _, _, mk = env
    c = mk()
    assert c.get("/api/posts").json() == []
    d = root / "posts" / "2026-11-16_judge"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"title": "판정기 고르기", "sources": ["2603.28052"], "created": "2026-11-16"}))
    (d / "linkedin.md").write_text("**판정기는 정확도 한 숫자로 고르면 안 됩니다.**\n\n- 순서 바꿈 강건성\n- 누락 탐지\n\n내 작업 연결 관련 문장입니다 여기서부터\n#LLM")
    (d / "blog.md").write_text("# 판정기\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    (root / "library/papers/2603.28052/notes.private.md").write_text("# 개인\n- 내 작업 연결 관련 문장입니다 여기서부터 비밀\n")
    lst = c.get("/api/posts").json()
    assert [x["slug"] for x in lst] == ["2026-11-16_judge"] and lst[0]["has"] == ["linkedin.md", "blog.md"]
    p = c.get("/api/posts/2026-11-16_judge").json()
    li = p["linkedin"]
    assert li["plain"].startswith("판정기는 정확도") and "• 순서 바꿈" in li["plain"] and "**" not in li["plain"]
    assert li["plain"].rstrip().endswith("#LLM")                                            # 해시태그는 제목이 아님
    assert [h["line"] for h in li["check"]["private_hits"]] == [6]                       # 개인 메모 문장 겹침
    assert li["check"]["private_hits"][0]["source"].endswith("notes.private.md")
    assert not li["check"]["over_limit"] and li["check"]["chars"] < 200
    assert "<table>" in p["blog"]["html"] and p["blog"]["check"]["private_hits"] == []
    (d / "linkedin.md").write_text("가" * 3100)
    assert c.get("/api/posts/2026-11-16_judge").json()["linkedin"]["check"]["over_limit"] is True
    assert c.get("/api/posts/없음").status_code == 404
    assert c.get("/api/posts/..%2F..%2Fetc").status_code == 404


class FakeLinkedIn:
    def __init__(self):
        self.posts, self.fail = [], None

    def exchange_code(self, code, redirect_uri, client_id, client_secret):
        assert code == "good-code" and client_id == "cid" and redirect_uri.endswith("/api/linkedin/callback")
        return {"access_token": "tok", "expires_in": 5184000}

    def userinfo(self, access_token):
        return {"sub": "abc123", "name": "테스트 계정"}

    def create_post(self, access_token, author_urn, text):
        from paper_analyst.linkedin import LinkedInError
        if self.fail:
            raise LinkedInError("거부", self.fail)
        self.posts.append((author_urn, text))
        return f"urn:li:share:{len(self.posts)}"


def test_linkedin_publish(tmp_path):
    import os, stat, urllib.parse
    root = make_root(tmp_path)
    fake = FakeLinkedIn()
    c = TestClient(create_app(root, backends={}, db_path=root / "data" / "t.db", topics=[], linkedin=fake))
    assert c.get("/api/linkedin").json()["configured"] is False
    assert c.get("/api/linkedin/connect", follow_redirects=False).status_code == 503
    (root / "data" / "linkedin_app.json").write_text(json.dumps({"client_id": "cid", "client_secret": "sec"}))
    r = c.get("/api/linkedin/connect", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].startswith("https://www.linkedin.com/oauth/v2/authorization?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    assert q["scope"] == ["openid profile w_member_social"] and q["redirect_uri"][0].endswith("/api/linkedin/callback")
    assert c.get("/api/linkedin/callback?code=good-code&state=forged").status_code == 400          # 위조 state
    assert c.get("/api/linkedin/callback?error=user_cancelled_login").status_code == 400
    assert c.get(f"/api/linkedin/callback?code=good-code&state={q['state'][0]}").status_code == 200
    assert c.get(f"/api/linkedin/callback?code=good-code&state={q['state'][0]}").status_code == 400  # 같은 state 재사용
    st = c.get("/api/linkedin").json()
    assert st["connected"] and st["name"] == "테스트 계정"
    tf = root / "data" / "linkedin_token.json"
    assert stat.S_IMODE(os.stat(tf).st_mode) == 0o600
    # 초안: 개인 메모 겹침 → 거부
    d = root / "posts" / "p1"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"title": "t"}))
    (root / "library/papers/2603.28052/notes.private.md").write_text("- 회사 일과 연결되는 아주 비밀스러운 문장입니다\n")
    (d / "linkedin.md").write_text("**첫 줄 훅입니다.**\n\n회사 일과 연결되는 아주 비밀스러운 문장입니다\n#LLM")
    sha = c.get("/api/posts/p1").json()["linkedin"]["sha"]
    assert c.post("/api/posts/p1/linkedin", json={"sha": sha}).status_code == 409 and fake.posts == []
    (d / "linkedin.md").write_text("**첫 줄 훅입니다.**\n\n- 항목 하나\n#LLM")
    assert c.post("/api/posts/p1/linkedin", json={"sha": sha}).status_code == 409                  # 미리보기와 다름
    sha = c.get("/api/posts/p1").json()["linkedin"]["sha"]
    r = c.post("/api/posts/p1/linkedin", json={"sha": sha})
    assert r.status_code == 200 and r.json()["url"] == "https://www.linkedin.com/feed/update/urn:li:share:1/"
    assert fake.posts == [("urn:li:person:abc123", "첫 줄 훅입니다.\n\n• 항목 하나\n#LLM")]
    assert c.get("/api/posts/p1").json()["published"]["linkedin"]["urn"] == "urn:li:share:1"
    assert c.post("/api/posts/p1/linkedin", json={"sha": sha}).status_code == 409 and len(fake.posts) == 1   # 두 번 X
    assert c.post("/api/posts/none/linkedin", json={"sha": "x"}).status_code == 404
    # LinkedIn 이 401 → 토큰 지우고 다시 연결 안내
    d2 = root / "posts" / "p2"
    d2.mkdir()
    (d2 / "linkedin.md").write_text("두 번째 글")
    fake.fail = 401
    sha2 = c.get("/api/posts/p2").json()["linkedin"]["sha"]
    r = c.post("/api/posts/p2/linkedin", json={"sha": sha2})
    assert r.status_code == 503 and "다시 연결" in r.json()["detail"] and not tf.exists()
    # 만료된 토큰
    tf.write_text(json.dumps({"access_token": "t", "expires_at": 1, "sub": "s", "name": "n"}))
    assert c.get("/api/linkedin").json()["expired"] is True
    assert c.post("/api/posts/p2/linkedin", json={"sha": sha2}).status_code == 503
    assert c.post("/api/linkedin/disconnect").json()["connected"] is False and not tf.exists()
