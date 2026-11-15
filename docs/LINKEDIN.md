# LinkedIn 연동

발행 탭의 **LinkedIn 에 게시** 버튼으로 초안을 본인 LinkedIn 에 올리는 설정. 처음 한 번, 15분 남짓.
설정하지 않아도 발행 탭의 **글자 복사**로 직접 붙여 넣을 수 있다 — 이 문서는 버튼으로 올리고 싶을 때만.

## 되는 것 / 안 되는 것

| 된다 | 안 된다 |
|---|---|
| **개인 프로필**에 글자·링크 게시 | 이미지·문서 첨부 (업로드 절차가 따로 있어 아직 없음) |
| 사람이 확인 창에서 누를 때만, 한 글은 한 번만 | 회사 페이지 명의 게시 (별도 권한·심사 필요) |
| 점검 경고(개인 메모 겹침·길이 초과)가 있으면 버튼 잠금 | 예약·자동 게시, 화면 속 AI 세션의 게시 |

공식 API 만 쓴다 ("Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect"). 브라우저 자동화는 쓰지 않는다 (약관·계정 위험).

## 준비물 한눈에

```
LinkedIn 페이지 (본인 소유) ──► 개발자 앱 ──► 제품 2개 + Redirect URL ──► 키 2개 ──► setup 명령 ──► 화면에서 연결
       1단계                       2·3단계            4·5단계                 6단계          7단계            8단계
```

## 1. LinkedIn 페이지 만들기 — 개인 계정이면 필요

LinkedIn 개발자 앱은 **반드시 LinkedIn 페이지(회사 페이지 형태)에 연결**해야 한다. 개인 프로필은 고를 수 없다.
페이지는 앱의 "발행자" 표시로만 쓰이고, **글은 개인 프로필로 올라간다.**

- 앱 만들기 화면의 "For Individual Developers … default Company page" 안내는 특정 제품(유럽 회원용 데이터 이동 API 등)
  이야기로, 이 연동에 쓰는 제품의 기본 페이지는 찾지 못했다 → 본인 페이지를 만드는 쪽이 확실하다.
- 페이지는 여러 프로젝트가 같이 쓸 수 있으니 **공개돼도 괜찮은 범용 이름**으로 (예: `side-projects`).

https://www.linkedin.com/company/setup/new/ → **Company**

| 칸 | 예시 |
|---|---|
| Name | `side-projects` |
| LinkedIn public URL | 영문 주소. 이미 쓰는 이름이면 `side-projects-<영문 핸들>` 처럼 |
| Website | 본인 GitHub 계정 주소 |
| Industry / Size / Type | Software Development / 0-1 employees / Self-employed |
| Logo | 정사각형 100px 이상 (없어도 됨) |
| 확인 체크 | "authorized representative" → **Create page** — 만든 사람이 관리자가 된다 |

## 2. 앱 만들기

https://www.linkedin.com/developers/apps → **Create app**

| 칸 | 넣을 것 |
|---|---|
| App name | 범용 이름 (예: `side-projects`). 연결할 때 승인 화면에 "○○이(가) 권한을 요청합니다"로 보인다 — 나중에 바꿀 수 있다 |
| LinkedIn Page | 1단계에서 만든 페이지를 검색해 선택. **앱과 페이지의 연결은 나중에 바꿀 수 없다** |
| Privacy policy URL | 선택 칸이면 비워 둔다 |
| App logo | 정사각형, 한 변 100px 이상 (필수) |
| Legal agreement | 체크 → **Create app** |

## 3. 앱 인증 — Settings 탭

**Verify** → **Generate URL** → 그 URL 을 열어 **Approve**. 본인이 페이지 관리자라 바로 끝난다
(남의 회사 페이지면 그 관리자가 30일 안에 승인해야 한다).

## 4. 제품 추가 — Products 탭

- **Sign In with LinkedIn using OpenID Connect** → Request access → 약관 체크 → Request access
- **Share on LinkedIn** → 같은 방법

둘 다 페이지 위쪽 **Added products** 에 보이면 끝. 그다음 **Auth 탭 아래 "OAuth 2.0 scopes"** 에 다음 셋이 있는지 확인한다:
`openid`, `profile` (OpenID Connect 에서) · `w_member_social` (Share on LinkedIn 에서). `email` 은 보여도 쓰지 않는다.

## 5. Redirect URL — Auth 탭 "OAuth 2.0 settings"

**Authorized redirect URLs** 의 연필 아이콘 → **+ Add redirect URL** →

```
http://127.0.0.1:8768/api/linkedin/callback
```

- 글자 그대로. `localhost` 가 아니라 `127.0.0.1`, 끝에 `/` 없음 — 한 글자라도 다르면 연결 때 `redirect_uri` 오류
- 다른 프로젝트도 같은 앱을 쓰면 그 프로젝트 주소를 **추가로** 등록한다 (여러 개 가능)

## 6. 키 확인 — Auth 탭 "Application credentials"

**Client ID** 와 **Primary Client Secret** (눈 아이콘으로 보기 / 복사 아이콘).
**Secret 은 채팅·이슈·커밋에 붙이지 않는다.**

## 7. 키 넣기 — 터미널에서

AI 대화창이 아닌 **별도 터미널**에서:

```bash
cd paper_analyst
python -m paper_analyst.linkedin setup     # Client ID → Secret (화면에 안 보임) → Secret 한 번 더
python -m paper_analyst.linkedin status    # 확인 (Client ID 는 앞뒤 몇 글자만 보임)
```

- 저장: `~/.config/side-projects/linkedin_app.json` (권한 600, 폴더 700) — **저장소 밖**이라 git 에 안 올라가고,
  화면 속 AI 세션도 읽지 못한다. 위치는 환경변수 `SIDE_PROJECTS_CONFIG` 로 바꿀 수 있다
- 서버 환경에서는 대신 환경변수 `LINKEDIN_CLIENT_ID` · `LINKEDIN_CLIENT_SECRET` 도 된다 (이쪽이 우선)

## 8. 연결하고 게시하기 — 화면에서

1. 서버: `python -m paper_analyst serve` → 브라우저로 **http://127.0.0.1:8768** (5단계와 같은 주소로 열어야 한다)
2. **발행** 탭 → 초안의 **LinkedIn** 보기 → **LinkedIn 연결** → LinkedIn 로그인·허용 → "연결됨" 화면에서 돌아가기
3. **LinkedIn 에 게시** → 확인 창(계정 이름·글자 수) → **게시** → "게시됨" + 글 링크

- 연결은 **60일**마다 다시 한다 (액세스 토큰 60일, 갱신 토큰은 일부 파트너에게만 주어진다 — 공식 문서)
- 토큰은 `~/.config/side-projects/tokens/paper_analyst-linkedin.json` (프로젝트별, 권한 600).
  끊기: 발행 탭 **연결 끊기** 또는 `python -m paper_analyst.linkedin disconnect`

## 여러 프로젝트에서 같은 앱 쓰기

- 키는 공용 위치 하나 (`~/.config/side-projects/linkedin_app.json`), 토큰은 프로젝트마다 따로
- **모든 프로젝트가 같은 권한 범위**(`openid profile w_member_social`)로 연결한다 — 같은 앱에서 다른 범위로 연결하면
  그 앱의 이전 토큰이 모두 무효가 된다 (공식 문서). 다른 권한이 필요한 프로젝트는 앱을 따로 만든다
- Redirect URL 은 프로젝트별로 추가 (5단계)

## 안전장치

| 무엇 | 어떻게 |
|---|---|
| 키·토큰 | 저장소 밖, 권한 600. 입력은 숨김 입력 명령으로만 |
| 화면 속 AI 세션 | 게시 권한 없음 ("올려줘"라고 해도 안 올라감). 읽기는 저장소 안으로 제한, `~/.config` 는 명시 거부 |
| 게시 | 사람이 확인 창에서 누를 때만. 점검 경고 남음 · 미리보기 뒤 초안 변경 · 이미 게시함 → 거부 |
| 연결 요청 | 서버가 만든 일회용 state 만 받는다 (위조·재사용 거부, 10분 유효) |

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| 앱 만들 때 페이지를 고를 수 없음 | 개인 프로필은 안 됨 | 1단계로 본인 페이지 만들기 |
| 앱이 "verification pending" | 페이지 관리자 승인 전 | 3단계 Verify URL 을 관리자 계정으로 열어 승인 |
| 연결 때 `redirect_uri` 오류 | 등록 주소와 다름 | 브라우저를 `127.0.0.1:8768` 로 열었는지, 5단계 주소가 글자 그대로인지 |
| 연결 때 `unauthorized_scope` 류 오류 | 제품이 덜 추가됨 | 4단계 — scopes 에 셋이 다 있는지 |
| 발행 탭에 "앱 키가 필요합니다" | 키 파일 없음 | 7단계 `setup` |
| "연결이 만료됐습니다" / 게시 때 "토큰이 거부됐습니다" | 60일 지남 · 사용자가 LinkedIn 설정에서 권한 취소 | 다시 **LinkedIn 연결** |
| 게시 버튼이 회색 | 점검 경고가 남음 | 경고 줄을 고친 초안으로 (`python -m paper_analyst.post check posts/<이름>`) |
| "화면에 보인 글과 파일 내용이 다릅니다" | 미리보기 뒤 초안이 바뀜 | 발행 탭을 새로 열어 바뀐 글을 확인하고 다시 |

## 확인 상태 (2026-11-15)

- 공식 문서로 확인: 페이지 연결 필수, 토큰 60일·갱신 토큰은 일부 파트너만, 권한 범위가 바뀌면 이전 토큰 무효,
  게시는 Person URN(OpenID Connect 의 `sub`)으로 `/v2/ugcPosts`
- 코드로 확인: 연결·게시·거부 조건 전부 가짜 LinkedIn 으로 자동 테스트·브라우저 점검
- **아직 실제 LinkedIn 으로 확인하지 않음**: 실제 연결·게시 1건, `http://127.0.0.1` Redirect URL 이 등록되는지 —
  처음 실제로 해 본 뒤 이 절을 고친다

## 참고

- [LinkedIn 3-Legged OAuth Flow](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow)
- [Refresh Tokens with OAuth 2.0](https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens)
- [Share on LinkedIn](https://developer.linkedin.com/documents/share-api)
- [Associate an app with a LinkedIn Page](https://www.linkedin.com/help/lms/answer/a548360)
