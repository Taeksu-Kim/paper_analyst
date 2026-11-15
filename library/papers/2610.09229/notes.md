# Conditional Accuracy Profiles: Diagnosing LLM Judges across Deployment Conditions

- arXiv 2610.09229v1 · 발표 2026-10-06 · cs.LG · 학회·수상 확인 안 함 (부록 N 에 "camera-ready" 언급만 있고 학회명 없음)
- 변환 html · 읽은 범위: 초록, §1 서론, §3 방법(3.1–3.3), §4 실험(4.1–4.3), §5 논의, §6 결론, §7 한계, 부록 N(공개 목록)
- 정리 2026-11-15 KST

## 먼저 — 용어와 구조
- **대상은 pairwise judge** — 질문 하나에 답 A·B 를 주고 "어느 쪽이 나은가"를 고르게 하는 판정. 점수형(scalar)·루브릭 채점은 다루지 않는다.
- **CAP (Conditional Accuracy Profiling)** = 새 지표가 아니라 *정확도를 조건별로 쪼개 보고하는 방식*. 8개 조건:
  - 내용 민감도 C1–C4: 사실 날조 / 논리 뒤집기 / 범위 과장(overclaim) / **범위 누락(omission, 단서·조건을 빼먹은 답)** — 각 유형의 오류가 심긴 답을 골라내는 비율
  - 강건성 C5–C7: 문체 다듬기 / 길이 부풀리기 / A·B 순서 바꾸기 — **"두 변형 모두 정답"이어야 1** (일관되게 틀려도 0, strict)
  - C8 설명 품질: 정답을 맞힌 건에 한해, 근거 설명이 실제 오류를 짚었는지를 별도 LLM(Claude Sonnet 4.6)이 판정
- **coverage 표**: 벤치마크마다 각 조건을 직접(direct) / 근사(기존 과제 부분집합을 대용) / 증강(변형 생성) / 불가 로 표시. 근사·증강 값은 주 표 평균에 섞지 않는다.
- **judgerEva-Standard**: 저자들이 만든 시험장. 정답 해설(A)과 한 가지 오류를 심은 해설(B)을 GPT-4o 로 생성 → 8조건을 같은 문항에서 모두 잴 수 있다. Hard-Empirical(N=245, *평가 대상 judge 중 하나라도 틀린 문항*이라 순환 의존) / Hard-Constructed(N=139, judge 와 무관하게 Gemini 2.5 Pro 로 난이도를 올림)로 나뉜다.
- 평가 judge 7개: GPT-4o, GPT-4o-mini, Claude Sonnet 4.5, Claude Haiku 4.5, Gemini 2.5 Pro/Flash, Llama-3.3-70B.

## 결론
**"judge 를 정확도 한 숫자로 고르지 말고 실패 유형별로 쪼개 보라"는 주장을 7개 judge × 6개 벤치마크로 보여 준 진단 프레임워크. 방법론(쪼개는 방식·strict 강건성·coverage 표기)은 바로 쓸 만하지만, 개별 judge 순위·수치는 n=7·소표본·합성 오류에 묶인 시점 스냅샷이다.**
- **가져갈 것:** (1) 순서 바꿈 강건성을 "양쪽 순서 모두 정답" 으로 재는 strict 기준 (2) 정확도 × 설명 품질 = "맞고 근거도 맞는 비율"(supported-correct rate) — 조건부 설명 점수가 적게 맞힌 judge 를 과대평가하는 걸 막는다 (3) 오류 유형을 심은 합성 쌍으로 judge 를 시험하는 설계, 특히 **누락형 오류는 전체 정확도와 따로 재야 한다** (4) 근사·증강 측정을 직접 측정과 섞지 않는 coverage 표기. 모두 학습 없이 평가 하네스에 넣을 수 있다.
- **믿어도 되는 결과:** 순서 강건성 순위는 6개 벤치마크 사이에서 잘 옮겨간다(평균 Spearman 0.87, 15쌍 중 12쌍 p<0.05). 2차 생성기(Claude)로 다시 만든 문항에서도 조건별 순위는 유지(ρ≥0.84, C1–C3·C7) — 단 절대값은 생성기에 따라 최대 40점 달라짐.
- **해석에 주의할 결과:** "가장 정확한 judge 가 누락 탐지엔 약하다" — Hard-Empirical 의 Sonnet–Haiku 차(11.3점)는 judge 독립 부분집합에서 사라졌고, 남은 근거는 n=7 의 ρ=−0.33(저자도 '기술적'이라 함)과 C4 n=30 의 넓은 CI. "Gemini 가 adversarial stress 에 Claude 보다 강하다"는 JudgeBench-Pro 하나에서의 결과. C8 은 사람 1명(평가자 라벨을 본 상태)·120건으로만 검증.
- **읽는다면:** §3.1 표 1(8조건 정의), §4.1 "Rationale-quality evidence" 단락(supported-correct rate), 표 2(coverage). 나머지는 이 notes 로 충분.

## 한 줄 요약
pairwise LLM judge 의 정확도를 내용 민감도 4 · 강건성 3 · 설명 품질 1 의 8조건으로 분해하고, 이를 모두 잴 수 있는 합성 벤치마크(judgerEva-Standard)와 벤치마크별 측정 가능 여부 표를 함께 제시했다.

## 문제와 핵심 아이디어
judge 성능은 보통 정확도·일치율 하나로 보고되어, 전체 정확도가 비슷한 두 judge 가 서로 다른 이유로 실패해도 구별이 안 된다. 기존 벤치마크도 카테고리별 정확도를 내긴 하지만 벤치마크마다 분류가 달라 서로 비교할 수 없다.
CAP 는 공통 조건 분류(8개)를 정하고, 각 벤치마크가 그 조건을 직접/근사/증강/불가 중 어떻게 지원하는지 명시해 judge·벤치마크 사이 비교를 가능하게 한다.
기존 벤치마크는 두 답의 차이가 어떤 종류의 오류인지 정해져 있지 않고(다른 모델이 쓴 답이라 문체 차도 섞임), 그래서 오류 유형을 하나만 심은 짝을 직접 만들었다.

## 저자 주장
- 8조건은 서로 중복되지 않는다 — Scope-Omission 순위는 Factual Sensitivity 와 거의 반대(ρ=−0.86), 두 범위 조건끼리도 음의 상관(ρ=−0.32) (§3.1, 부록 G)
- 생성기(GPT-4o)가 judge 로서 유리하지 않다 — judgerEva 전체 정확도 7개 중 6위 (§3.2, 부록 L)
- 전체 judgerEva 에서는 대부분 judge 가 대부분 조건에서 90% 초과 → 천장 효과라 Hard 부분집합으로 비교 (§4.1)
- Hard-Empirical: Sonnet 4.5 가 전체 89.7% 로 1위, 8조건 중 5개 1위지만 Scope-Omission 59.2% 로 Haiku 4.5(70.5%)보다 11.3점 낮음 (표 3)
- judge 간 격차는 Factual 79.9점, Length 74.1점, Position 71.2점으로 크고 Scope-Omission 14.1점으로 가장 작다 → 변별력의 상당 부분이 표현(presentation) 민감도에 있다 (§4.1)
- 설명 품질: GPT-4o-mini 의 조건부 C8=75.0 은 supported-correct rate 로는 20.3%, Sonnet 4.5 는 85.7 → 76.9% (§4.1)
- C8 평가자는 사람 1명 대비 91.7% 일치, κ=0.826, 오류는 한쪽(거짓 양성 0, 거짓 음성 12.8%, 주로 누락형) → C8 은 하한으로 읽으라 (§4.1, 부록 C)
- Hard-Constructed(judge 독립): 누락 탐지 상위 둘(Llama-3.3-70B 56.7%, GPT-4o-mini 51.7%)이 전체 정확도 5위·7위, 전체 1위 Sonnet 4.5(76.3%)는 누락 36.7%. 전체 정확도–누락 순위 상관 ρ=−0.33 (표 4)
- JudgeBench 에서는 Gemini 2.5 Pro 가 1위로 순위가 뒤집힘 — 과제 분포에 따라 읽어야 한다 (표 5)
- 순서 강건성 순위의 벤치마크 간 평균 Spearman 0.87(범위 0.71–1.00), JudgeBench 와 JudgeBench-Pro 는 순위 동일(ρ=1.00) (§4.2, 부록 F)
- JudgeBench → JudgeBench-Pro 하락: Gemini 2.5 Pro/Flash 평균 10.9/15.6점, Claude Haiku 4.5 47.0점(최대). 조건 평균으론 C7 30.7 > C1 28.4 > C2 25.1 이지만 C7 이 최대 하락인 judge 는 7개 중 2개뿐 (표 6, §4.3)
- 같은 계열 소형 모델은 대형의 대체재가 아니다 — GPT-4o-mini 는 JudgeBench Knowledge 에서 GPT-4o 와 같지만(60.7 vs 60.7) judgerEva Hard C1 에서 28.0점 뒤짐 (§5)

## 실험에서 볼 것
- **천장 효과 때문에 주 결과는 전부 Hard 부분집합.** Hard-Empirical 은 평가 대상 judge 가 틀린 문항으로 골랐으니 그 judge 들의 순위 비교에 편향이 있다 — 저자도 인정하고 Hard-Constructed 로 재검증했는데, 거기서 대표 사례(Sonnet vs Haiku 누락 격차)가 사라졌다.
- **표본이 작다.** Hard-Empirical C2 의 CI 가 38–69, 70–100 처럼 넓고, C8 은 33–100. 표 3 의 굵은 글씨(1위) 중 상당수는 CI 가 겹친다.
- **오류가 모두 LLM 이 심은 합성 오류.** 사람이 실제로 만드는 누락·과장과 같은 분포인지는 확인 안 됨(저자도 human-authored 오류를 향후 과제로). 범위 조건(C3/C4)은 judgerEva 에서만 측정 가능.
- **API 모델 중심.** 오픈 모델은 Llama-3.3-70B 하나. 소형 로컬 모델을 judge 로 쓰는 경우는 측정 안 됨.
- 모든 judge 가 같은 pairwise 프롬프트·temperature 0 — 프롬프트 설계(루브릭, 기준 명시 등)를 바꾸면 프로필이 어떻게 변하는지는 안 쟀다.
- **안 한 것:** CAP 로 고른 judge 가 실제 과제에서 정확도로 고른 judge 보다 나은지 — 저자가 향후 과제로 명시. 즉 "더 actionable 하다"는 주장 자체는 아직 검증 전.

## 한계
- 논문이 밝힌 것: 8조건은 공리적이지 않고 완전하지 않음 / pairwise 전용(점수·루브릭 채점으로 확장하려면 조건 재정의 필요) / judge 버전별 스냅샷 / 근사 측정은 직접 측정과 동등하지 않음 / C3·C4 는 합성 오류에서만 / C8 평가자가 Claude 계열이라 Claude judge 2개와 같은 계열, 사람 검증은 1명·비맹검·120건 / stress 분석은 JudgeBench-Pro 의 주입 방식에 한정 / 절대값은 생성기 의존(Claude 생성분이 최대 40점 더 어려움)
- 읽으며 본 것 (내 판단): 결론부의 "가장 강한 judge 가 누락엔 늘 강하진 않다"는 judge 독립 부분집합에선 n=30·n=7 에 기대는 약한 근거다. 프레임워크의 실무 가치는 특정 순위가 아니라 *측정 설계*(strict 강건성, supported-correct, coverage 표기)에 있다. 공개 저장소 URL 은 본문에 있으나 HF 메타데이터상 0★ 이고 실제 공개 여부는 확인 안 함.

## 외부 평가
조회했으나 없음: S2 건너뜀(발표 40일) · HN 없음 · HF upvote 0 · PWC 조회 실패(404) · 웹 검색 1회에서 이 논문을 다룬 독립 평가 못 찾음.
(같은 검색에서 나온 관련 연구: "A Judge Should Know What Changed: Construct Validity for LLM-as-a-Judge Evaluation" (arXiv 2608.24419) — 7개 judge 의 validity profile 을 다루는 비슷한 문제의식의 논문. 이 논문에 대한 평가는 아님.)

## 관심 주제와의 연결
- **LLM-as-a-judge / evaluation without ground truth:** judge 를 고르거나 검증할 때 쓸 체크리스트가 된다 — 순서 바꿔 두 번 돌려 둘 다 맞는지, 길이만 부풀린 답에 넘어가는지, 단서를 빠뜨린 답을 잡는지를 따로 잰다. 정답 레이블 없이 운영하는 judge 라도, 오류를 심은 합성 쌍을 만들어 사전 점검하는 방식으로 옮길 수 있다.
- **long-form document generation:** 긴 문서 평가는 길이 편향과 누락(조건·예외를 빠뜨림)에 노출된다고 저자도 언급. 누락 탐지가 전체 정확도와 따로 논다는 결과는(근거는 약하지만) 긴 문서 judge 를 따로 점검할 이유가 된다.
- **rubric evaluation:** 직접 연결은 약함 — 논문은 pairwise 만 다루고 루브릭 채점으로의 확장은 열린 문제로 남겼다. supported-correct rate(판정 × 근거 품질)는 루브릭 채점의 근거 검증에도 같은 모양으로 쓸 수 있다.

## 출처
- 논문: https://arxiv.org/abs/2610.09229
- 공개 저장소(본문 표기, 확인 안 함): https://github.com/wenqi-l/CAP-judgerEva
- 관련 연구(검색 결과): https://arxiv.org/pdf/2608.24419
