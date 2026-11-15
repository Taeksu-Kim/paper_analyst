---
name: paper-setup
description: 논문 탐색 프로필(profiles/<이름>.toml)을 인터뷰로 만들고, 예시 논문과 시험 수집으로 보정한 뒤 현재 프로필로 지정한다. 처음 쓰는 사람이 "세팅해줘", "시작하려면?", "내 분야로 바꾸고 싶어"라고 하거나, 관심 주제·읽는 목적이 바뀌었을 때("요즘은 RAG 보다 평가 쪽이 관심", "필터가 이상한 걸 잡아"), 또는 다른 스킬이 "프로필 없음" 오류를 냈을 때 쓴다.
---

# paper-setup — 프로필 만들기·보정

paper-find 와 paper-read 는 전부 **현재 프로필**을 따른다: 어떤 소스에서 모을지, 무엇을 주제로 볼지, 어떤 관점으로 판정·정리할지,
어느 언어로 쓸지. 프로필이 사용자의 실제 관심과 어긋나면 이후 결과가 전부 어긋나므로, 질문에 답한 내용만 믿지 말고
**예시 논문으로 시험해서** 맞춘다.

작업 위치: 저장소 루트. 참고 프로필: `profiles/nlp.toml` (NLP·LLM 응용, 실무 관점 예시).

## 흐름

### 1. 인터뷰 — 한 번에 몰아 묻지 말고 2~3번에 나눠서
| 묻는 것 | 프로필에서 | 비고 |
|---|---|---|
| 분야와 세부 주제 | `description`, `interests.topics` | "LLM" 처럼 넓으면 무엇을 만들거나 연구하는지 되묻는다 |
| **좋았던 논문 2~3편, 안 맞았던 논문 1~2편** | (보정용) | 가장 강한 입력. 제목·링크 무엇이든 — `paper_analyst/resolve.py` 로 id 확정 |
| 읽는 목적 | `reader.lens`, `reader.criteria` | 실무 적용 / 연구 동향 / 공부 등. 사용자의 말로 쓴다 |
| 따라잡을 기간 | `catchup_from` | 공백이 있으면 언제부터 |
| 출력 언어 | `reader.language` | |
| 이미 아는 좋은 소스 | `sources.curated`, `watch` | 학회·정리 글·관심 모델 계열·기관 |
| (선택) 업무·연구 맥락 | `profiles/<이름>.private.md` | **공개 프로필에 넣지 않는다** — 실무 판정과 notes.private.md 에만 쓴다 |

- 사용자가 정하지 않은 관점·기준을 지어내지 않는다. 기준이 필요한데 답이 없으면 nlp.toml 의 것을 **예시로 보여 주고 고르게** 한다.
- "안 맞았던 논문"은 왜 안 맞았는지까지 묻는다 — 주제가 달라서인지(→ 필터), 관점이 달라서인지(→ `reader.criteria`).

### 2. 예시 논문 읽기
좋았던 논문들의 제목·초록(HF `https://huggingface.co/api/papers/<id>` 의 `summary`, 없으면 `python -m paper_analyst.fetch <id>` 후 `meta.json`)
에서 공통 주제어를 뽑는다. 이것이 `discover.include` 정규식과 `discover.s2_topics` 의 재료다.

### 3. 프로필 초안
`profiles/<이름>.toml` — 구조는 nlp.toml 을 따른다. 값을 정하는 법:
- `discover.include` : 제목·HF 키워드에 걸 정규식. 단어 경계(`\bagent`)로 — "presentation" 이 "representation" 에 걸린 적이 있다
- `discover.exclude` : 관심 밖 분야 (예: 비전·로봇·의료)
- `discover.sources` : HF Daily·HN 은 **AI·개발 쪽 소스**다. 다른 분야면 `["s2"]` 만. `s2_fields` 는 Semantic Scholar 분야 이름
- `discover.s2_topics` : S2 인용순 검색어 5~15개 (2단어 이상 구체적으로)
- `discover.thresholds` : 처음엔 nlp 값(★1000 / HN 100 / 인용 150)으로 두고 4단계에서 조정. 이론·비 AI 분야는 스타가 거의 없다
초안 전체를 사용자에게 보여 주고 주제·관점 문구를 확인받는다.

### 4. 시험과 보정
```bash
python -m paper_analyst.discover --profile <이름> --check <좋았던 id...> <안 맞았던 id...>
python -m paper_analyst.discover --profile <이름> --from <최근 2개월 전> --to <이번 달>
```
- **좋았던 논문이 주제 필터에서 떨어지면** include 를 넓힌다 (어느 단어가 빠졌는지 출력에 이유가 나온다)
- **좋았던 논문이 신호 기준을 하나도 못 넘으면** 그 논문은 어떤 경로로 알았는지 묻는다 → 수상·정리 글이면 `sources.curated` 에,
  기준이 높아서면 thresholds 조정 (조정한 값과 이유를 프로필 주석에 남긴다)
- 시험 수집의 신호 통과 목록을 보여 주고 "이 중 잡음은?" — 잡음의 공통점을 exclude 로
- 안 맞았던 논문이 필터를 통과하는 것 자체는 괜찮다 (주제는 맞고 관점이 다른 경우) — 그건 paper-find 의 판정 기준이 거른다
- 보정은 2~3회면 충분하다. 완벽한 필터보다 "좋았던 논문이 잡히고 잡음이 견딜 만한" 정도

### 5. 지정과 확인
```bash
python -m paper_analyst.profile --use <이름>     # profiles/active 에 기록 (git 제외)
```
출력된 요약을 사용자에게 보여 주고 끝낸다. 다음 행동으로 paper-find 를 제안한다.

## 지킬 것 (왜)
- **공개 프로필과 개인 맥락을 나눈다.** `profiles/*.toml` 은 저장소에 올라갈 수 있다 — 직무·회사·동료 이야기는 `<이름>.private.md`.
- **키·토큰은 받지 않는다.** LinkedIn 게시 등 키가 필요한 설정은 사용자가 별도 터미널에서 `python -m paper_analyst.linkedin setup`
  으로 넣는다 (`docs/LINKEDIN.md`). 채팅으로 Secret 을 받거나 대신 저장하지 않는다 — 대화 기록에 남는다.
- **임계값·정규식은 질문으로 정하지 않는다.** 사람은 "인용 150"을 판단할 수 없다 — 예시 논문 시험 결과로 정한다.
- **프로필을 바꾸면 이유를 주석에 남긴다.** 나중에 "왜 이 기준이지?"에 답할 수 있어야 다시 보정할 수 있다.
- 범위: 후보 소스와 받기(`fetch.py`)가 arXiv 기반이라 **arXiv 에 올라오는 분야**에서 동작한다. 그 밖의 분야는 할 수 있는 것과 없는 것을 먼저 말한다.
