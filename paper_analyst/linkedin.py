"""LinkedIn 게시 — 공식 API("Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect")만 쓴다.

화면의 버튼으로만 게시한다 (확인 창 → 미리보기 해시 대조 → 한 번만). Claude 세션에는 게시 권한이 없다.
예약·자동 게시는 하지 않는다.

설정 (처음 한 번, README "LinkedIn 게시" 절):
  LinkedIn 개발자 앱 — LinkedIn 페이지 연결 필수, 제품: Share on LinkedIn · Sign In with LinkedIn using OpenID Connect,
  Redirect URL: http://127.0.0.1:8768/api/linkedin/callback
  앱 키 넣기 (이 대화·화면 밖의 터미널에서, Secret 은 화면에 안 보이게 입력):
      python -m paper_analyst.linkedin setup        # 저장 위치: ~/.config/side-projects/linkedin_app.json (권한 600)
      python -m paper_analyst.linkedin status
  키·토큰은 저장소 밖 공용 위치에 둔다 — 여러 프로젝트가 같은 앱을 쓰고, 화면의 Claude 세션(작업 폴더 밖 접근 불가)이 읽지 못하게.
  위치는 환경변수 SIDE_PROJECTS_CONFIG 로 바꿀 수 있다. 앱 키 읽는 순서: 환경변수 LINKEDIN_CLIENT_ID/SECRET → 공용 위치.
토큰: <공용 위치>/tokens/paper_analyst-linkedin.json (프로젝트별). 액세스 토큰 60일, 갱신 토큰은 일부 파트너만 → 만료되면 다시 연결.

API (공식 문서 기준, 2026-11-15 확인):
  인증  https://www.linkedin.com/oauth/v2/authorization (scope: openid profile w_member_social)
  토큰  POST https://www.linkedin.com/oauth/v2/accessToken
  사용자 GET https://api.linkedin.com/v2/userinfo → sub (Person URN = urn:li:person:<sub>)
  게시  POST https://api.linkedin.com/v2/ugcPosts (X-Restli-Protocol-Version: 2.0.0) → 응답 헤더 x-restli-id 가 글 URN
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POST_URL = "https://api.linkedin.com/v2/ugcPosts"
SCOPE = "openid profile w_member_social"


class LinkedInError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class LinkedInClient(Protocol):
    def exchange_code(self, code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict: ...
    def userinfo(self, access_token: str) -> dict: ...
    def create_post(self, access_token: str, author_urn: str, text: str) -> str: ...


def _http(req: urllib.request.Request) -> tuple[dict, dict]:
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return (json.loads(body) if body else {}), dict(r.headers)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise LinkedInError(f"LinkedIn 응답 HTTP {e.code}: {detail}", e.code) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise LinkedInError(f"LinkedIn 에 연결하지 못했습니다: {e}") from e


class HttpLinkedIn:
    def exchange_code(self, code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict:
        data = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                       "client_id": client_id, "client_secret": client_secret}).encode()
        body, _ = _http(urllib.request.Request(TOKEN_URL, data=data,
                                               headers={"Content-Type": "application/x-www-form-urlencoded"}))
        return body

    def userinfo(self, access_token: str) -> dict:
        body, _ = _http(urllib.request.Request(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}))
        return body

    def create_post(self, access_token: str, author_urn: str, text: str) -> str:
        payload = {
            "author": author_urn, "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text}, "shareMediaCategory": "NONE"}},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        req = urllib.request.Request(POST_URL, data=json.dumps(payload, ensure_ascii=False).encode(), headers={
            "Authorization": f"Bearer {access_token}", "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"})
        body, headers = _http(req)
        urn = {k.lower(): v for k, v in headers.items()}.get("x-restli-id") or body.get("id", "")
        if not urn:
            raise LinkedInError("게시 응답에 글 id 가 없습니다 — LinkedIn 에서 직접 확인하세요")
        return urn


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"


class Store:
    """앱 키·토큰 파일 (data/, git 제외)."""

    def __init__(self, config_dir: Path | None = None, project: str = "paper_analyst") -> None:
        cfg = config_dir or default_config_dir()
        self.app_f = cfg / "linkedin_app.json"
        self.token_f = cfg / "tokens" / f"{project}-linkedin.json"

    def app(self) -> dict | None:
        cid, sec = os.environ.get("LINKEDIN_CLIENT_ID"), os.environ.get("LINKEDIN_CLIENT_SECRET")
        if cid and sec:
            return {"client_id": cid, "client_secret": sec}
        try:
            d = json.loads(self.app_f.read_text())
            return d if d.get("client_id") and d.get("client_secret") else None
        except (OSError, json.JSONDecodeError):
            return None

    def token(self) -> dict | None:
        try:
            return json.loads(self.token_f.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def save_token(self, tok: dict) -> None:
        _write_secret(self.token_f, tok)

    def save_app(self, client_id: str, client_secret: str) -> None:
        _write_secret(self.app_f, {"client_id": client_id, "client_secret": client_secret})

    def clear(self) -> None:
        self.token_f.unlink(missing_ok=True)


def default_config_dir() -> Path:
    return Path(os.environ.get("SIDE_PROJECTS_CONFIG") or Path.home() / ".config" / "side-projects")


def _write_secret(path: Path, data: dict) -> None:
    """권한 600 파일로 원자적 저장 (폴더는 700)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _mask(s: str) -> str:
    return s[:4] + "…" + s[-2:] if len(s) > 8 else "…"


def status(store: Store) -> dict:
    tok = store.token()
    now = time.time()
    return {"configured": store.app() is not None, "connected": bool(tok) and tok.get("expires_at", 0) > now,
            "expired": bool(tok) and tok.get("expires_at", 0) <= now, "name": (tok or {}).get("name", ""),
            "expires_at": (tok or {}).get("expires_at", 0)}


def _setup(store: Store) -> int:
    print("LinkedIn 앱 키 설정 — LinkedIn 개발자 앱의 Auth 탭에서 복사해 붙여 넣으세요.")
    print(f"저장 위치: {store.app_f} (권한 600, 저장소 밖)\n")
    old = store.app()
    if old and input(f"이미 있습니다 (Client ID {_mask(old['client_id'])}). 바꿀까요? [y/N] ").strip().lower() != "y":
        print("그대로 둡니다.")
        return 0
    cid = input("Client ID: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{8,40}", cid):
        print("Client ID 모양이 아닙니다 (영문·숫자 8~40자). 다시 실행하세요.")
        return 1
    sec = getpass.getpass("Primary Client Secret (입력해도 화면에 안 보입니다): ").strip()
    if not sec or " " in sec or len(sec) < 8:
        print("Secret 이 비었거나 공백이 있습니다. 다시 실행하세요.")
        return 1
    if getpass.getpass("Secret 한 번 더: ").strip() != sec:
        print("두 번 입력한 Secret 이 다릅니다. 다시 실행하세요.")
        return 1
    store.save_app(cid, sec)
    print(f"\n저장했습니다: {store.app_f}  (Client ID {_mask(cid)})")
    print("다음: 화면 서버를 (다시) 켜고 http://127.0.0.1:8768 → 발행 탭 → LinkedIn 연결")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m paper_analyst.linkedin", description="LinkedIn 앱 키 설정·상태")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="앱 키 입력 (Secret 은 화면에 안 보임)")
    sub.add_parser("status", help="키·연결 상태 (값은 가려서)")
    sub.add_parser("disconnect", help="이 프로젝트의 LinkedIn 토큰 지우기")
    a = ap.parse_args()
    store = Store()
    if a.cmd == "setup":
        if not sys.stdin.isatty():
            print("터미널에서 직접 실행하세요 (Secret 을 숨겨서 입력받습니다).")
            return 1
        return _setup(store)
    if a.cmd == "disconnect":
        store.clear()
        print("토큰을 지웠습니다.")
        return 0
    app, st = store.app(), status(store)
    src = "환경변수" if os.environ.get("LINKEDIN_CLIENT_ID") else str(store.app_f)
    print(f"앱 키: {'있음 — Client ID ' + _mask(app['client_id']) + ' (' + src + ')' if app else '없음 → python -m paper_analyst.linkedin setup'}")
    print(f"연결: {'됨 — ' + st['name'] + ', 만료 ' + time.strftime('%Y-%m-%d', time.localtime(st['expires_at'])) if st['connected'] else ('만료됨' if st['expired'] else '안 됨')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
