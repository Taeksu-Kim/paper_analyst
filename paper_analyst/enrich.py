"""받아 둔 논문에 외부 신호를 붙인다 → library/papers/<id>/external.json + 짧은 요약 출력.

    python -m paper_analyst.enrich 2604.12374 2609.05933          # fetch.py 로 먼저 받아 둔 논문
    python -m paper_analyst.enrich 2604.12374 --refresh           # 7일 캐시 무시

모으는 것 (전부 공개 API, 한 건씩 간격):
- Semantic Scholar: 인용 수·영향력 인용 수·학회, 인용 문맥 (다른 논문이 이 논문을 어떤 문장으로 인용했나)
- Hacker News (Algolia): arXiv 링크를 건 글 + 이름(제목 콜론 앞)으로 올라온 글, 댓글 있으면 상위 댓글
- paperswithcode.co: tasks·methods·벤치마크 순위·공식 코드 (비공개 API — 실패해도 진행)
- HF Papers: upvote·GitHub
웹 검색(블로그·비판 글)은 여기서 하지 않는다 — 읽는 쪽(Claude)이 한 번 한다.
출력은 Claude 가 읽는 요약이라 짧게 자른다. 전체는 external.json.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "library" / "papers"
UA = {"User-Agent": "paper_analyst/0.1 (research tool)"}
GAP = {"api.semanticscholar.org": 3.5, "hn.algolia.com": 1.0, "paperswithcode.co": 1.5, "huggingface.co": 1.0}
CACHE_DAYS = 7
try:  # 프로필의 citation_min_age_months (없으면 3개월)
    from paper_analyst.profile import load as _load_profile
    S2_MIN_AGE_DAYS = int(_load_profile().get("citation_min_age_months", 3)) * 30
except SystemExit:
    S2_MIN_AGE_DAYS = 90
MAX_CTX, CTX_CHARS = 8, 220
MAX_HN_STORIES, MAX_HN_COMMENTS, COMMENT_CHARS = 5, 4, 280

_last: dict[str, float] = {}


def get_json(url: str, tries: int = 3):
    host = urllib.parse.urlparse(url).netloc
    headers = dict(UA)
    if host == "api.semanticscholar.org" and os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]  # 키 없으면 공용 한도 — 429 잦음
    for t in range(tries):
        wait = GAP.get(host, 1.0) - (time.monotonic() - _last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and t < tries - 1:
                time.sleep(10 * (t + 1))
                continue
            return {"_error": f"HTTP {e.code}"}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            return {"_error": str(e)[:120]}
        finally:
            _last[host] = time.monotonic()
    return {"_error": "429 반복"}


def clean(s: str, n: int) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ── 소스별 ────────────────────────────────────────────────

_s2_down = False  # 이번 실행에서 S2 가 재시도 끝에 429 → 나머지 논문은 건너뜀 (다음 실행이 다시 시도)


def s2(aid: str) -> dict:
    global _s2_down
    if _s2_down:
        return {"error": "건너뜀 (이번 실행에서 S2 요청 제한)"}
    base = "https://api.semanticscholar.org/graph/v1/paper/ARXIV:" + aid
    p = get_json(base + "?fields=citationCount,influentialCitationCount,venue,publicationDate")
    if "_error" in p:
        _s2_down = p["_error"] in ("HTTP 429", "429 반복")
        return {"error": p["_error"]}
    c = get_json(base + "/citations?fields=title,year,contexts,isInfluential&limit=100")
    rows = c.get("data", []) if "_error" not in c else []
    ctx = []
    for r in rows:
        cs = [x for x in (r.get("contexts") or []) if len(x) > 40]
        if cs:
            ctx.append({"title": (r.get("citingPaper") or {}).get("title"), "year": (r.get("citingPaper") or {}).get("year"),
                        "influential": bool(r.get("isInfluential")), "context": cs[0]})
    ctx.sort(key=lambda x: (not x["influential"], -(x["year"] or 0)))
    return {"citations": p.get("citationCount"), "influential": p.get("influentialCitationCount"),
            "venue": p.get("venue") or None, "contexts_total": len(ctx), "contexts": ctx,
            "citations_error": c.get("_error")}


def short_name(title: str) -> str | None:
    """'Nemotron 3 Super: Open, …' → 'Nemotron 3 Super'. 한 단어 이름은 잡음이 많아 두 단어 이상만."""
    head = title.split(":")[0].strip()
    return head if ":" in title and len(head.split()) >= 2 and len(head) <= 40 else None


def _is_paper_url(url: str, aid: str) -> bool:
    """arXiv·HF 페이지에서 이 id 를 가리키는 링크만 (explainarxiv.org/… 처럼 id 만 들어간 남의 서비스 제외)."""
    u = urllib.parse.urlparse(url or "")
    host = u.netloc.lower()
    ok_host = host in ("arxiv.org", "www.arxiv.org", "export.arxiv.org") or host == "huggingface.co"
    return ok_host and re.search(rf"/{re.escape(aid)}(v\d+)?(\.pdf)?/?$", u.path) is not None


def hn(aid: str, title: str) -> dict:
    api = "https://hn.algolia.com/api/v1/search?"
    stories: dict[str, dict] = {}
    by_url = get_json(api + urllib.parse.urlencode({"query": aid, "tags": "story", "restrictSearchableAttributes": "url"}))
    queries = [("url", by_url)]
    name = short_name(title)
    if name:
        queries.append(("name", get_json(api + urllib.parse.urlencode(
            {"query": name, "tags": "story", "restrictSearchableAttributes": "title"}))))
    for how, res in queries:
        for h in res.get("hits", []):
            t = h.get("title") or ""
            if how == "name" and not re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", t, re.I):
                continue  # 이름이 구절 그대로 있는 글만 ('Nemotron 3.5 Super' 는 'Nemotron 3 Super' 아님)
            if how == "url" and not _is_paper_url(h.get("url"), aid):
                continue
            stories[h["objectID"]] = {"id": h["objectID"], "title": t, "points": h.get("points") or 0,
                                      "comments": h.get("num_comments") or 0, "date": (h.get("created_at") or "")[:10],
                                      "match": how, "url": f"https://news.ycombinator.com/item?id={h['objectID']}"}
    top = sorted(stories.values(), key=lambda s: (-s["points"], -s["comments"]))[:MAX_HN_STORIES]
    for s in sorted(top, key=lambda s: -s["comments"])[:2]:
        if s["comments"] == 0:
            continue
        item = get_json(f"https://hn.algolia.com/api/v1/items/{s['id']}")
        kids = [k for k in item.get("children", []) if k.get("text")]
        s["top_comments"] = [clean(k["text"], COMMENT_CHARS) for k in kids[:MAX_HN_COMMENTS]]
    return {"stories": top, "errors": [r.get("_error") for _, r in queries if "_error" in r] or None}


def pwc(aid: str) -> dict:
    p = get_json(f"https://paperswithcode.co/api/v1/papers/{aid}")
    if "_error" in p:
        return {"error": p["_error"]}
    ranks = sorted(p.get("leaderboard_ranks") or [], key=lambda r: r.get("best_rank") or 99)
    return {"tasks": [t["name"] for t in p.get("tasks") or []], "methods": [m["name"] for m in p.get("methods") or []],
            "official_code": p.get("has_official_implementation"), "code_repos": p.get("code_repository_count"),
            "hf_models": p.get("hf_models") or [],
            "leaderboard": [{"dataset": r.get("dataset_name"), "rank": r.get("best_rank")} for r in ranks[:5]]}


def hf(aid: str) -> dict:
    p = get_json(f"https://huggingface.co/api/papers/{aid}")
    if "_error" in p:
        return {"error": p["_error"]}
    return {"upvotes": p.get("upvotes"), "github": p.get("githubRepo"), "github_stars": p.get("githubStars")}


# ── 조립·출력 ─────────────────────────────────────────────

def enrich(aid: str, refresh: bool) -> dict:
    d = LIBRARY / aid.replace("/", "_")
    if not (d / "meta.json").exists():
        raise FileNotFoundError(f"{aid}: 받아 둔 논문 아님 — paper_analyst/fetch.py {aid} 먼저")
    out = d / "external.json"
    meta = json.loads((d / "meta.json").read_text())
    age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(meta["published"]).date()).days
    # 발표 직후엔 인용이 없다 (측정: 2026-10 논문 인용 중앙값 0.5) → 호출만 낭비하고 429 만 늘린다
    s2_fetch = (lambda: s2(aid)) if age >= S2_MIN_AGE_DAYS else \
        (lambda: {"skipped": f"발표 {age}일 — {S2_MIN_AGE_DAYS}일 미만은 인용이 아직 없어 조회 안 함"})
    fetchers = {"s2": s2_fetch, "hn": lambda: hn(aid, meta["title"]), "pwc": lambda: pwc(aid), "hf": lambda: hf(aid)}
    old = json.loads(out.read_text()) if out.exists() and not refresh else None
    if old and datetime.now(timezone.utc) - datetime.fromisoformat(old["fetched_at"]) < timedelta(days=CACHE_DAYS):
        # 캐시가 새것이면 실패했던 소스만 다시 (429 결과를 7일 붙잡고 있지 않게)
        redo = [k for k in fetchers if "error" in old.get(k, {"error": "없음"})]
        for k in redo:
            old[k] = fetchers[k]()
        old["_cached"] = not redo
        if redo:
            out.write_text(json.dumps({k: v for k, v in old.items() if k != "_cached"}, ensure_ascii=False, indent=2))
        return old
    ext = {"arxiv_id": aid, "title": meta["title"], "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ext.update({k: f() for k, f in fetchers.items()})
    out.write_text(json.dumps(ext, ensure_ascii=False, indent=2))
    return ext


def summary(e: dict) -> str:
    L = [f"## {e['arxiv_id']} {e['title'][:90]}" + ("  (캐시)" if e.get("_cached") else "")]
    s, h, p, f = e["s2"], e["hn"], e["pwc"], e["hf"]
    if "skipped" in s:
        L.append(f"S2: 건너뜀 ({s['skipped']})")
    elif "error" in s:
        L.append(f"S2: 실패 ({s['error']})")
    else:
        ctx_note = f"인용 문맥 조회 실패 ({s['citations_error']})" if s.get("citations_error") else f"인용 문맥 {s['contexts_total']}건"
        L.append(f"S2: 인용 {s['citations']} (영향력 {s['influential']}) · 학회 {s['venue'] or '-'} · {ctx_note}")
        for c in s["contexts"][:MAX_CTX]:
            L.append(f"  - {'★' if c['influential'] else '·'} [{c['year']}] {clean(c['title'], 70)}\n"
                     f"    \"{clean(c['context'], CTX_CHARS)}\"")
    if h["stories"]:
        L.append(f"HN: 글 {len(h['stories'])}개")
        for st in h["stories"]:
            L.append(f"  - {st['points']}점 댓글 {st['comments']} [{st['date']}] {clean(st['title'], 80)} ({st['match']}) {st['url']}")
            for cm in st.get("top_comments", []):
                L.append(f"      > {cm}")
    else:
        L.append("HN: 없음" + (f" (오류 {h['errors']})" if h.get("errors") else ""))
    if "error" in p:
        L.append(f"PWC: 실패 ({p['error']})")
    else:
        lb = ", ".join(f"{r['dataset']} #{r['rank']}" for r in p["leaderboard"]) or "-"
        L.append(f"PWC: tasks {p['tasks'][:5]} · methods {p['methods'][:6]} · 공식코드 {p['official_code']} · 순위 {lb}")
    L.append("HF: " + (f"실패 ({f['error']})" if "error" in f else
                       f"upvote {f['upvotes']} · GitHub {f['github'] or '-'} ({f['github_stars'] or 0}★)"))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="+", help="arXiv id (fetch.py 로 받아 둔 것)")
    ap.add_argument("--refresh", action="store_true", help=f"{CACHE_DAYS}일 캐시 무시하고 다시 조회")
    a = ap.parse_args()
    failed = 0
    for aid in dict.fromkeys(a.ids):
        try:
            print(summary(enrich(aid, a.refresh)) + "\n")
        except FileNotFoundError as e:
            failed += 1
            print(f"FAILED {e}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
