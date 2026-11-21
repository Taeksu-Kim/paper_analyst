"""README 용 화면 캡처 → docs/images/*.png

    python tools/screenshots.py

실제 서재의 공개 파일만 임시 폴더에 복사해 서버를 띄운다 (*.private.md·원문·대화 DB 는 복사하지 않는다 —
캡처에 개인 메모가 어떤 형태로도 나오지 않게). 대화 패널은 가짜 세션으로 짧은 예시 대화를 한 번 돌린다.
"""
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from paper_analyst.app import create_app  # noqa: E402

OUT = ROOT / "docs" / "images"
TMP = Path(tempfile.mkdtemp(prefix="paper_shots_"))
for d in (ROOT / "library" / "papers").iterdir():
    t = TMP / "library" / "papers" / d.name
    t.mkdir(parents=True)
    for f in ("meta.json", "notes.md"):
        if (d / f).exists():
            shutil.copy(d / f, t / f)
for sub in ("lists", "ideas", "library/candidates", "posts"):
    src = ROOT / sub
    if src.exists():
        shutil.copytree(src, TMP / sub, ignore=shutil.ignore_patterns("*.private.md"), dirs_exist_ok=True)
# 외부 평가는 날짜·인용 수만 (external.json 은 제3자 댓글 원문이 있어 git 제외 — '확인 시점' 줄에 쓰이는 값만 옮긴다)
for d in (ROOT / "library" / "papers").iterdir():
    if (d / "external.json").exists():
        e = json.loads((d / "external.json").read_text(encoding="utf-8"))
        slim = {"fetched_at": e.get("fetched_at"), "s2": {"citations": (e.get("s2") or {}).get("citations")}}
        (TMP / "library" / "papers" / d.name / "external.json").write_text(json.dumps(slim), encoding="utf-8")
assert not list(TMP.rglob("*.private.md")), "개인 메모가 복사됨"
# 캡처할 글 둘만 남긴다: 소개 글은 '게시 전'으로, LLMs Get Lost 는 '게시한 글'로 (계정 이름은 지운다)
KEEP = {"2026-11-15_paper-analyst-intro": "todo", "2026-11-15_llms-get-lost": "done"}
for p in (TMP / "posts").glob("*"):
    if p.name not in KEEP:
        shutil.rmtree(p)
        continue
    m = json.loads((p / "meta.json").read_text(encoding="utf-8"))
    m.pop("project_root", None)
    if KEEP[p.name] == "todo":
        m.pop("published", None)
    else:
        for v in (m.get("published") or {}).values():
            v["account"] = "내 계정"
    (p / "meta.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


class Proc:
    def __init__(self, ctx, text):
        self.ctx, self.text = ctx, text

    def events(self):
        yield {"type": "session", "session_id": "demo"}
        for i, (name, s) in enumerate([("Skill", "paper-read"), ("Bash", "python -m paper_analyst.fetch 2603.28052 --parse"),
                                       ("Bash", "python -m paper_analyst.enrich 2603.28052"),
                                       ("Read", "library/papers/2603.28052/parsed/paper.md"),
                                       ("WebSearch", '"Meta-Harness" review OR analysis OR criticism'),
                                       ("Write", "library/papers/2603.28052/notes.md")]):
            yield {"type": "tool", "id": str(i), "name": name, "summary": s}
            yield {"type": "tool_done", "id": str(i), "ok": True, "summary": ""}
        yield {"type": "text", "text": "**정리했습니다.** `library/papers/2603.28052/notes.md`\n- 결론: 요약 대신 실행 기록 원본을 주면 사람이 만든 최고 하네스를 넘는다\n- 외부 평가: 후속 논문 인용 문맥 8건, HN 글 1개\n- 연결: LLMs Get Lost(같은 방향)"}
        yield {"type": "done", "cost": 0.68}

    def cancel(self):
        pass


class Demo:
    name, label = "claude", "Claude Code"

    def available(self):
        return True, ""

    def start(self, ctx, text):
        return Proc(ctx, text)


class Off:
    name, label = "local", "로컬 LLM"

    def available(self):
        return False, "로컬 LLM 서버가 꺼져 있습니다."


class LI:   # 발행 캡처에서 '연결됨' 상태를 보이려는 가짜 (실제 게시는 하지 않음)
    def exchange_code(self, *a):
        return {}

    def userinfo(self, t):
        return {}

    def create_post(self, *a):
        raise RuntimeError("캡처 중 게시 안 함")


CFG = TMP / "cfg"
(CFG / "tokens").mkdir(parents=True, exist_ok=True)
(TMP / "data").mkdir(parents=True, exist_ok=True)
(CFG / "linkedin_app.json").write_text(json.dumps({"client_id": "demo", "client_secret": "demo"}))
(CFG / "tokens" / "paper_analyst-linkedin.json").write_text(json.dumps({"access_token": "demo", "expires_at": time.time() + 86400 * 59,
                                                              "sub": "demo", "name": "내 LinkedIn 계정"}))
app = create_app(TMP, backends={"claude": Demo(), "local": Off()}, db_path=TMP / "data" / "shots.db",
                 abstract_fn=lambda a: "", linkedin=LI(), config_dir=CFG)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
URL = f"http://127.0.0.1:{PORT}"
threading.Thread(target=uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")).run,
                 daemon=True).start()


def call(path, body=None, method=None):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


for _ in range(40):
    try:
        call("/api/status")
        break
    except Exception:
        time.sleep(0.25)
# 서재에 실제 관계를 몇 개 (notes 에서 서로 언급한 논문들)
call("/api/papers/2603.28052/tags", {"tags": ["agent harness", "agent skills"]}, "PUT")
call("/api/papers/2505.06120/tags", {"tags": ["multi-turn conversation", "agent harness"]}, "PUT")
call("/api/papers/2605.15184/tags", {"tags": ["agent harness", "retrieval augmented generation"]}, "PUT")
call("/api/links", {"src": "2603.28052", "dst": "2505.06120", "kind": "agrees", "note": "초반 잘못된 가정의 연쇄"})
call("/api/links", {"src": "2605.15184", "dst": "2603.28052", "kind": "agrees", "note": "하네스가 성능을 좌우"})
cid = call("/api/chats", {"backend": "claude"})["id"]
call(f"/api/chats/{cid}/messages", {"text": "이 논문 paper-read 로 정리해줘", "paper_id": "2603.28052"})
time.sleep(1.5)

FALLBACK = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    try:
        b = p.chromium.launch()
    except Exception:
        b = p.chromium.launch(executable_path=str(FALLBACK[-1]))
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    ctx.add_init_script("localStorage.setItem('pa.cmp', JSON.stringify(['2603.28052','2505.06120'])); localStorage.setItem('pa.chatShown', '1')")   # README 캡처는 대화 칸을 펼친 채로
    page = ctx.new_page()
    page.goto(URL + "/")
    page.wait_for_selector("#todo")               # 첫 화면 = 책상 (할 일 더미 + 결론 카드 서랍)
    page.wait_for_selector(".msg.bot")
    time.sleep(0.3)
    page.screenshot(path=str(OUT / "desk.png"))
    page.click("#tab-lib")
    page.click("#lib-list button[data-paper='2603.28052']")
    page.wait_for_selector(".links li")
    page.screenshot(path=str(OUT / "library.png"))
    page.click("#tab-cmp")
    page.wait_for_selector("table.cmp")
    page.screenshot(path=str(OUT / "compare.png"))
    page.click("#tab-cand")
    page.wait_for_selector(".cand")
    time.sleep(0.3)
    page.screenshot(path=str(OUT / "candidates.png"))
    page.click("#tab-pub")
    page.wait_for_selector(".preview-plain")
    page.click("#pub-done > summary")
    time.sleep(0.2)
    page.screenshot(path=str(OUT / "publish.png"))
    b.close()
for f in sorted(OUT.glob("*.png")):
    print(f.relative_to(ROOT), f.stat().st_size // 1024, "KB")
