"""발행 초안 — posts/<날짜>_<이름>/ 의 linkedin.md · blog.md 를 읽고 점검한다. 네트워크 없음.

    python -m paper_analyst.post check posts/2026-11-16_llm-judge      # 점검 (개인 메모 겹침·길이)
    python -m paper_analyst.post list

폴더 하나 = 글 하나:
  meta.json   {"title", "sources": ["2610.09229", "ideas/…"], "created"}
  linkedin.md 짧은 글 (LinkedIn) — 붙여넣을 때는 마크다운 기호를 뺀 글자로 복사
  blog.md     장문 (기술 블로그 마크다운). 티스토리용 HTML 은 여기서 변환 (Claude 가 따로 쓰지 않는다)

점검:
- 개인 메모 겹침: 초안의 각 줄을 저장소의 모든 *.private.md 와 글자 12-gram 으로 비교해, 절반 이상 겹치면 경고.
  개인 단어 목록을 코드에 두지 않는다 (공개 저장소에 개인 정보가 들어가므로) — 비공개 파일 자체가 기준이다.
- 길이: LinkedIn 본문 3,000자 한도, 첫 줄 훅이 '더 보기' 전에 보이는지 (약 210자, 확인 안 한 어림값).
posts/ 는 git 에서 제외된다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from paper_analyst import ROOT
from paper_analyst.library import to_html

LINKEDIN_LIMIT = 3000
LINKEDIN_FOLD = 210        # '더 보기' 전 노출 어림값 (공식 수치 확인 안 함)
NGRAM = 12
PRIVATE_DIRS = ("library", "ideas", "lists", "profiles")


def posts_dir(root: Path) -> Path:
    return root / "posts"


def list_posts(root: Path) -> list[dict]:
    out = []
    d = posts_dir(root)
    for p in sorted(d.iterdir(), reverse=True) if d.is_dir() else []:
        if not p.is_dir():
            continue
        meta = _meta(p)
        out.append({"slug": p.name, "title": meta.get("title") or p.name, "sources": meta.get("sources", []),
                    "created": meta.get("created", ""), "has": [f for f in ("linkedin.md", "blog.md") if (p / f).exists()],
                    "mtime": max((f.stat().st_mtime for f in p.iterdir()), default=0)})
    return out


def _meta(p: Path) -> dict:
    try:
        return json.loads((p / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def plain(md: str) -> str:
    """LinkedIn 에 붙일 글자: 마크다운 기호(굵게·제목·링크 문법)를 걷어낸다. 줄바꿈은 그대로."""
    t = re.sub(r"^#{1,6}[ \t]+", "", md, flags=re.M)     # 제목만 (줄 맨 앞 해시태그 '#LLM' 은 그대로)
    t = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), t)
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", t)
    t = re.sub(r"^\s*[-*] ", "• ", t, flags=re.M)
    return t.strip() + "\n"


def _grams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + NGRAM] for i in range(max(0, len(s) - NGRAM + 1))}


def private_corpus(root: Path) -> dict[str, set[str]]:
    out = {}
    for d in PRIVATE_DIRS:
        for f in (root / d).rglob("*.private.md") if (root / d).is_dir() else []:
            out[str(f.relative_to(root))] = _grams(f.read_text(encoding="utf-8"))
    return out


def check(text: str, root: Path, kind: str) -> dict:
    corpus = private_corpus(root)
    hits = []
    for i, line in enumerate(text.split("\n"), 1):
        g = _grams(line)
        if len(g) < 3:      # 너무 짧은 줄 (제목·빈 줄)은 판단 안 함
            continue
        for src, pg in corpus.items():
            r = len(g & pg) / len(g)
            if r >= 0.5:
                hits.append({"line": i, "text": line.strip()[:160], "ratio": round(r, 2), "source": src})
                break
    out: dict = {"private_hits": hits, "chars": len(text)}
    if kind == "linkedin":
        body = plain(text)
        first = next((l for l in body.split("\n") if l.strip()), "")
        out.update({"chars": len(body), "limit": LINKEDIN_LIMIT, "over_limit": len(body) > LINKEDIN_LIMIT,
                    "hook": first[:LINKEDIN_FOLD], "hook_cut": len(first) > LINKEDIN_FOLD})
    return out


def read_post(root: Path, slug: str) -> dict:
    if not re.fullmatch(r"[\w.\-]+", slug):
        raise FileNotFoundError(slug)
    p = posts_dir(root) / slug
    if not p.is_dir():
        raise FileNotFoundError(slug)
    out = {"slug": slug, **{k: v for k, v in _meta(p).items() if k in ("title", "sources", "created")}}
    li = (p / "linkedin.md").read_text(encoding="utf-8") if (p / "linkedin.md").exists() else ""
    bl = (p / "blog.md").read_text(encoding="utf-8") if (p / "blog.md").exists() else ""
    out["linkedin"] = {"md": li, "plain": plain(li), "check": check(li, root, "linkedin")} if li else None
    out["blog"] = {"md": bl, "html": to_html(bl), "check": check(bl, root, "blog")} if bl else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m paper_analyst.post")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("path", help="posts/<이름> 또는 <이름>")
    a = ap.parse_args()
    if a.cmd == "list":
        for p in list_posts(ROOT):
            print(f"{p['slug']}\t{p['title']}\t{','.join(p['has'])}")
        return 0
    slug = Path(a.path).name
    try:
        r = read_post(ROOT, slug)
    except FileNotFoundError:
        print(f"초안 없음: posts/{slug}")
        return 1
    bad = 0
    for kind in ("linkedin", "blog"):
        v = r.get(kind)
        if not v:
            continue
        ch = v["check"]
        line = f"[{kind}] {ch['chars']}자"
        if kind == "linkedin":
            line += f" / 한도 {ch['limit']}" + (" — 넘음" if ch["over_limit"] else "") + (" · 첫 줄이 '더 보기' 전에 다 안 보임" if ch["hook_cut"] else "")
            bad += ch["over_limit"]
        print(line)
        for h in ch["private_hits"]:
            bad += 1
            print(f"  ⚠ {h['line']}행: 개인 메모와 {int(h['ratio'] * 100)}% 겹침 ({h['source']}) — {h['text']}")
    print("문제 없음" if not bad else f"고칠 것 {bad}건")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
