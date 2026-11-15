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


def conclusion_parts(md: str) -> list[dict]:
    """결론 절의 '- **라벨:** 내용' 항목들 (가져갈 것·믿어도 되는 결과·해석에 주의할 결과·읽는다면). 비교 보기에 쓴다."""
    body = _section(md, "결론")
    parts: list[dict] = []
    for m in re.finditer(r"^- \*\*([^*\n]+?):?\*\*:?\s*(.*?)(?=^- \*\*|\Z)", body, re.M | re.S):
        text = _dedent_rest(m.group(2).strip())
        parts.append({"label": m.group(1).strip().rstrip(":"), "md": text})
    return parts


def _dedent_rest(text: str) -> str:
    """'- **라벨:** 첫 줄' 뒤의 이어지는 줄들은 항목 안쪽으로 들여 쓰여 있다 → 공통 들여쓰기를 걷어 목록·문단으로 읽히게."""
    lines = text.split("\n")
    rest = [l for l in lines[1:] if l.strip()]
    cut = min((len(l) - len(l.lstrip(" ")) for l in rest), default=0)
    return "\n".join([lines[0]] + [l[cut:] for l in lines[1:]])


def _acronym(topic: str) -> str:
    words = [w for w in re.split(r"[\s\-]+", topic) if w]
    return "".join(w[0] for w in words).upper() if len(words) >= 3 else ""


def suggest_tags(md: str, title: str, topics: list[str]) -> list[str]:
    """프로필 관심 주제 중 notes 의 '관심 주제와의 연결' 절이나 제목에 나온 것 (약어 RAG 등도)."""
    text = _section(md, "관심 주제와의 연결") + "\n" + title
    low = text.lower()
    out = []
    for t in topics:
        ac = _acronym(t)
        if t.lower() in low or (ac and re.search(rf"\b{re.escape(ac)}\b", text)):
            out.append(t)
    return out


def short_name(title: str) -> str:
    """notes 에서 다른 논문을 부르는 이름: 콜론 앞, 콜론이 없으면 앞 세 단어 (예: 'Meta-Harness', 'LLMs Get Lost')."""
    name = title.split(":")[0] if ":" in title else " ".join(title.split()[:3])
    return name.strip()


def mentions(md: str, self_id: str, papers: dict[str, "Paper"]) -> list[str]:
    """notes 본문에 나온 다른 서재 논문 (arXiv id 또는 짧은 이름). 연결 제안에 쓴다."""
    out = []
    for p in papers.values():
        if p.id == self_id:
            continue
        if p.id in md or _named(md, p.title):
            out.append(p.id)
    return out


def _named(md: str, title: str) -> bool:
    """짧은 이름이 나오고, 바로 뒤 영어 단어들이 그 논문 제목과 어긋나지 않을 때만
    ('Rethinking the Evaluation of Harness…' 는 'Rethinking the Evaluation of Efficiency…' 가 아니다)."""
    name = short_name(title)
    if len(name) < 8:
        return False
    rest = title[len(name):].lstrip(": ").split() if title.startswith(name) else []
    for m in re.finditer(re.escape(name), md):
        if re.match(r"-?[A-Za-z0-9]", md[m.end():m.end() + 2]):   # 'DeepSeek-V4-Pro' 는 'DeepSeek-V4' 가 아니다
            continue
        after = re.match(r"[ \-]*((?:[A-Za-z][\w\-]*\s*){0,2})", md[m.end():]).group(1).split()
        if all(i < len(rest) and w.lower() == rest[i].lower() for i, w in enumerate(after)) or ":" in title:
            return True
    return False


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
    return {"meta": meta, "notes": read("notes.md"), "private": read("notes.private.md"), "memo": read("memo.private.md")}


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
