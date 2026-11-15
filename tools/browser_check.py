"""브라우저 점검: 실제 서재 복사본 + 가짜 세션으로 화면을 Chromium(headless)에서 눌러 본다.

    python tools/browser_check.py            # 임시 폴더·포트로 서버를 띄우고 끝나면 정리 (실제 library/·data/ 는 안 건드림)

스크린샷: /tmp/paper_ui_*/shot_*.png
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

TMP = Path(tempfile.mkdtemp(prefix="paper_ui_"))
# 실제 서재 복사본 (메타·notes·개인 메모·목록·후보만 — 원문은 빼고)
for d in (ROOT / "library" / "papers").iterdir():
    t = TMP / "library" / "papers" / d.name
    t.mkdir(parents=True)
    for f in ("meta.json", "notes.md", "notes.private.md"):
        if (d / f).exists():
            shutil.copy(d / f, t / f)
for sub in ("lists", "ideas", "library/candidates"):
    if (ROOT / sub).exists():
        shutil.copytree(ROOT / sub, TMP / sub, dirs_exist_ok=True)
TARGET = "2604.12374"     # notes 없는 논문 — 가짜 세션이 정리한다
# 발행 초안 하나 (개인 메모 문장을 일부러 한 줄 섞어 경고가 나오는지 본다)
_pd = TMP / "posts" / "2026-11-16_judge"
_pd.mkdir(parents=True)
(_pd / "meta.json").write_text(json.dumps({"title": "판정기는 한 숫자로 고르면 안 된다", "sources": ["2603.28052"], "created": "2026-11-16"},
                                          ensure_ascii=False))
(_pd / "linkedin.md").write_text("**LLM 판정기를 정확도 한 숫자로 고르면 안 됩니다.** 실패 유형별로 쪼개 봐야 합니다.\n\n"
                                 "- 순서 바꿈 강건성은 양쪽 순서 모두 정답일 때만\n- 누락형 오류는 따로 잰다\n\n"
                                 "이 줄은 비공개 메모에서 옮겨 온 문장이라 경고가 떠야 합니다\n\n출처: https://arxiv.org/abs/2610.09229\n#LLM #평가")
(_pd / "blog.md").write_text("# 판정기 고르기\n\n## 논문이 보인 것\n\n| 조건 | 결과 |\n|---|---|\n| 순서 | 강건성 0.87 |\n")
(TMP / "library/papers/2603.28052/notes.private.md").write_text("# 개인\n- 이 줄은 비공개 메모에서 옮겨 온 문장이라 경고가 떠야 합니다 (원문)\n")
N_NOTED = sum(1 for d in (TMP / "library" / "papers").iterdir() if (d / "notes.md").exists())
N_ALL = sum(1 for d in (TMP / "library" / "papers").iterdir())
assert not (TMP / "library" / "papers" / TARGET / "notes.md").exists()


class FakeProc:
    def __init__(self, ctx, text):
        self.ctx, self.text, self.stop = ctx, text, threading.Event()

    def events(self):
        yield {"type": "session", "session_id": self.ctx.session_id or "fake-session"}
        yield {"type": "tool", "id": "a", "name": "Bash", "summary": f"python -m paper_analyst.enrich {TARGET}"}
        for _ in range(60 if "느리게" in self.text else 15):
            if self.stop.is_set():
                return
            time.sleep(0.05)
        yield {"type": "tool_done", "id": "a", "ok": True, "summary": ""}
        if self.ctx.paper:
            yield {"type": "tool", "id": "b", "name": "Write", "summary": f"library/papers/{self.ctx.paper['id']}/notes.md"}
            (TMP / "library" / "papers" / self.ctx.paper["id"] / "notes.md").write_text(
                f"# {self.ctx.paper['title']}\n\n## 결론\n**가짜 세션이 쓴 결론 — 하이브리드 MoE 로 처리량을 높였다.**\n\n## 한 줄 요약\n테스트\n")
            yield {"type": "tool_done", "id": "b", "ok": True, "summary": ""}
            yield {"type": "library_changed"}
        yield {"type": "tool", "id": "c", "name": "Bash", "summary": "rm -rf /"}
        yield {"type": "tool_done", "id": "c", "ok": False, "summary": "This command requires approval"}
        yield {"type": "text", "text": f"**정리했습니다.** `library/papers/{TARGET}/notes.md`\n- 결론 블록 작성\n- 외부 평가: HN 없음"}
        yield {"type": "done", "cost": 0.123, "denied": ["Bash"]}

    def cancel(self):
        self.stop.set()


class Fake:
    def __init__(self, name, label, ok, how=""):
        self.name, self.label, self.ok, self.how = name, label, ok, how

    def available(self):
        return self.ok, self.how

    def start(self, ctx, text):
        return FakeProc(ctx, text)


class FakeLI:
    def __init__(self):
        self.posts = []

    def exchange_code(self, *a):
        return {"access_token": "t", "expires_in": 5184000}

    def userinfo(self, tok):
        return {"sub": "s1", "name": "테스트 계정"}

    def create_post(self, tok, author, text):
        self.posts.append((author, text))
        return f"urn:li:share:{len(self.posts)}"


FAKE_LI = FakeLI()
backends = {"claude": Fake("claude", "Claude Code", True),
            "local": Fake("local", "로컬 LLM", False, "로컬 LLM 서버가 꺼져 있습니다. LLM.md §2 의 명령으로 켜세요.")}
CFG = TMP / "cfg"   # LinkedIn 키·토큰 (실제 ~/.config/side-projects 는 건드리지 않음)
(CFG / "tokens").mkdir(parents=True)
app = create_app(TMP, backends=backends, db_path=TMP / "data" / "ui.db", linkedin=FAKE_LI, config_dir=CFG,
                 abstract_fn=lambda a: f"{a} 의 초록입니다. 에이전트 하네스에 대한 연구." * 3)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
URL = f"http://127.0.0.1:{PORT}/"
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(40):
    try:
        urllib.request.urlopen(URL + "api/status", timeout=2)
        break
    except Exception:
        time.sleep(0.25)
FALLBACK = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
# 레이아웃·밀도 측정 스크립트는 상위 폴더의 ui-design 스킬에서 읽는다 (없으면 그 점검만 건너뜀)
UI_SKILL = ROOT.parent / ".claude" / "skills" / "ui-design"


def _snippet(rel: str, name: str) -> str | None:
    f = UI_SKILL / rel
    return f.read_text().split(f'{name} = """', 1)[1].split('"""', 1)[0] if f.exists() else None


LAYOUT_JS = _snippet("stages/6-verify.md", "LAYOUT_JS")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail else ""))


TEXT_JS = _snippet("topics/value-density.md", "TEXT_JS")


def basics(page, tag):
    page.evaluate("document.querySelector('#lib-list').scrollTop = 0")
    if TEXT_JS:
        d = page.evaluate(TEXT_JS)
        print(f"  밀도 [{tag}] 첫 화면 글자 {d['first_screen_chars']} · 블록 {d['text_blocks']} · 60자 넘는 블록 {len(d['long_blocks_over_60'])}")
    body = page.inner_text("body")
    bad = [w for w in ("undefined", "NaN", "null") if w in body]
    check(f"[{tag}] 깨진 값 없음", not bad, ",".join(bad))
    if not LAYOUT_JS:
        print(f"  [{tag}] 레이아웃 측정 건너뜀 (ui-design 스킬 없음: {UI_SKILL})")
        return
    lay = page.evaluate(LAYOUT_JS)
    check(f"[{tag}] 화면 밖 요소 없음", not lay["overflow"], "; ".join(lay["overflow"][:5]))
    check(f"[{tag}] 겹친 클릭 대상 없음", not lay["overlap"], "; ".join(lay["overlap"][:5]))
    if lay["small"]:
        print(f"  참고 [{tag}] 24px 미만 클릭 대상 {len(lay['small'])}개: " + "; ".join(lay["small"][:6]))


with sync_playwright() as p:
    try:
        b = p.chromium.launch()
    except Exception:
        b = p.chromium.launch(executable_path=str(FALLBACK[-1]))
    page = b.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    expected_4xx = []
    page.context.on("response", lambda r: r.status >= 400 and expected_4xx.append(f"{r.status} {r.url}"))

    page.goto(URL)
    page.wait_for_selector("button.concl")
    page.wait_for_function("document.querySelector('#cand-n').textContent.trim() !== ''")
    n_concl = page.locator("#main button.concl").count()
    check(f"첫 화면: 최근 결론 {N_NOTED}개", n_concl == N_NOTED, str(n_concl))
    check(f"서재: 정리됨 {N_NOTED} · 받음 {N_ALL - N_NOTED} 필터", f"정리됨 {N_NOTED}" in page.inner_text("#filters")
          and f"받음 {N_ALL - N_NOTED}" in page.inner_text("#filters"), page.inner_text("#filters").replace(chr(10), " "))
    check("서재: 목록·아이디어 묶음 보임", "목록" in page.inner_text("#lib-list") and "아이디어" in page.inner_text("#lib-list"))
    check("후보함 탭 숫자", page.inner_text("#cand-n").strip().isdigit(), page.inner_text("#cand-n"))
    check("대화 없음 안내 + 입력 잠김", "새 대화" in page.inner_text("#msgs") and page.is_disabled("#input"))
    page.screenshot(path=str(TMP / "shot_1440_home.png"))

    # 논문 열기
    page.click("#main button.concl[data-paper='2605.15184']")
    page.wait_for_selector("article .concl")
    check("논문: notes 안 제목·결론 문장 중복 없음", page.locator("#notes > h1").count() == 0
          and page.inner_text("#notes").count(page.inner_text("article .concl .v")[:30]) == 0)
    check("논문: 결론 블록 + notes 렌더 (표)", page.locator("article .md table").count() >= 1)
    has_priv = page.locator("details.private").count()
    page.screenshot(path=str(TMP / "shot_1440_paper.png"))
    page.evaluate("document.querySelector('#main').scrollTop = 900")
    page.screenshot(path=str(TMP / "shot_1440_paper_mid.png"))
    page.evaluate("document.querySelector('#main').scrollTop = 0")
    check("논문: 개인 메모 접힘", has_priv == 1 and not page.is_visible("details.private .md"))
    check("대화창: 보고 있는 논문 붙음", "함께 보낼 논문" in page.inner_text("#attach"))
    page.click("button[data-st='applied']")
    page.wait_for_function("document.querySelector('#filters').innerText.includes('적용함 1')")
    check("상태: 적용함으로 옮김", "적용함" in page.inner_text("article .bar"))
    page.click("button[data-st='']")
    page.wait_for_function("document.querySelector('#filters').innerText.includes('적용함 0')")
    check("상태: 되돌리기", True)

    # 후보함
    page.click("#tab-cand")
    page.wait_for_selector(".cand")
    n_sig = int(page.inner_text("#cand-n") or 0)
    first = page.locator(".cand button.t").first
    first_id = first.get_attribute("data-abs")
    first.click()
    page.wait_for_function(f"document.querySelector('.cand .abstract') && document.querySelector('.cand .abstract').innerText.includes('{first_id}')")
    check("후보: 초록 펼침", True)
    page.screenshot(path=str(TMP / "shot_1440_cand.png"))
    page.click(f"button[data-dec='read'][data-id='{first_id}']")
    page.wait_for_function(f"!document.querySelector(\"button[data-abs='{first_id}']\")")
    check("후보: 읽기로 판정 → 목록에서 빠짐", int(page.inner_text("#cand-n") or 0) == n_sig - 1)
    check("후보: 서재 '읽을 것'에 들어감", "읽을 것 1" in page.inner_text("#filters"))
    page.click("button[data-cv='decided']")
    page.wait_for_selector("button[data-dec='']")
    check("후보: 판정함 보기에 있음", first_id in page.inner_text("#main"))

    # v2: 태그·연결·내 메모·비교
    page.click("#tab-lib")
    page.click("button[data-paper='2603.28052']")
    page.wait_for_selector("button[data-tagadd]")
    sug = page.locator("button[data-tagadd]").all_inner_texts()
    check("태그 제안 (관심 주제와의 연결 기반)", any("agent harness" in x for x in sug), str(sug))
    page.click("button[data-tagadd='agent harness']")
    page.wait_for_selector(".tag button[data-tagdel='agent harness']")
    page.fill("#tag-in", "내 태그")
    page.press("#tag-in", "Enter")
    page.wait_for_selector(".tag button[data-tagdel='내 태그']")
    check("태그 직접 입력 + 서재 태그 필터 줄", "agent harness 1" in page.inner_text("#tagfilters") and "내 태그 1" in page.inner_text("#tagfilters"))
    page.click("button[data-tagdel='내 태그']")
    page.wait_for_function("!document.querySelector('#tagfilters').innerText.includes('내 태그')")
    page.click("button[data-tagf='agent harness']")
    n_items = page.locator("#lib-list button.item").count()
    check("태그로 서재 거르기 → 1편", n_items == 1, str(n_items))
    page.click("button[data-tagf='agent harness']")
    check("연결 제안: notes 에 나온 논문", page.locator("button[data-linkpre='2505.06120']").count() == 1)
    page.click("button[data-linkpre='2505.06120']")
    check("제안 누르면 연결 대상이 골라짐", page.input_value("#link-dst") == "2505.06120")
    page.select_option("#link-kind", "agrees")
    page.click("#link-add")
    page.wait_for_selector(".links button.go[data-paper='2505.06120']")
    check("연결 추가 → 제안에서 빠짐", page.locator("button[data-linkpre='2505.06120']").count() == 0)
    page.click("details.memo summary") if not page.is_visible("#memo") else None
    page.fill("#memo", "원본 trace 디렉터리 구조를 우리 평가에 시험")
    page.click("#memo-save")
    page.wait_for_function("document.querySelector('#memo-st').innerText.startsWith('저장됨')")
    check("내 메모 파일로 저장 (git 제외 이름)", (TMP / "library/papers/2603.28052/memo.private.md").exists())
    page.click("button[data-cmp='2603.28052']")
    page.wait_for_selector("#tab-cmp:not([hidden])")
    page.screenshot(path=str(TMP / "shot_1440_v2_paper.png"))
    page.click(".links button.go[data-paper='2505.06120']")
    page.wait_for_selector(".links li")
    check("상대 논문에서 역방향 연결 보임", "같은 방향" in page.inner_text(".links") and "Meta-Harness" in page.inner_text(".links"))
    page.click("button[data-cmp='2505.06120']")
    page.click("button[data-paper='2603.28052']")
    page.wait_for_selector("#memo")
    check("다시 열면 메모 유지", "원본 trace" in page.input_value("#memo"))
    page.click("#tab-cmp")
    page.wait_for_selector("table.cmp")
    cols = page.locator("table.cmp thead th").count() - 1
    rows = page.locator("table.cmp tbody tr").count()
    check("비교: 2편 × (판정 + 항목 4) 표", cols == 2 and rows >= 5, f"{cols}열 {rows}행")
    check("비교 탭 숫자", page.inner_text("#cmp-n") == "2")
    page.screenshot(path=str(TMP / "shot_1440_compare.png"))
    basics(page, "1440 비교")
    page.click("button[data-uncmp='2505.06120']")
    page.wait_for_function("document.querySelectorAll('table.cmp thead th').length === 2")
    check("비교에서 빼기", page.inner_text("#cmp-n") == "1")
    page.reload()
    page.wait_for_selector("button.concl")
    check("새로고침 후 비교 목록 유지 (브라우저 저장)", page.inner_text("#cmp-n") == "1")

    # 발행: 초안 보기·점검 경고·복사
    page.click("#tab-pub")
    page.wait_for_selector(".pub-body")
    check("발행: 초안 목록 + LinkedIn 미리보기", "판정기는 한 숫자로" in page.inner_text(".pub-head") and page.is_visible(".preview-plain"))
    check("발행: 개인 메모 겹침 경고", "개인 메모" in page.inner_text(".warn") and "1건" in page.inner_text(".warn"), page.inner_text(".warn")[:120] if page.locator(".warn").count() else "경고 없음")
    check("발행: '더 보기' 경계 표시", page.locator(".preview-plain .fold").count() == 1)
    check("발행: 기호 걷어낸 글자 (** 없음, • 목록)", "**" not in page.inner_text(".preview-plain") and "•" in page.inner_text(".preview-plain"))
    page.screenshot(path=str(TMP / "shot_1440_pub.png"))
    page.click("button[data-copy='linkedin']")
    page.wait_for_function("document.querySelector('#toast').innerText.includes('복사')")
    check("발행: 복사 알림", "복사했습니다" in page.inner_text("#toast"), page.inner_text("#toast"))
    page.click("button[data-ptab='blog']")
    page.wait_for_selector(".pub-body .md table")
    page.click("button[data-ptab='tistory']")
    page.wait_for_selector("pre.preview-src")
    check("발행: 티스토리 HTML 원본 (표 포함)", "<table>" in page.inner_text("pre.preview-src"))
    basics(page, "1440 발행")
    # LinkedIn: 키 없음 → 안내 / 연결됨 + 경고 → 게시 잠김 / 고친 뒤 확인 창 → 게시 → 게시됨
    page.click("button[data-ptab='linkedin']")
    page.wait_for_selector(".pubbar")
    check("LinkedIn: 앱 키 없음 안내", "앱 키가 필요" in page.inner_text(".pubbar"))
    (CFG / "linkedin_app.json").write_text(json.dumps({"client_id": "c", "client_secret": "s"}))
    page.click("#tab-lib"); page.click("#tab-pub")
    page.wait_for_selector(".pubbar a[href='/api/linkedin/connect']")
    check("LinkedIn: 연결 버튼", True)
    (CFG / "tokens" / "paper_analyst-linkedin.json").write_text(json.dumps({"access_token": "t", "expires_at": time.time() + 86400 * 50,
                                                                  "sub": "s1", "name": "테스트 계정"}))
    page.click("#tab-lib"); page.click("#tab-pub")
    page.wait_for_selector("#li-publish")
    check("LinkedIn: 점검 경고가 남으면 게시 잠김", page.is_disabled("#li-publish") and "테스트 계정" in page.inner_text(".pubbar"))
    (_pd / "linkedin.md").write_text("**LLM 판정기를 정확도 한 숫자로 고르면 안 됩니다.**\n\n- 순서 바꿈 강건성\n\n출처: https://arxiv.org/abs/2610.09229\n#LLM")
    page.click("#tab-lib"); page.click("#tab-pub")
    page.wait_for_selector("#li-publish:not([disabled])")
    page.click("#li-publish")
    page.wait_for_selector("#li-dialog[open]")
    check("LinkedIn: 확인 창 (계정·글자 수)", "테스트 계정" in page.inner_text("#li-dialog") and "자" in page.inner_text("#li-dialog-body"))
    page.screenshot(path=str(TMP / "shot_1440_li_confirm.png"))
    page.click("#li-cancel")
    check("LinkedIn: 취소하면 안 올라감", FAKE_LI.posts == [] and not page.is_visible("#li-dialog"))
    page.click("#li-publish")
    page.click("#li-confirm")
    page.wait_for_selector(".pubbar .done")
    check("LinkedIn: 게시됨 + 링크, 한 번만", len(FAKE_LI.posts) == 1 and page.locator(".pubbar a[href*='feed/update']").count() == 1
          and FAKE_LI.posts[0][1].startswith("LLM 판정기를") and "\n\n• 순서" in FAKE_LI.posts[0][1])
    page.screenshot(path=str(TMP / "shot_1440_li_done.png"))
    page.click("button[data-paper='2603.28052']") if page.locator(".pub-body button[data-paper='2603.28052']").count() else None
    page.wait_for_selector("article h1")
    check("재료 링크 → 논문 화면 + 글 초안 버튼", page.locator("button[data-ask*='paper-post']").count() == 1)

    # 대화: 새 대화 메뉴 (로컬 잠김)
    page.click(f"button[data-paper='{TARGET}']")
    page.wait_for_selector("article h1")
    check("받기만 한 논문: 정리 시키기 버튼", page.locator("button[data-ask]").first.inner_text() == "Claude 에게 정리 시키기")
    page.click("#new-chat")
    page.wait_for_selector(".menu")
    check("새 대화 메뉴: 로컬 LLM 잠김 + 켜는 법", page.is_disabled(".menu button[data-backend='local']")
          and "LLM.md" in page.inner_text(".menu"))
    page.screenshot(path=str(TMP / "shot_1440_menu.png"))
    page.click(".menu button[data-backend='claude']")
    page.wait_for_function("!document.querySelector('#input').disabled")
    check("Claude Code 대화 생성 + 세션 표시", "Claude Code" in page.inner_text("#sess") and "Anthropic" in page.inner_text("#sess"))

    # 한글 조합 중 Enter 는 보내지 않음
    page.fill("#input", "한글")
    page.evaluate("""() => document.querySelector('#input').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', isComposing:true, keyCode:229, bubbles:true}))""")
    time.sleep(0.4)
    check("IME 조합 중 Enter 무시", page.locator(".msg.user").count() == 0)
    page.fill("#input", "이 논문 정리해줘")
    page.press("#input", "Enter")
    page.wait_for_selector(".msg.user")
    check("보내기: 논문 맥락이 말풍선에", "Nemotron" in page.inner_text(".msg.user"))
    check("보내는 중: 입력 잠김 + 중지 버튼", page.is_disabled("#send") and page.is_visible("#stop"))
    page.wait_for_selector(".endline:has-text('비용')", timeout=10000)
    check("도구 줄: 완료·거부 표시", page.locator(".tool .st.ok").count() == 2 and page.locator(".tool .st.bad").count() == 1)
    check("거부 안내", "허용 목록 밖의 도구 1건" in page.inner_text("#msgs"))
    check("답: 마크다운(굵게·코드·목록)", page.locator(".msg.bot b").count() == 1 and page.locator(".msg.bot code").count() == 1
          and page.locator(".msg.bot li").count() == 2)
    page.wait_for_function(f"document.querySelector(\"button[data-paper='{TARGET}'] .new\") || document.querySelector('article .concl')")
    check("서재 실시간 반영: 결론이 논문 화면에", "가짜 세션이 쓴 결론" in page.inner_text("#main"))
    check(f"서재: 정리됨 {N_NOTED + 1}", f"정리됨 {N_NOTED + 1}" in page.inner_text("#filters"), page.inner_text("#filters").replace(chr(10), " "))
    page.screenshot(path=str(TMP / "shot_1440_chat.png"))
    basics(page, "1440")

    # 중지
    page.fill("#input", "느리게 다시")
    page.click("#send")
    page.wait_for_selector("#stop:visible")
    page.click("#stop")
    page.wait_for_selector(".endline:has-text('중지했습니다')", timeout=8000)
    check("중지 → '중지했습니다' + 입력 다시 열림", not page.is_disabled("#input"))

    # 새로고침 후 대화 이어짐
    page.reload()
    page.wait_for_selector(".msg.user")
    check("새로고침: 대화 기록 복원", page.locator(".msg.user").count() == 2 and "중지했습니다" in page.inner_text("#msgs"))
    sid = json.loads(urllib.request.urlopen(URL + "api/chats").read())[0]["session_id"]
    check("세션 id 저장", sid == "fake-session", str(sid))

    # 폭 3종 + 다크
    for w, h in ((1280, 900), (768, 1024), (390, 844)):
        page.set_viewport_size({"width": w, "height": h})
        page.click("#tab-lib")
        time.sleep(0.3)
        if w == 390:
            page.click("#lib-toggle")
            time.sleep(0.2)
            page.screenshot(path=str(TMP / f"shot_{w}_list.png"))
            page.click(f"button[data-paper='{TARGET}']")
            time.sleep(0.4)
            check("[390] 가로 스크롤 없음", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        page.screenshot(path=str(TMP / f"shot_{w}.png"))
        basics(page, str(w))
        if w <= 768:
            page.click("#chat-toggle")
            time.sleep(0.35)
            check(f"[{w}] 대화 서랍 열림", page.evaluate("document.querySelector('.chat').getBoundingClientRect().left < innerWidth - 100"))
            page.screenshot(path=str(TMP / f"shot_{w}_chat.png"))
            page.keyboard.press("Escape")
            time.sleep(0.3)
    dark = b.new_context(color_scheme="dark", viewport={"width": 1440, "height": 900}).new_page()
    dark.on("pageerror", lambda e: errors.append(str(e)))
    dark.goto(URL)
    dark.wait_for_selector("button.concl")
    dark.click(f"button[data-paper='{TARGET}']")
    dark.wait_for_selector("article .concl")
    dark.screenshot(path=str(TMP / "shot_1440_dark.png"))
    check("JS 오류 없음", not errors, "; ".join(errors[:5]))
    unexpected = [e for e in expected_4xx if "/abstract" not in e]
    check("4xx/5xx 응답 없음", not unexpected, "; ".join(unexpected[:5]))
    b.close()

server.should_exit = True
print(f"\n{sum(results)}/{len(results)} PASS · 스크린샷 {TMP}")
sys.exit(0 if all(results) else 1)
