"""화면의 대화 세션 2종 — 같은 `ChatBackend` 뒤의 두 구현 (side_projects REF/AGENT_PRODUCT.md 규칙 8).

① ClaudeBackend: 저장소 폴더를 cwd 로 `claude -p --output-format stream-json` (첫 턴 --session-id, 이후 --resume).
   .claude/skills (paper-find·paper-read·paper-setup) 와 CLAUDE.md 가 그대로 적용. 권한은 허용 목록만.
   실측 2026-11-15 (CLI 2.1.325): 파일 쓰기 규칙은 Write(...) 가 아니라 Edit(<경로>/**) 로 걸어야 동작.
② LocalBackend: 로컬 Qwen (vLLM :8002). JSON 스키마로 "도구 하나 부르기 | 최종 답" 을 고르는 짧은 루프.
   엔진 도구(서재 조회·notes 읽기·제목→id·후보·받기)만 쓴다. notes 작성은 맡기지 않는다 (읽기·정리는 Claude 몫).

두 구현 모두 같은 이벤트를 낸다 (서비스가 그대로 저장·스트림):
  {"type":"session","session_id"} · {"type":"text","text"} · {"type":"tool","id","name","summary"} ·
  {"type":"tool_done","id","ok","summary"} · {"type":"library_changed"} · {"type":"done","cost"} · {"type":"error","message"}
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ChatCtx:
    session_id: str | None            # Claude Code 세션 (없으면 새로)
    history: list[dict] = field(default_factory=list)   # [{"role","content"}] 이전 턴 텍스트 (로컬용)
    paper: dict | None = None         # 화면에서 보고 있는 논문 {"id","title"}


class Proc(Protocol):
    def events(self) -> Iterator[dict]: ...
    def cancel(self) -> None: ...


class ChatBackend(Protocol):
    name: str
    label: str
    def available(self) -> tuple[bool, str]: ...
    def start(self, ctx: ChatCtx, text: str) -> Proc: ...


def with_paper(ctx: ChatCtx, text: str) -> str:
    p = ctx.paper
    return f"[화면에서 보고 있는 논문: arXiv {p['id']} — {p.get('title', '')}]\n\n{text}" if p else text


# ── ① Claude Code ─────────────────────────────────────────────

TOOLS = ("fetch", "enrich", "discover", "resolve", "profile", "post")
# 공통 CLAUDE.md 가 파이썬 절대경로를 쓰라고 해서 Claude 가 그 형태로도 부른다 (실측 2026-11-15) → 두 형태 모두 허용
# 읽기는 저장소 안만. 경로 없는 "Read" 는 디스크 전체 읽기를 허용한다 (실측 2026-11-15: 저장소 밖 파일 내용이 그대로 나옴)
ALLOWED = [
    "Read(./**)", "Grep(./**)", "Glob(./**)", "WebSearch", "WebFetch", "Skill",
    *[f"Bash({py} -m paper_analyst.{t}:*)" for py in ("python", sys.executable) for t in TOOLS],
    "Bash(grep:*)", "Bash(ls:*)", "Bash(wc:*)", "Bash(head:*)",
    "Edit(library/**)", "Edit(lists/**)", "Edit(ideas/**)", "Edit(profiles/**)", "Edit(posts/**)",
]
SYSTEM = (
    "너는 paper_analyst 화면에 심어진 세션이다. 사용자는 브라우저 대화창으로 말하고, 화면 왼쪽 서재는 저장소 파일을 그대로 보여 준다. "
    "논문 정리·후보 목록·아이디어·글 초안은 스킬 규칙대로 파일(library/papers/<id>/notes.md, lists/, ideas/, posts/)로 남겨야 화면에 나타난다. "
    "개인 맥락은 *.private.md 에. 채팅 답은 짧게 — 긴 내용은 파일에 쓰고 무엇을 어디에 썼는지만 말한다. "
    "셸 명령은 하나씩 실행한다 — `;`·`&&`·`|`·`echo` 를 붙이면 승인이 필요해 거부된다. "
    "허용 목록 밖의 도구는 거부된다 (화면에 승인 창구가 없음) — 거부되면 대신 할 수 있는 방법을 말한다."
)
# 명시적 거부 (허용보다 우선): LinkedIn 키·토큰이 있는 공용 설정 폴더
DENIED = ["Read(~/.config/**)", "Grep(~/.config/**)", "Glob(~/.config/**)", "Bash(cat:*)"]
WRITES = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _summary(name: str, inp: dict, root: Path) -> str:
    if name == "Bash":
        return (inp.get("command") or "")[:160]
    for k in ("file_path", "path", "pattern", "query", "url", "skill"):
        if inp.get(k):
            v = str(inp[k])
            return v.replace(str(root) + "/", "") if k in ("file_path", "path") else v[:160]
    return ""


class _ClaudeProc:
    def __init__(self, cmd: list[str], root: Path, env: dict, session_id: str) -> None:
        self.root, self.session_id = root, session_id
        self.p = subprocess.Popen(cmd, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
        self.canceled = False

    def events(self) -> Iterator[dict]:
        pending: dict[str, tuple[str, dict]] = {}
        got_result = False
        assert self.p.stdout
        for line in self.p.stdout:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "system" and d.get("subtype") == "init":
                # 세션이 실제로 생긴 뒤에만 저장 — 시작 전에 중지하면 다음 턴은 새 세션으로 (--resume 이 "대화 없음"으로 실패하지 않게)
                yield {"type": "session", "session_id": d.get("session_id") or self.session_id}
            elif t == "assistant":
                for c in d.get("message", {}).get("content", []):
                    if c.get("type") == "text" and c.get("text", "").strip():
                        yield {"type": "text", "text": c["text"]}
                    elif c.get("type") == "tool_use":
                        pending[c["id"]] = (c["name"], c.get("input") or {})
                        yield {"type": "tool", "id": c["id"], "name": c["name"],
                               "summary": _summary(c["name"], c.get("input") or {}, self.root)}
            elif t == "user":
                for c in d.get("message", {}).get("content", []):
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        name, inp = pending.pop(c.get("tool_use_id"), ("", {}))
                        err = bool(c.get("is_error"))
                        content = c.get("content")
                        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                        yield {"type": "tool_done", "id": c.get("tool_use_id"), "ok": not err,
                               "summary": text[:300] if err else ""}
                        if not err and (name in WRITES or (name == "Bash" and "paper_analyst.fetch" in inp.get("command", ""))):
                            yield {"type": "library_changed"}
            elif t == "result":
                got_result = True
                if d.get("is_error") and d.get("subtype") != "success":
                    yield {"type": "error", "message": str(d.get("result") or d.get("subtype"))[:500]}
                yield {"type": "done", "cost": d.get("total_cost_usd"),
                       "denied": [x.get("tool_name") for x in d.get("permission_denials", [])]}
        code = self.p.wait()
        if not got_result and not self.canceled:
            err = (self.p.stderr.read() if self.p.stderr else "")[-500:]
            yield {"type": "error", "message": f"Claude Code 가 결과 없이 끝났습니다 (종료 코드 {code}). {err}".strip()}

    def cancel(self) -> None:
        self.canceled = True
        if self.p.poll() is None:
            try:
                os.killpg(self.p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


class ClaudeBackend:
    name, label = "claude", "Claude Code"

    def __init__(self, root: Path, model: str | None = None) -> None:
        self.root, self.model = root, model

    def available(self) -> tuple[bool, str]:
        if not shutil.which("claude"):
            return False, "claude 명령이 없습니다. Claude Code 를 설치하고 터미널에서 `claude` 로 로그인한 뒤 서버를 다시 켜세요."
        return True, ""

    def start(self, ctx: ChatCtx, text: str) -> Proc:
        sid = ctx.session_id or str(uuid.uuid4())
        cmd = ["claude", "-p", with_paper(ctx, text), "--output-format", "stream-json", "--verbose",
               "--strict-mcp-config", "--append-system-prompt", SYSTEM, "--allowedTools", *ALLOWED,
               "--disallowedTools", *DENIED]
        cmd += ["--resume", sid] if ctx.session_id else ["--session-id", sid]
        if self.model:
            cmd += ["--model", self.model]
        env = dict(os.environ)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")   # 스킬의 `python` = 이 환경
        return _ClaudeProc(cmd, self.root, env, sid)


# ── ② 로컬 LLM ───────────────────────────────────────────────

MODEL = "qwen3.8-27b-redhat-int4"
LOCAL_SYSTEM = (
    "너는 논문 서재 도우미다. 한국어로 짧게 답한다. 서재·논문에 대한 사실은 반드시 도구로 확인하고, 도구 결과에 없는 내용은 지어내지 않는다. "
    "논문을 새로 읽고 notes 를 쓰는 일은 하지 않는다 — 그런 요청이면 'Claude Code 세션에서 paper-read 로 정리하세요'라고 안내한다.\n"
    "한 번에 도구 하나를 부르거나 최종 답을 낸다. 도구:\n{tools}"
)
ACTION = {"anyOf": [
    {"type": "object", "properties": {"action": {"type": "string", "const": "tool"}, "tool": {"type": "string"},
                                      "args": {"type": "object"}}, "required": ["action", "tool", "args"]},
    {"type": "object", "properties": {"action": {"type": "string", "const": "final"}, "answer": {"type": "string"}},
     "required": ["action", "answer"]},
]}


@dataclass
class Tool:
    fn: Callable[..., object]
    doc: str                      # 인자 스키마 포함 설명 (LLM.md 함정: 인자 이름 추측)
    writes: bool = False


def default_llm_url() -> str:
    if os.environ.get("PAPER_LLM_URL"):
        return os.environ["PAPER_LLM_URL"]
    try:
        ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout.split()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        ip = "127.0.0.1"
    return f"http://{ip}:8002/v1"


class _LocalProc:
    MAX_STEPS = 6

    def __init__(self, backend: "LocalBackend", ctx: ChatCtx, text: str) -> None:
        self.b, self.ctx, self.text = backend, ctx, text
        self.stop = threading.Event()

    def events(self) -> Iterator[dict]:
        tools = "\n".join(f"- {n}: {t.doc}" for n, t in self.b.tools.items())
        msgs = [{"role": "system", "content": LOCAL_SYSTEM.format(tools=tools)}]
        msgs += self.ctx.history[-6:]
        msgs.append({"role": "user", "content": with_paper(self.ctx, self.text)})
        for step in range(self.MAX_STEPS):
            if self.stop.is_set():
                return
            try:
                out = self.b.call(msgs)
            except RuntimeError as e:
                yield {"type": "error", "message": str(e)}
                return
            if out.get("action") == "final":
                yield {"type": "text", "text": out.get("answer", "")}
                yield {"type": "done", "cost": 0}
                return
            name, args = out.get("tool", ""), out.get("args") or {}
            tid = f"local-{step}"
            yield {"type": "tool", "id": tid, "name": name, "summary": json.dumps(args, ensure_ascii=False)[:160]}
            tool = self.b.tools.get(name)
            if not tool:
                result, ok = f"없는 도구: {name}. 쓸 수 있는 도구: {', '.join(self.b.tools)}", False
            else:
                try:
                    result, ok = tool.fn(**args), True
                except TypeError as e:
                    result, ok = f"인자 오류: {e}. 기대 인자: {tool.doc}", False
                except Exception as e:  # 도구 실패는 모델에게 돌려줘 다음 행동을 고르게 한다
                    result, ok = f"도구 실패: {e}", False
            body = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            if len(body) > 2500:
                body = body[:2500] + " …(잘림 — 더 필요하면 offset 인자로 이어 읽기)"
            yield {"type": "tool_done", "id": tid, "ok": ok, "summary": "" if ok else body[:300]}
            if ok and tool and tool.writes:
                yield {"type": "library_changed"}
            msgs.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
            msgs.append({"role": "user", "content": f"[도구 결과 {name}]\n{body}"})
        yield {"type": "text", "text": f"도구를 {self.MAX_STEPS}번 써도 답을 정하지 못했습니다. 질문을 좁혀 주세요."}
        yield {"type": "done", "cost": 0}

    def cancel(self) -> None:
        self.stop.set()


class LocalBackend:
    name, label = "local", "로컬 LLM"

    def __init__(self, tools: dict[str, Tool], base_url: str | None = None) -> None:
        self.tools, self.base = tools, base_url or default_llm_url()

    def available(self) -> tuple[bool, str]:
        try:
            urllib.request.urlopen(f"{self.base}/models", timeout=2).read()
            return True, ""
        except (urllib.error.URLError, TimeoutError, OSError):
            return False, (f"로컬 LLM 서버({self.base})가 꺼져 있습니다. side_projects/reference/LLM.md §2 의 명령으로 켜면 "
                           "약 1분 뒤 쓸 수 있습니다.")

    def call(self, msgs: list[dict]) -> dict:
        body = {"model": MODEL, "messages": msgs, "temperature": 0, "max_tokens": 800,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {"name": "act", "schema": ACTION}}}
        req = urllib.request.Request(f"{self.base}/chat/completions", data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if "maximum context length" in msg:
                raise RuntimeError("대화가 로컬 모델 한도(8,192 토큰)를 넘었습니다. 새 대화로 시작하세요.") from e
            raise RuntimeError(f"로컬 LLM 오류 HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(f"로컬 LLM 에 연결하지 못했습니다: {e}") from e
        try:
            return json.loads(data["choices"][0]["message"]["content"])
        except (KeyError, json.JSONDecodeError) as e:
            raise RuntimeError("로컬 LLM 응답을 읽지 못했습니다") from e

    def start(self, ctx: ChatCtx, text: str) -> Proc:
        return _LocalProc(self, ctx, text)
