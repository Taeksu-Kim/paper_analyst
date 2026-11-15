"""논문 후보 찾기 — 프로필 설정으로 여러 소스에서 모아 주제·신호로 거른다.

    python -m paper_analyst.discover --from 2026-01 --to 2026-11                  # 현재 프로필 (paper_analyst/profile.py)
    python -m paper_analyst.discover --profile nlp --from 2026-09 --to 2026-11 --sources hf,hn
    python -m paper_analyst.discover --check 2603.28052 2604.15597                # 이 논문들이 프로필 필터를 통과하나 (paper-setup 보정용)

소스 (전부 공개 API, 호스트별 간격):
- hf : HF Daily Papers 월별 목록 (월당 최대 pages × 100편) — upvote, GitHub, 스타
- hn : Hacker News 에 arXiv 링크로 올라온 글 (기간 내, 최소 점수) — 실무자 관심
- kw : 관심 키워드(discover.keywords + watch.models)로 HF 검색 — 신호가 약한 응용 논문용, 걸리면 신호 기준과 무관하게 통과('kw')
- s2 : Semantic Scholar 주제별 인용순 검색 (discover.s2_topics, 분야 discover.s2_fields) — 영향력. 키 없으면 429 잦음 (S2_API_KEY)
hf·hn 은 AI·개발 쪽에 치우친 소스다 — 다른 분야 프로필은 discover.sources 에서 빼고 s2 만 쓴다.

거르기: 기간(arXiv id 앞 4자리 YYMM) → 주제(include / exclude 정규식, 제목 + HF 키워드) → 신호 기준(하나라도 넘으면 후보).
신호는 합산하지 않는다 (임의 가중치를 피함). 출력:
- library/candidates/<오늘>_<프로필>.jsonl : 주제를 통과한 전부 (신호·출처 태그 포함)
- 화면 : 신호 기준을 넘은 후보 표
다음 단계(초록 확인·실무 기준 판정)는 paper-find 스킬이 한다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from paper_analyst.profile import load as load_profile

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "library" / "candidates"
UA = {"User-Agent": "paper_analyst/0.1 (research tool)"}
GAP = {"huggingface.co": 1.2, "hn.algolia.com": 1.0, "api.semanticscholar.org": 4.0}
_last: dict[str, float] = {}


def get_json(url: str, tries: int = 3):
    host = urllib.parse.urlparse(url).netloc
    headers = dict(UA)
    if host == "api.semanticscholar.org" and os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
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
            return {"_error": str(e)[:80]}
        finally:
            _last[host] = time.monotonic()
    return {"_error": "429 반복"}


def months(a: str, b: str) -> list[str]:
    y, m = map(int, a.split("-"))
    y2, m2 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class Pool:
    def __init__(self) -> None:
        self.c: dict[str, dict] = {}

    def add(self, aid: str | None, src: str, **kw) -> None:
        if not aid or not re.fullmatch(r"\d{4}\.\d{4,5}", aid):
            return
        c = self.c.setdefault(aid, {"id": aid, "src": []})
        if src not in c["src"]:
            c["src"].append(src)
        for k, v in kw.items():
            if v in (None, "", []):
                continue
            if k in ("hn_points", "upvotes", "stars", "cit"):
                c[k] = max(c.get(k) or 0, v)
            elif not c.get(k):
                c[k] = v


def collect_hf(pool: Pool, ms: list[str], pages: int, log: list[str]) -> None:
    for mm in ms:
        n = 0
        for p in range(pages):
            d = get_json(f"https://huggingface.co/api/daily_papers?month={mm}&limit=100&p={p}")
            if not isinstance(d, list) or not d:
                break
            for x in d:
                q = x.get("paper", {})
                pool.add(q.get("id"), "hf", title=q.get("title"), upvotes=q.get("upvotes"), gh=q.get("githubRepo"),
                         stars=q.get("githubStars"), kw=q.get("ai_keywords"))
            n += len(d)
            if len(d) < 100:
                break
        log.append(f"hf {mm}: {n}")


def collect_hn(pool: Pool, since: str, min_points: int, log: list[str]) -> None:
    ts = int(datetime.fromisoformat(since + "-01").replace(tzinfo=timezone.utc).timestamp())
    n = 0
    for page in range(20):
        q = urllib.parse.urlencode({"query": "arxiv.org", "tags": "story", "restrictSearchableAttributes": "url",
                                    "numericFilters": f"created_at_i>{ts},points>={min_points}",
                                    "hitsPerPage": 100, "page": page})
        d = get_json("https://hn.algolia.com/api/v1/search?" + q)
        hits = d.get("hits", []) if isinstance(d, dict) else []
        if not hits:
            break
        for h in hits:
            m = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", h.get("url") or "")
            if m:
                n += 1
                pool.add(m.group(1), "hn", title=h.get("title"), hn_points=h.get("points"),
                         hn_comments=h.get("num_comments"))
    log.append(f"hn arXiv 글: {n}")


def collect_s2(pool: Pool, topics: list[str], year: str, fields: list[str], log: list[str]) -> None:
    for tp in topics:
        q = urllib.parse.urlencode({"query": tp, "year": year, "fieldsOfStudy": ",".join(fields),
                                    "sort": "citationCount:desc", "fields": "title,citationCount,externalIds"})
        d = get_json("https://api.semanticscholar.org/graph/v1/paper/search/bulk?" + q, tries=4)
        rows = d.get("data", [])[:30] if isinstance(d, dict) else []
        for r in rows:
            pool.add((r.get("externalIds") or {}).get("ArXiv"), f"s2:{tp}", title=r.get("title"),
                     cit=r.get("citationCount"))
        log.append(f"s2 '{tp}': {len(rows)}" + (f" ({d['_error']})" if isinstance(d, dict) and "_error" in d else ""))


def collect_kw(pool: Pool, terms: list[str], log: list[str]) -> set[str]:
    """관심 키워드로 HF 논문 검색 (검색어당 최대 약 120편, 날짜 무관 → 기간 필터는 뒤에서). 신호가 약한 응용 논문용."""
    hit: set[str] = set()
    for term in terms:
        d = get_json("https://huggingface.co/api/papers/search?q=" + urllib.parse.quote(term))
        rows = d if isinstance(d, list) else []
        for x in rows:
            q = x.get("paper", x)
            pool.add(q.get("id"), f"kw:{term}", title=q.get("title"), upvotes=q.get("upvotes"), gh=q.get("githubRepo"),
                     kw=q.get("ai_keywords"))
            if q.get("id"):
                hit.add(q["id"])
        log.append(f"kw '{term}': {len(rows)}" + (f" ({d['_error']})" if isinstance(d, dict) and "_error" in d else ""))
    return hit


def topic_filter(cfg: dict):
    inc = re.compile("|".join(cfg.get("include", [r"(?!x)x"])), re.I)
    exc = re.compile("|".join(cfg.get("exclude", [r"(?!x)x"])), re.I)

    def check(c: dict) -> str:
        """통과면 '', 아니면 이유."""
        title = c.get("title") or ""
        text = title + " " + " ".join(c.get("kw") or [])
        if not inc.search(text):
            return "include 에 안 걸림"
        m = exc.search(title)
        return f"exclude '{m.group(0)}'" if m else ""
    return check


def signals(c: dict, th: dict) -> list[str]:
    """신호 기준을 넘은 것 + 관심 키워드 검색에 걸렸으면 'kw' (기준값과 무관한 별도 경로)."""
    out = [k for k, key in (("stars", "stars"), ("hn", "hn_points"), ("cit", "cit")) if (c.get(key) or 0) >= th.get(k, 10 ** 9)]
    if any(s.startswith("kw:") for s in c.get("src", [])):
        out.append("kw")
    return out


def kw_terms(prof: dict) -> list[str]:
    """키워드 검색어 = discover.keywords + watch.models (관심 모델 계열은 신호와 무관하게 후보로)."""
    terms = list(prof.get("discover", {}).get("keywords", [])) + list(prof.get("watch", {}).get("models", []))
    return list(dict.fromkeys(terms))


def check_ids(ids: list[str], cfg: dict, terms: list[str]) -> int:
    """예시 논문이 주제 필터·신호 기준을 통과하는지 (기간은 보지 않음). HF 에 없으면 제목만으로 본다."""
    topic, th = topic_filter(cfg), cfg.get("thresholds", {})
    cit = s2_citations(ids)
    kw_pool, kw_log = Pool(), []
    collect_kw(kw_pool, terms, kw_log)
    ok = 0
    for aid in ids:
        d = get_json(f"https://huggingface.co/api/papers/{aid}")
        c = {"id": aid, "title": d.get("title"), "kw": d.get("ai_keywords"), "stars": d.get("githubStars"),
             "upvotes": d.get("upvotes")} if isinstance(d, dict) and "_error" not in d else {"id": aid}
        if not c.get("title"):   # HF 에 없음 → arXiv abs 페이지 제목
            c["title"] = _arxiv_title(aid)
        c["cit"] = cit.get(aid)
        c["hn_points"] = hn_best(aid)
        c["src"] = kw_pool.c.get(aid, {}).get("src", [])
        why = topic(c) if c.get("title") else "제목 못 찾음"
        ok += not why
        sig = signals(c, th)
        print(f"{aid} | {'주제 통과' if not why else '주제 탈락: ' + why} | 신호 {','.join(sig) or '없음'} "
              f"(★{c.get('stars') or 0} hn{c.get('hn_points') or 0} cit{'?' if c.get('cit') is None else c['cit']} up{c.get('upvotes') or 0}, HF {'있음' if c.get('kw') is not None else '없음'}{', 키워드 ' + ','.join(s[3:] for s in c['src']) if c['src'] else ''}) | {(c.get('title') or '')[:70]}")
    print(f"\n주제 필터 통과 {ok}/{len(ids)}  (cit? = S2 조회 실패, 기간은 보지 않음)")
    return 0


def s2_citations(ids: list[str]) -> dict[str, int]:
    """S2 batch 한 번으로 인용 수. 실패하면 빈 dict (호출부는 '?' 로 표시)."""
    host = "api.semanticscholar.org"
    headers = {**UA, "Content-Type": "application/json"}
    if os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    body = json.dumps({"ids": [f"ARXIV:{i}" for i in ids]}).encode()
    for t in range(3):
        try:
            req = urllib.request.Request(f"https://{host}/graph/v1/paper/batch?fields=citationCount,externalIds",
                                         data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                rows = json.loads(r.read())
            return {(x.get("externalIds") or {}).get("ArXiv"): x.get("citationCount") for x in rows if x}
        except urllib.error.HTTPError as e:
            if e.code == 429 and t < 2:
                time.sleep(10 * (t + 1))
                continue
            return {}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return {}
    return {}


def hn_best(aid: str) -> int:
    q = urllib.parse.urlencode({"query": aid, "tags": "story", "restrictSearchableAttributes": "url", "hitsPerPage": 20})
    d = get_json("https://hn.algolia.com/api/v1/search?" + q)
    return max((h.get("points") or 0 for h in d.get("hits", [])), default=0) if isinstance(d, dict) else 0


def _arxiv_title(aid: str) -> str:
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://arxiv.org/abs/{aid}", headers=UA), timeout=40) as r:
            m = re.search(r'<meta name="citation_title" content="([^"]+)"', r.read().decode("utf-8", "replace"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def in_period(aid: str, a: str, b: str) -> bool:
    yymm = aid[:4]
    return a[2:4] + a[5:7] <= yymm <= b[2:4] + b[5:7]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="프로필 이름·경로 (기본: 현재 프로필)")
    ap.add_argument("--from", dest="start", help="YYYY-MM (arXiv 발표 월 기준, 포함)")
    ap.add_argument("--to", dest="end", help="YYYY-MM (포함)")
    ap.add_argument("--sources", help="hf,hn,s2,kw 중 (기본: 프로필 discover.sources)")
    ap.add_argument("--check", nargs="+", metavar="ARXIV_ID", help="수집 대신 이 논문들이 필터를 통과하는지만 본다")
    a = ap.parse_args()
    prof = load_profile(a.profile)
    cfg = prof.get("discover", {})
    if a.check:
        return check_ids(a.check, cfg, kw_terms(prof))
    if not (a.start and a.end):
        ap.error("--from 과 --to 가 필요 (또는 --check)")
    for v in (a.start, a.end):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
            ap.error(f"YYYY-MM 형식이 아님: {v}")
    if a.start > a.end:
        ap.error(f"--from {a.start} 이 --to {a.end} 보다 늦음")

    topic, th = topic_filter(cfg), cfg.get("thresholds", {})
    srcs = set((a.sources or ",".join(cfg.get("sources", ["hf", "hn", "s2"]))).split(","))
    pool, log = Pool(), []

    if "hf" in srcs:
        collect_hf(pool, months(a.start, a.end), int(cfg.get("hf_pages", 5)), log)
    if "hn" in srcs:
        collect_hn(pool, a.start, int(cfg.get("hn_min_points", 20)), log)
    if "kw" in srcs:
        collect_kw(pool, kw_terms(prof), log)
    if "s2" in srcs:
        years = sorted({a.start[:4], a.end[:4]})
        collect_s2(pool, cfg.get("s2_topics", []), "-".join([years[0], years[-1]]) if len(years) > 1 else years[0],
                   cfg.get("s2_fields", ["Computer Science"]), log)

    rel = []
    for c in pool.c.values():
        if in_period(c["id"], a.start, a.end) and not topic(c):
            c["signals"] = signals(c, th)
            rel.append(c)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{date.today().isoformat()}_{prof.get('name', 'profile')}_{a.start}_{a.end}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for c in sorted(rel, key=lambda c: c["id"]):
            f.write(json.dumps({k: v for k, v in c.items() if k != "kw"}, ensure_ascii=False) + "\n")

    short = sorted([c for c in rel if c["signals"]], key=lambda c: (-len(c["signals"]), -(c.get("hn_points") or 0),
                                                                    -(c.get("stars") or 0), -(c.get("cit") or 0)))
    print("\n".join(log))
    print(f"\n프로필 {prof['name']} · 소스 {','.join(sorted(srcs))}")
    print(f"모은 후보 {len(pool.c)} → 기간·주제 통과 {len(rel)} → 신호 기준 통과 {len(short)}  (기준 {th})")
    print(f"저장: {out.relative_to(ROOT)}\n")
    for c in short:
        print(f"{c['id']} | {(c.get('title') or '')[:80]} | ★{c.get('stars') or 0} hn{c.get('hn_points') or 0} "
              f"cit{c.get('cit') or '-'} up{c.get('upvotes') or 0} | {','.join(c['signals'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
