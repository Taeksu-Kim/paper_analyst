# 논문 소스 판단 (NLP 프로필 기준)

> 작성 2026-11-14 KST. 아래 숫자는 **이 날 API로 직접 측정**한 값(HF·Semantic Scholar·arXiv·
> paperswithcode.co). 수상 내역은 학회 공식 페이지 또는 웹 검색 2차 출처 — 항목마다 표시.
> 설정값은 `profiles/nlp.toml`.

## 결론

**시기별로 소스를 나눈다.** 지난 구간(발표 3개월+)은 학계가 이미 걸러낸 신호로, 최근(3개월 미만)은 화제성 + 관심 목록으로.

| 시기 | 주 소스 | 보조 |
|---|---|---|
| 따라잡기 (프로필 catchup_from ~ 발표 3개월 전) | 주제별 서베이 → S2 인용 상위 → 학회 수상작 | 전문가 정리 글, HF 는 제목만 (어떤 모델이 나왔나) |
| 최근 (3개월 미만) | HF upvote 넓게(20+) + 관심 목록 | 이미 나온 수상작 |
| 앞으로 | 열 때마다 HF 주간 + 관심 목록 | 학회 끝날 때 수상작, 분기별 인용 재확인 (예약 실행 없음) |

모든 경로는 arXiv id 로 합치고, 논문마다 **어느 경로·어떤 등급으로 들어왔는지** 태그를 남긴다
(여러 경로에서 잡히면 강한 신호).

## 근거 (2026-11-14 측정)

### 1. HF upvote 와 인용은 따로 논다
- HF 2026-01~11 월별 상위 100 합집합(1,100편) → 연간 상위 300 (300위 upvote 86, 월별 100위 최대 52 → 누락 없음)
- 그 300편의 S2 인용 수와 Spearman **0.19**
- 인용은 시간이 필요: 월별 인용 중앙값 1월 19 / 4월 22.5 / 7월 6.5 / 10월 0.5 → **3개월 미만은 인용 판단 불가**

### 2. HF 상위권은 대형 모델 보고서가 차지
- 연간 상위: Kimi K3(526), mHC(333), Kimi K2.5(277), ERNIE 5.0(266) …
- S2 "language model / LLM agent / RAG / agent memory" 2026 인용 상위 30편 중 **HF 상위 300 에 든 것 5편**
- 빠진 것: Meta-Harness(인용 382, upvote 21), SkillsBench(370, 69), SkillRL(328, 72), Trace2Skill(224, 52),
  자기 증류 계열 4~5편(upvote 1~52)

### 3. 선별 목록은 HF 에서 거의 안 보인다
| 논문 | 선별 근거 | HF upvote |
|---|---|---|
| Rethinking MAS Efficiency Eval (2609.05933) | EMNLP 2026 Outstanding (공식 페이지 확인) | HF 페이지 없음 |
| SWE-MEM (2606.28434) | EMNLP 2026 SAC Highlight (공식) | HF 페이지 없음 |
| HarnessForge (2606.01779) | EMNLP 2026 SAC Highlight (공식) | 8 |
| Nemotron 3 Super (2604.12374) | Raschka "한 편만 고르면" | 38 |
| LLMs Get Lost In Multi-Turn (2505.06120) | ICLR 2026 Outstanding (공식 블로그) | 7 |
| The Imperfective Paradox in LLMs (2601.09373) | ACL 2026 Best (2차 출처) | HF 페이지 없음 |

- Nemotron 3 계열 전체 upvote 19~44, 주 카테고리 cs.LG → upvote·인용·cs.CL 필터 **모두** 탈락. 관심 목록(키워드 검색)으로만 잡힘.

### 4. 소스별 특성
| | HF Papers | paperswithcode.co | Semantic Scholar |
|---|---|---|---|
| 운영 | HF | **HF** (JS 번들에 huggingface/paperswithcode) | AI2 |
| API | 공개 `huggingface.co/api` | 비공개 `/api/v1` (예고 없이 바뀔 수 있음) | 공개 Graph API, 키 없으면 429 잦음 |
| 기간 목록 | `daily_papers?date=/week=/month=`, limit ≤ 100(1000 → 400), `p=` 페이지 | 최근 14일·trending 2,010편 | 검색 `year=` |
| 검색 | `papers/search?q=` (agent memory → 120) | `papers/?search=` (→ 13). `q=` `title=` 무시됨 | `paper/search/bulk` 인용순 정렬 |
| 분야 필터 | 없음 → arXiv 카테고리 조회로 보완 | tasks 290개 (분류 부정확: language-modeling 에 로봇 논문) | fieldsOfStudy |
| 고유 정보 | upvote, ai_summary, githubRepo/Stars | tldr, tasks, methods, 벤치마크 순위, HF 모델·데이터셋 | 인용, 영향력 인용 |

- upvote 주의: Daily 에는 저자가 직접 올리는 경우가 많다(EgoX: 올린 사람 = 공저자). 기관 규모·홍보 영향.
- arXiv 카테고리: Agent·Harness 논문 상당수가 cs.AI / cs.LG. "주 카테고리 cs.CL" 로 거르면 놓침.
  (상위 300 중 cs.CV 89 · cs.AI 71 · cs.CL 59)
- **HN 점수는 화제성이지 품질이 아니다** (2026-11-15): 실무 재조사에서 HN 을 실무 신호로 썼는데, *Is Grep All You Need?* (HN 164) 는
  1회 실행·벡터 설정 미기재·같은 조건 두 실험의 결과가 9개 중 5개 뒤집힘·미완 행이 있는 빠른 실험 보고였다. HN·스타로 고른 논문은
  본문에서 **반복 실행 여부와 기준선 설정부터** 확인한다. (`library/papers/2605.15184/notes.md`)
- S2 메타데이터 이상: 2024년 Anthropic "Scaling Monosemanticity" 가 2026 논문(인용 952)으로 잡힘 → 인용 상위는 발표일 재확인.

## 미확인
- 2025 년 구간은 아직 조회 안 함 (HF 월 API 가 2025 월에도 되는지 확인 전)
- ACL 2026 공식 수상 페이지 못 찾음 (2026.acl.org DNS 없음, aclweb 404). ImplicitMemBench "Best Resource" 미확인
- NeurIPS 2025 수상작 미조사

## 출처
- EMNLP 2026 Awards (공식): https://2026.emnlp.org/program/awards/
- ICLR 2026 Outstanding Papers: https://blog.iclr.cc/2026/04/23/announcing-the-iclr-2026-outstanding-papers/
- ICML 2026 Awards: https://blog.icml.cc/?p=1347
- Raschka, LLM Research Papers 2026 (Jan–May): https://magazine.sebastianraschka.com/p/llm-research-papers-2026-part1
- ACL 2026 수상(2차): https://www.nii.ac.jp/en/news/release/2026/0722.html , https://www.36kr.com/p/3888326643104513
