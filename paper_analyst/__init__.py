"""paper_analyst — 논문을 찾아 읽고, 외부 평가를 붙여 결론을 낸다.

import 로 쓰는 단계 함수 (엔진):
    from paper_analyst import profile, discover, resolve, fetch, enrich, library
    prof = profile.load()                       # 현재 프로필
    resolve.resolve("Meta-Harness: ...")        # → ("확정", "2603.28052", 제목)
    fetch.fetch_one("2603.28052", ...)          # 받기·변환 (fetch.py 참고)
    library.scan_papers(ROOT)                   # 서재 (파일 기준)
CLI:  python -m paper_analyst.<discover|resolve|fetch|enrich|profile> --help
화면: python -m paper_analyst serve
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
__all__ = ["ROOT"]
