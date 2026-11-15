"""논문 제목·링크 → arXiv id (큐레이터 글, 블로그, 메모에서 가져온 목록용).

    python -m paper_analyst.resolve "Multi-Token Prediction Done Right" "https://arxiv.org/abs/2605.15184"
    python -m paper_analyst.resolve < titles.txt          # 한 줄에 하나

- arXiv 링크(abs/pdf/html)는 id 를 바로 읽는다.
- 제목은 HF 검색 → 없으면 arXiv 제목 검색. **정규화한 제목이 정확히 같을 때만** 확정한다.
  비슷한 제목만 있으면 "확인 필요"와 후보를 보여 준다 — 부분 일치로 엉뚱한 논문에 붙는 일을 막는다
  (예: "System One Models Are Not Better Rerankers" 를 "... Order-Invariant Decisions in System One Models" 로 잘못 매칭).
출력: 입력 \t 상태(확정|확인 필요|못 찾음) \t arXiv id \t 찾은 제목
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "paper_analyst/0.1 (research tool)"}
_last = 0.0


def _get(url: str, gap: float) -> str | None:
    global _last
    wait = gap - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        _last = time.monotonic()


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(t or "").lower()).strip()


def resolve(text: str) -> tuple[str, str, str]:
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", text)
    if m:
        return "확정", m.group(1), "(링크)"
    want = norm(text)
    cands: list[tuple[str, str]] = []
    r = _get("https://huggingface.co/api/papers/search?q=" + urllib.parse.quote(text), 1.2)
    try:
        for x in json.loads(r or "[]"):
            p = x.get("paper", x)
            cands.append((p.get("id", ""), p.get("title", "")))
    except json.JSONDecodeError:
        pass
    hit = [c for c in cands if norm(c[1]) == want]
    if not hit:   # arXiv 제목 검색 (HF 에 없는 논문)
        q = urllib.parse.quote(f'ti:"{text}"')
        xml = _get(f"https://export.arxiv.org/api/query?search_query={q}&max_results=5", 3.0) or ""
        for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
            i = re.search(r"<id>https?://arxiv\.org/abs/(\d{4}\.\d{4,5})", e)
            t = re.search(r"<title>(.*?)</title>", e, re.S)
            if i and t:
                cands.append((i.group(1), " ".join(t.group(1).split())))
        hit = [c for c in cands if norm(c[1]) == want]
    if hit:
        return "확정", hit[0][0], hit[0][1]
    words = set(want.split())
    overlap = lambda c: len(set(norm(c[1]).split()) & words) / max(len(words), 1)
    best = max(cands, key=overlap, default=None)
    if best and overlap(best) >= 0.5:   # 단어 절반 이상 겹칠 때만 후보로 보여 준다 (그 아래는 잡음)
        return "확인 필요", best[0], best[1]
    return "못 찾음", "", ""


def main() -> int:
    items = sys.argv[1:] or [l.strip() for l in sys.stdin if l.strip()]
    for it in items:
        status, aid, title = resolve(it)
        print(f"{it}\t{status}\t{aid}\t{title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
