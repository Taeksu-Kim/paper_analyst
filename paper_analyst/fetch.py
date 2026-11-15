"""arXiv 논문 받기 → library/papers/<id>/ 에 paper.pdf · meta.json, (--parse) parsed/paper.md.

    python -m paper_analyst.fetch 2604.12374 https://arxiv.org/abs/2609.05933v1 --parse
    python -m paper_analyst.fetch 2604.12374 --via pdf --layout-url http://<host>:8090   # PDF 로, 그림까지

변환 경로 (--via, 기본 auto):
- auto: arXiv HTML(LaTeXML) → 없거나 본문이 아니면 PDF + doc_parser. 2단 PDF 는 doc_parser 에서 줄 순서가 섞인다.
- html / pdf: 그 경로만 (html 이 없으면 실패).
이미 받은 PDF·변환 결과는 건너뛴다 (--force 로 다시). 버전을 지정하면 그 버전, 아니면 최신.
arXiv 요청 사이 3초(그림 파일은 1초) 간격. 종료 코드: 전부 성공 0, 하나라도 실패 1.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from paper_analyst.arxiv_html import NotLatexml, convert

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "library" / "papers"
UA = {"User-Agent": "paper_analyst/0.1 (research tool)"}
GAP_S = 3.0
IMG_GAP_S = 1.0
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
# 신형 2604.12374(v2) / 구형 cs/0101001(v1)
ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?P<ver>v\d+)?")

_last_call = 0.0


class FetchError(Exception):
    pass


def parse_id(text: str) -> tuple[str, str | None]:
    """'2604.12374v2' · 'arxiv.org/abs/..' · 'arxiv.org/pdf/...pdf' → ('2604.12374', 'v2')."""
    t = text.strip()
    t = re.sub(r"^(https?://)?(www\.)?(export\.)?arxiv\.org/(abs|pdf|html)/", "", t)
    t = re.sub(r"\.pdf$", "", t.rstrip("/"))
    m = ID_RE.fullmatch(t)
    if not m:
        raise FetchError(f"arXiv id 로 읽을 수 없음: {text!r}")
    return m["id"], m["ver"]


RETRY_WAITS = (5.0, 15.0)  # 429·503 일 때 재시도 전 대기 (Retry-After 가 더 길면 그걸 따름)


def _get(url: str, gap: float = GAP_S) -> bytes:
    global _last_call
    for attempt in range(len(RETRY_WAITS) + 1):
        wait = gap - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < len(RETRY_WAITS):
                ra = e.headers.get("Retry-After", "")
                time.sleep(max(RETRY_WAITS[attempt], float(ra) if ra.isdigit() else 0))
                continue
            raise FetchError(f"HTTP {e.code}: {url}") from e
        except urllib.error.URLError as e:
            raise FetchError(f"연결 실패: {url} ({e.reason})") from e
        finally:
            _last_call = time.monotonic()
    raise AssertionError("unreachable")


_api_down: str | None = None  # 이번 실행에서 API 가 재시도 끝에 실패 → 나머지는 바로 abs 페이지로


def fetch_meta(aid: str, ver: str | None) -> dict:
    """arXiv API → 막히면(429·503 등) 논문 페이지(arxiv.org/abs)의 메타 태그로. 없는 id 는 바로 실패."""
    global _api_down
    if _api_down is None:
        try:
            return _meta_from_api(aid, ver)
        except FetchError as e:
            if str(e).startswith("arXiv 에 없음"):
                raise
            _api_down = str(e)[:60]
    m = _meta_from_abs(aid, ver)
    m["meta_source"] = f"abs 페이지 (API 실패: {_api_down})"
    return m


def _meta_from_abs(aid: str, ver: str | None) -> dict:
    page = _get(f"https://arxiv.org/abs/{aid}{ver or ''}").decode("utf-8", "replace")

    def metas(name: str) -> list[str]:
        return [html.unescape(v) for v in re.findall(rf'<meta name="{name}" content="([^"]*)"', page)]

    title = metas("citation_title")
    if not title:
        raise FetchError(f"abs 페이지에 메타 태그 없음: {aid}")
    subj = re.search(r'tablecell subjects">(.*?)</td>', page, re.S)
    cats = re.findall(r"\(([a-z\-]+(?:\.[A-Za-z\-]+)?)\)", re.sub(r"<[^>]+>", "", subj[1])) if subj else []
    versions = [int(v) for v in re.findall(r"<strong>\[v(\d+)\]</strong>", page)]
    date = (metas("citation_date") or [""])[0].replace("/", "-")
    return {
        "arxiv_id": aid,
        "version": ver or (f"v{max(versions)}" if versions else None),
        "title": " ".join(title[0].split()),
        "authors": metas("citation_author"),  # "성, 이름" 형식 (API 는 "이름 성")
        "published": date,
        "updated": date,
        "primary_category": cats[0] if cats else None,
        "categories": cats,
        "abstract": " ".join((metas("citation_abstract") or [""])[0].split()),
        "abs_url": f"https://arxiv.org/abs/{aid}",
    }


def _meta_from_api(aid: str, ver: str | None) -> dict:
    xml = _get(f"https://export.arxiv.org/api/query?id_list={aid}{ver or ''}&max_results=1")
    entries = ET.fromstring(xml).findall("a:entry", NS)
    e = entries[0] if entries else None
    # 없는 id 면 arXiv 는 entry 없이 주거나 title=Error 인 entry 를 준다
    if e is None or e.find("x:primary_category", NS) is None:
        raise FetchError(f"arXiv 에 없음: {aid}{ver or ''}")
    abs_url = e.find("a:id", NS).text.strip()
    latest = re.search(r"(v\d+)$", abs_url)
    return {
        "arxiv_id": aid,
        "version": ver or (latest[1] if latest else None),
        "title": " ".join(e.find("a:title", NS).text.split()),
        "authors": [a.find("a:name", NS).text for a in e.findall("a:author", NS)],
        "published": e.find("a:published", NS).text[:10],
        "updated": e.find("a:updated", NS).text[:10],
        "primary_category": e.find("x:primary_category", NS).get("term"),
        "categories": [c.get("term") for c in e.findall("a:category", NS)],
        "abstract": " ".join(e.find("a:summary", NS).text.split()),
        "abs_url": f"https://arxiv.org/abs/{aid}",
    }


def fetch_one(text: str, parse: bool, via: str, layout_url: str | None, force: bool,
              reparse: bool = False) -> dict:
    aid, ver = parse_id(text)
    d = LIBRARY / aid.replace("/", "_")
    meta_p, pdf_p = d / "meta.json", d / "paper.pdf"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else None
    if ver and meta and meta.get("version") != ver:
        force = True  # 다른 버전을 요청 → 다시 받는다

    status = "skip"
    if force or meta is None or not pdf_p.exists():
        meta = fetch_meta(aid, ver)
        pdf = _get(f"https://arxiv.org/pdf/{aid}{meta['version'] or ''}")
        if not pdf.startswith(b"%PDF"):
            raise FetchError(f"PDF 가 아님 ({pdf[:40]!r}): {aid}")
        d.mkdir(parents=True, exist_ok=True)  # 메타·PDF 둘 다 성공한 뒤에만 폴더를 만든다
        tmp = pdf_p.with_suffix(".pdf.part")
        tmp.write_bytes(pdf)
        tmp.replace(pdf_p)
        (d / "paper.html").unlink(missing_ok=True)  # 다른 버전의 HTML 이 남지 않게
        meta["pdf_bytes"] = len(pdf)
        meta["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        meta.pop("parsed", None)
        status = "downloaded"

    p = meta.get("parsed")
    if parse and (force or reparse or status == "downloaded" or not p
                  or (via == "html" and p.get("source") != "arxiv_html")
                  or (via == "pdf" and p.get("source") != "pdf")
                  or (layout_url and p.get("source") == "pdf" and not p.get("layout"))):
        meta["parsed"] = parse_paper(d, meta, via, layout_url, force)
        status += f"+{meta['parsed']['source']}"

    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return {"id": aid, "dir": str(d), "status": status, "title": meta["title"]}


def parse_paper(d: Path, meta: dict, via: str, layout_url: str | None, force: bool) -> dict:
    """parsed.tmp/ 에 만들고 성공하면 parsed/ 와 바꾼다 — 실패해도 이전 결과가 남는다."""
    out, tmp = d / "parsed", d / "parsed.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    fallback, r = None, None
    if via in ("auto", "html"):
        try:
            r = run_html(d, meta, tmp, force)
        except (FetchError, NotLatexml) as e:
            shutil.rmtree(tmp, ignore_errors=True)
            if via == "html":
                raise FetchError(f"HTML 경로 실패: {e}") from e
            fallback = str(e)
    if r is None:
        r = run_parser(d / "paper.pdf", tmp, layout_url)
        if fallback:
            r["html_unavailable"] = fallback
    shutil.rmtree(out, ignore_errors=True)  # 이전 경로(html/pdf)의 산출물이 섞이지 않게
    tmp.rename(out)
    r["md"] = "parsed/paper.md"
    return r


def run_html(d: Path, meta: dict, out: Path, force: bool) -> dict:
    base = f"https://arxiv.org/html/{meta['arxiv_id']}{meta['version'] or ''}"
    html_p = d / "paper.html"
    if force or not html_p.exists():
        html_p.write_bytes(_get(base))
    conv = convert(html_p.read_text(encoding="utf-8", errors="replace"), base)
    warnings = list(conv.warnings)
    saved = 0
    if conv.images:
        (out / "images").mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    text = conv.md
    for url, name in conv.images:
        try:
            f = out / "images" / name
            f.write_bytes(_get(url, gap=IMG_GAP_S))
            saved += 1
        except FetchError as e:
            warnings.append(f"그림 못 받음: {name} ({e})")
            continue
        if f.suffix.lower() == ".svg":  # Claude 는 SVG 를 그림으로 못 봄 → PNG 로, md 링크도 바꿈
            png = svg_to_png(f)
            if png:
                text = text.replace(f"images/{name})", f"images/{png.name})")
            else:
                warnings.append(f"SVG→PNG 실패: {name}")
    md = out / "paper.md"
    md.write_text(text, encoding="utf-8")
    return {
        "source": "arxiv_html",
        "md_chars": len(text),
        "images": saved,
        "warnings": warnings,
    }


def svg_to_png(svg: Path) -> Path | None:
    """긴 변 1000px 이상으로 렌더링. 실패하면 None (SVG 는 남겨 둔다)."""
    import pymupdf
    try:
        doc = pymupdf.open(svg)
        page = doc[0]
        zoom = max(1.0, 1000 / max(page.rect.width, page.rect.height, 1))
        png = svg.with_suffix(".png")
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(png)
        return png
    except (RuntimeError, ValueError, pymupdf.FileDataError):
        return None


def run_parser(pdf: Path, out: Path, layout_url: str | None) -> dict:
    cmd = [sys.executable, "-m", "doc_parser", str(pdf), "--extract-output", str(out)]
    if layout_url:
        cmd += ["--layout-url", layout_url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise FetchError(f"doc_parser 실패 ({r.returncode}): {r.stderr.strip()[-300:]}")
    md = out / "paper.md"
    em = json.loads((out / "meta.json").read_text()) if (out / "meta.json").exists() else {}
    return {
        "source": "pdf",
        "layout": bool(layout_url),
        "md_chars": len(md.read_text()) if md.exists() else 0,
        "images": len(list((out / "images").glob("*.png"))) if (out / "images").exists() else 0,
        "warnings": em.get("warnings", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="+", help="arXiv id 또는 abs/pdf/html URL")
    ap.add_argument("--parse", action="store_true", help="텍스트 변환 (parsed/paper.md)")
    ap.add_argument("--via", choices=["auto", "html", "pdf"], default="auto",
                    help="변환 경로: auto=HTML 먼저, 없으면 PDF (기본)")
    ap.add_argument("--layout-url", help="PDF 경로에서 doc_parser 레이아웃 서버 (doc_reader/doc_parser/tools/ocr.sh start 출력 주소)")
    ap.add_argument("--force", action="store_true", help="이미 있어도 다시 받고 다시 변환")
    ap.add_argument("--reparse", action="store_true",
                    help="받아 둔 paper.html·paper.pdf 로 변환만 다시 (변환기를 고쳤을 때)")
    a = ap.parse_args()
    parse = a.parse or a.reparse or bool(a.layout_url) or a.via != "auto"

    failed = []
    for text in dict.fromkeys(a.ids):  # 같은 입력 중복 제거, 순서 유지
        try:
            r = fetch_one(text, parse, a.via, a.layout_url, a.force, a.reparse)
            print(f"{r['status']:<24} {r['id']:<12} {r['title'][:70]}")
        except FetchError as e:
            failed.append(text)
            print(f"{'FAILED':<24} {text:<12} {e}", file=sys.stderr)
    if failed:
        print(f"\n실패 {len(failed)}건: {' '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
