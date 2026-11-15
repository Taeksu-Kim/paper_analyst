# paper_analyst — 작업 규칙

- **PDF 를 Read 로 직접 열지 않는다.** `paper_analyst/fetch.py --parse` 로 변환한 `library/papers/<id>/parsed/paper.md` 를
  절 단위로 읽는다 (`grep -n '^#'` 로 목차 먼저 → 필요한 절만). 그림은 `parsed/images/` 에서 필요한 것만.
- 변환 경로는 `meta.json` 의 `parsed.source` 로 확인. `pdf` 면 2단 논문의 줄 순서가 섞였을 수 있다.
- 변환기(`paper_analyst/arxiv_html.py`)를 고치면 `--reparse` 로 기존 논문을 다시 변환하고 산출물을 확인한다.
- 소스 선택·설정은 `docs/SOURCES.md` 와 `profiles/<분야>.toml`. 관심 주제·관심 목록은 **사용자가 정한다** — 임의로 추가하지 않는다.
- 외부 API 는 몰아 호출하지 않는다: arXiv 3초, S2 3~4초(키 없음, 429 시 물러남), HF 1초 간격. 한 건씩.
- 논문 수치·수상 내역을 보고할 때 측정/인용/미확인을 구분하고, 수상은 **등급**(Best / Outstanding / SAC Highlight /
  개인 추천)을 같이 적는다.
- **공개 저장소다.** `notes.md`·`ideas/`·`lists/` 에는 논문 내용과 일반 원리만 쓴다. 사용자의 회사·업무·경력·동료·큐레이터 등
  개인 맥락은 같은 이름의 `*.private.md` 에 (git 제외). 원문(PDF·HTML·parsed)은 커밋하지 않는다.
- 논문 기간 조건은 **arXiv 발표일 기준**으로 엄격히 ("올해" = 올해 발표). 수상 시점으로 넓히지 않는다.
- 도구는 `python -m paper_analyst.<도구>` (패키지). 화면은 `python -m paper_analyst serve` (127.0.0.1:8768).
- 화면을 고치면 `python tools/browser_check.py` (n/m PASS) 와 `python -m pytest tests -q` 를 돌리고 스크린샷을 직접 본다.
- 화면의 Claude Code 세션 권한은 `paper_analyst/chat.py` 의 `ALLOWED` 하나에서만 정한다. 읽기도 `Read(./**)` 처럼 경로를 붙인다
  (경로 없는 `Read` 는 디스크 전체를 허용 — 실측). 파일 쓰기 규칙은 `Edit(<경로>/**)` 형태
  (실측: `Write(...)` 로는 허용이 안 됨). 공통 CLAUDE.md 때문에 파이썬을 절대경로로 부르므로 두 형태를 다 허용한다.
