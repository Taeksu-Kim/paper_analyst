"""arXiv HTML(LaTeXML) → 마크다운. 2단 PDF 의 읽기 순서 문제를 피하려고 PDF 보다 먼저 쓴다.

convert(html, base_url) -> Converted(md, images=[(url, 파일명)], warnings)
- 제목 h1~h5 → #~#####, 수식 → $alttext$ / $$…$$, 표 → 마크다운 표(rowspan·colspan 펼침, 굵게 유지),
  그림 → ![](images/파일명) + 캡션, 각주 → [fn: …] 본문 안, 코드 → ``` 블록, 참고문헌 → 목록.
- 네트워크를 쓰지 않는다 (그림 받기는 호출하는 쪽).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

SKIP_TAGS = {"script", "style", "button", "nav", "header", "footer", "noscript"}
SKIP_CLASSES = {"ltx_note_mark", "ltx_tag_note", "ltx_tag_item", "ltx_page_footer", "ltx_dates",
                "ltx_role_institutetext", "ltx_eqn_eqno",
                "ltx_authors"}  # 저자는 meta.json(arXiv API)에 깨끗하게 있다 — HTML 쪽은 각주·소속이 섞임


class NotLatexml(Exception):
    """HTML 이 있지만 LaTeXML 본문(article.ltx_document)이 아님 — 'HTML 없음' 안내 페이지 등."""


@dataclass
class Converted:
    md: str
    images: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _Conv:
    def __init__(self, base_url: str):
        self.base = base_url
        self.images: dict[str, str] = {}  # url -> 파일명

    # ── 인라인 ──────────────────────────────────────────
    def inline(self, el: Tag) -> str:
        parts: list[str] = []
        for c in el.children:
            if isinstance(c, Comment):
                continue
            if isinstance(c, NavigableString):
                parts.append(str(c))
                continue
            if not isinstance(c, Tag) or c.name in SKIP_TAGS:
                continue
            cls = set(c.get("class", []))
            if cls & SKIP_CLASSES:
                continue
            if c.name == "math":
                alt = (c.get("alttext") or c.get_text()).strip()
                parts.append(f" ${alt}$ " if alt else "")
            elif "ltx_role_footnote" in cls:
                body = c.select_one(".ltx_note_content")
                t = self.inline(body) if body else ""
                parts.append(f" [fn: {t}]" if t else "")
            elif c.name == "img" or (c.name == "object" and c.get("data")):
                parts.append(f" ![]({self.image(c)}) ")
            elif "ltx_tag" in cls:  # 절·그림 번호 "1" + "Introduction" 이 붙지 않게
                t = self.inline(c)
                parts.append(f"{t} " if t else "")
            elif c.name == "br":
                parts.append(" ")
            elif c.name in ("b", "strong") or "ltx_font_bold" in cls:
                t = self.inline(c)
                parts.append(f"**{t}**" if t else "")
            else:
                parts.append(self.inline(c))
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def image(self, img: Tag) -> str:
        url = urljoin(self.base, img.get("src") or img.get("data") or "")
        if url not in self.images:
            name = re.sub(r"[^\w.\-]", "_", url.rstrip("/").rsplit("/", 1)[-1]) or "img"
            if name in self.images.values():
                name = f"{len(self.images)}_{name}"
            self.images[url] = name
        return f"images/{self.images[url]}"

    # ── 블록 ────────────────────────────────────────────
    def blocks(self, el: Tag, out: list[str]) -> None:
        for c in el.children:
            self.block(c, out)

    def block(self, c, out: list[str]) -> None:
        """자식 노드 하나를 블록으로."""
        if isinstance(c, Comment):
            return
        if isinstance(c, NavigableString):
            t = re.sub(r"\s+", " ", str(c)).strip()
            if t:
                out.append(t)
            return
        if not isinstance(c, Tag) or c.name in SKIP_TAGS:
            return
        cls = set(c.get("class", []))
        if cls & SKIP_CLASSES:
            return
        name = c.name
        if name == "img" or (name == "object" and c.get("data")):
            out.append(f"![]({self.image(c)})")
        elif re.fullmatch(r"h[1-6]", name):
            t = self.inline(c)
            if "ltx_title_abstract" in cls:
                out.append("## Abstract")
            elif t:
                out.append("#" * min(int(name[1]), 5) + " " + t)
        elif name == "figure":
            self.figure(c, out)
        elif name == "table" and cls & {"ltx_equation", "ltx_equationgroup", "ltx_eqn_table"}:
            eqs = [(m.get("alttext") or "").strip() for m in c.find_all("math")]
            eqs = [e for e in eqs if e]
            if eqs:
                out.append("$$\n" + " \\\\\n".join(eqs) + "\n$$")
        elif name == "table":
            tbl = self.table(c)
            if tbl:
                out.append(tbl)
        elif name in ("ul", "ol"):
            self.list_(c, out, ordered=(name == "ol"))
        elif "ltx_listing" in cls:
            lines = [ln.get_text() for ln in c.select(".ltx_listingline")] or [c.get_text()]
            out.append("```\n" + "\n".join(l.rstrip() for l in lines).strip("\n") + "\n```")
        elif name == "p" or "ltx_p" in cls:
            t = self.inline(c)
            if t:
                out.append(t)
        elif name in ("div", "section", "span", "article", "blockquote", "tbody", "thead", "center"):
            self.blocks(c, out)
        else:
            t = self.inline(c)
            if t:
                out.append(t)

    def figure(self, fig: Tag, out: list[str]) -> None:
        for c in fig.children:
            if isinstance(c, Tag) and c.name == "figcaption":
                continue
            self.block(c, out)
        for cap in fig.find_all("figcaption", recursive=False):
            t = self.inline(cap)
            if t:
                out.append(f"> {t}")

    def list_(self, ul: Tag, out: list[str], ordered: bool) -> None:
        n = 0
        for li in ul.find_all("li", recursive=False):
            n += 1
            sub: list[str] = []
            self.blocks(li, sub)
            if not sub:
                continue
            mark = f"{n}." if ordered else "-"
            first, rest = sub[0], sub[1:]
            out.append(f"{mark} {first}" + "".join("\n  " + r.replace("\n", "\n  ") for r in rest))

    def table(self, tbl: Tag) -> str:
        rows = [tr for tr in tbl.find_all("tr") if tr.find_parent("table") is tbl]
        grid: dict[tuple[int, int], str] = {}
        for r, tr in enumerate(rows):
            c = 0
            for cell in tr.find_all(["td", "th"], recursive=False):
                while (r, c) in grid:
                    c += 1
                rs = max(1, int(cell.get("rowspan", 1) or 1))
                cs = max(1, int(cell.get("colspan", 1) or 1))
                text = self.inline(cell).replace("|", "\\|")
                for dr in range(rs):
                    for dc in range(cs):
                        grid[(r + dr, c + dc)] = text if dr == 0 and dc == 0 else ""
                c += cs
        if not grid:
            return ""
        nr = max(k[0] for k in grid) + 1
        nc = max(k[1] for k in grid) + 1
        lines = []
        for r in range(nr):
            lines.append("| " + " | ".join(grid.get((r, c), "") for c in range(nc)) + " |")
            if r == 0:
                lines.append("|" + "---|" * nc)
        return "\n".join(lines)


def convert(html: str, base_url: str) -> Converted:
    soup = BeautifulSoup(html, "html.parser")
    art = soup.find("article", class_="ltx_document")
    if art is None:
        raise NotLatexml("article.ltx_document 없음")
    conv = _Conv(base_url)
    out: list[str] = []
    conv.blocks(art, out)
    warnings = []
    n_err = len(art.select(".ltx_ERROR"))
    if n_err:
        warnings.append(f"LaTeXML 변환 오류 표시 {n_err}곳 (.ltx_ERROR)")
    n_unparsed = len(art.select("math.ltx_math_unparsed"))
    if n_unparsed:
        warnings.append(f"파싱 안 된 수식 {n_unparsed}개 (alttext 원문으로 둠)")
    # 제목을 맨 앞으로 (앞에 라이선스 문구·처리 안 된 매크로가 오는 논문이 있다)
    title = next((i for i, b in enumerate(out) if b.startswith("# ")), None)
    if title:
        out.insert(0, out.pop(title))
    md = "\n\n".join(out).strip() + "\n"
    return Converted(md=md, images=list(conv.images.items()), warnings=warnings)
