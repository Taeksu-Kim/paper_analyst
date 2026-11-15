"""LinkedIn 게시 — 공식 API("Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect")만 쓴다.

화면의 버튼으로만 게시한다 (확인 창 → 미리보기 해시 대조 → 한 번만). Claude 세션에는 게시 권한이 없다.
예약·자동 게시는 하지 않는다.

설정 (처음 한 번, README "LinkedIn 게시" 절):
  LinkedIn 개발자 앱 — LinkedIn 페이지 연결 필수, 제품: Share on LinkedIn · Sign In with LinkedIn using OpenID Connect,
  Redirect URL: http://127.0.0.1:8768/api/linkedin/callback
  앱 키: 환경변수 LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET 또는 data/linkedin_app.json {"client_id","client_secret"}
토큰: data/linkedin_token.json (git 제외). 액세스 토큰 60일, 갱신 토큰은 일부 파트너만 → 만료되면 다시 연결.

API (공식 문서 기준, 2026-11-15 확인):
  인증  https://www.linkedin.com/oauth/v2/authorization (scope: openid profile w_member_social)
  토큰  POST https://www.linkedin.com/oauth/v2/accessToken
  사용자 GET https://api.linkedin.com/v2/userinfo → sub (Person URN = urn:li:person:<sub>)
  게시  POST https://api.linkedin.com/v2/ugcPosts (X-Restli-Protocol-Version: 2.0.0) → 응답 헤더 x-restli-id 가 글 URN
"""
from __future__ import annotations

import json
import os
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

    def __init__(self, data_dir: Path) -> None:
        self.app_f = data_dir / "linkedin_app.json"
        self.token_f = data_dir / "linkedin_token.json"

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
        self.token_f.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_f.with_suffix(".tmp")
        tmp.write_text(json.dumps(tok, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        tmp.replace(self.token_f)

    def clear(self) -> None:
        self.token_f.unlink(missing_ok=True)


def status(store: Store) -> dict:
    tok = store.token()
    now = time.time()
    return {"configured": store.app() is not None, "connected": bool(tok) and tok.get("expires_at", 0) > now,
            "expired": bool(tok) and tok.get("expires_at", 0) <= now, "name": (tok or {}).get("name", ""),
            "expires_at": (tok or {}).get("expires_at", 0)}
