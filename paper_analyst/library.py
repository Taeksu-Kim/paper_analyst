"""서재 — 파일(library/papers, lists, ideas)을 읽어 화면·서비스가 쓰는 모양으로. 네트워크 없음.

논문 폴더가 진실의 원천이다 (Claude 가 스킬로 파일을 쓴다). 상태 덮어쓰기·후보·대화는 서비스(SQLite)가 가진다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import markdown as _md

DOC_DIRS = ("lists", "ideas")


@dataclass
class Paper:
    id: str
    title: str
    published: str = ""
    category: str = ""
    authors: list[str] = field(default_factory=list)
    has_notes: bool = False
    has_private: bool = False
    has_parsed: bool = False
    conclusion: str = ""
    noted_at: float = 0.0     # notes.md 수정 시각 (epoch)
    fetched_at: str = ""

    def dict(self) -> dict:
        return asdict(self)


def _section(md: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", md, re.M | re.S)
    return m.group(1).strip() if m else ""


def conclusion(md: str) -> str:
    """notes.md 의 결론 판정 문장 (## 결론 의 굵은 블록). 예전 양식은 '한 줄 요약'."""
    body = _section(md, "결론")
    if body:
        m = re.match(r"\*\*(.+?)\*\*", body, re.S)
        if m:
            return " ".join(m.group(1).split())
        return " ".join(body.split("\n\n")[0].split())
    return " ".join(_section(md, "한 줄 요약").split())


def scan_papers(root: Path) -> dict[str, Paper]:
    out: dict[str, Paper] = {}
    base = root / "library" / "papers"
    if not base.exists():
        return out
    for d in sorted(base.iterdir()):
        mf = d / "meta.json"
        if not mf.is_file():
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        p = Paper(id=d.name, title=m.get("title") or d.name, published=m.get("published", ""),
                  category=m.get("primary_category", ""), authors=m.get("authors", [])[:20],
                  fetched_at=m.get("fetched_at", ""), has_parsed=(d / "parsed" / "paper.md").is_file())
        notes = d / "notes.md"
        if notes.is_file():
            text = notes.read_text(encoding="utf-8")
            p.has_notes, p.conclusion, p.noted_at = True, conclusion(text), notes.stat().st_mtime
        p.has_private = (d / "notes.private.md").is_file()
        out[p.id] = p
    return out


def paper_files(root: Path, aid: str) -> dict:
    """논문 하나의 notes·개인 메모·초록. 없는 것은 빈 문자열."""
    d = root / "library" / "papers" / aid
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").is_file() else {}
    read = lambda f: (d / f).read_text(encoding="utf-8") if (d / f).is_file() else ""
    return {"meta": meta, "notes": read("notes.md"), "private": read("notes.private.md")}


def scan_docs(root: Path) -> list[dict]:
    """lists/·ideas/ 의 공개 문서 (+ 같은 이름의 .private.md 가 있는지)."""
    out = []
    for kind in DOC_DIRS:
        d = root / kind
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md"), reverse=True):
            if f.name.endswith(".private.md"):
                continue
            first = f.read_text(encoding="utf-8").lstrip().split("\n", 1)[0]
            out.append({"kind": kind, "name": f.stem, "title": first.lstrip("# ").strip() or f.stem,
                        "mtime": f.stat().st_mtime, "has_private": f.with_suffix(".private.md").is_file()})
    # 개인 문서만 있는 것 (예: 큐레이터 목록)
    for kind in DOC_DIRS:
        d = root / kind
        for f in sorted(d.glob("*.private.md"), reverse=True) if d.is_dir() else []:
            if not (d / f.name.replace(".private.md", ".md")).exists():
                first = f.read_text(encoding="utf-8").lstrip().split("\n", 1)[0]
                out.append({"kind": kind, "name": f.name[:-3], "title": first.lstrip("# ").strip(),
                            "mtime": f.stat().st_mtime, "has_private": True, "private_only": True})
    return out


def read_doc(root: Path, kind: str, name: str) -> dict:
    if kind not in DOC_DIRS or not re.fullmatch(r"[\w.\-]+", name):
        raise FileNotFoundError(name)
    f = root / kind / f"{name}.md"
    priv = root / kind / f"{name.removesuffix('.private')}.private.md"
    if not f.is_file():
        raise FileNotFoundError(name)
    return {"text": f.read_text(encoding="utf-8"),
            "private": priv.read_text(encoding="utf-8") if priv.is_file() and priv != f else ""}


_LIST = re.compile(r"^( *)([-*+]|\d+\.) ")


def _gfm_lists(text: str) -> str:
    """Python-Markdown 은 문단 바로 뒤의 목록(빈 줄 없음)과 2칸 들여쓴 하위 목록을 목록으로 안 본다.
    notes 는 GitHub 식으로 쓰여 있어 그대로면 '가져갈 것·믿어도 되는 결과' 목록이 한 문단으로 뭉친다 → 보정."""
    out: list[str] = []
    in_code = False
    indents = {len(m.group(1)) for m in map(_LIST.match, text.split("\n")) if m}
    unit = 2 if any(i % 4 == 2 for i in indents) else 4      # 이 문서의 들여쓰기 단위
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _LIST.match(line)
        if m:
            indent = len(m.group(1))
            if indent and unit == 2:
                line = " " * (indent // 2 * 4) + line[indent:]
            prev = out[-1] if out else ""
            if prev.strip() and not _LIST.match(prev) and not prev.startswith((" ", "|", "#")):
                out.append("")
        out.append(line)
    return "\n".join(out)


def to_html(text: str) -> str:
    """마크다운 → HTML. 원시 HTML 은 글자로 (notes 는 외부 글을 옮겨 적기도 하므로)."""
    text = _gfm_lists(text)
    md = _md.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    return md.convert(text)
