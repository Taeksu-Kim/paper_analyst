"""프로필 찾기·읽기 — 모든 도구와 스킬이 같은 프로필을 쓰게 한다.

    python -m paper_analyst.profile              # 현재 프로필 요약 (스킬이 시작할 때 읽는다)
    python -m paper_analyst.profile --use nlp    # 현재 프로필을 profiles/nlp.toml 로 지정

현재 프로필 결정 순서: --profile 인자 > 환경변수 PAPER_PROFILE > profiles/active (한 줄, 파일 이름) .
셋 다 없으면 오류 — paper-setup 스킬로 프로필을 먼저 만든다. profiles/active 는 git 에서 제외된다(사람마다 다름).
"""
from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
ACTIVE = PROFILES / "active"


class NoProfile(SystemExit):
    pass


def resolve_path(arg: str | None = None) -> Path:
    name = arg or os.environ.get("PAPER_PROFILE") or (ACTIVE.read_text().strip() if ACTIVE.exists() else "")
    if not name:
        raise NoProfile("프로필 없음 — paper-setup 스킬로 만들거나 --profile / PAPER_PROFILE / profiles/active 로 지정")
    p = Path(name)
    for c in (p, PROFILES / p, PROFILES / f"{name}.toml"):
        if c.is_file():
            return c.resolve()
    raise NoProfile(f"프로필 파일을 못 찾음: {name}")


def load(arg: str | None = None) -> dict:
    path = resolve_path(arg)
    prof = tomllib.loads(path.read_text(encoding="utf-8"))
    prof["_path"] = str(path)
    prof.setdefault("name", path.stem)
    return prof


def summary(prof: dict) -> str:
    r, d = prof.get("reader", {}), prof.get("discover", {})
    lines = [
        f"프로필: {prof['name']}  ({Path(prof['_path']).relative_to(ROOT) if prof['_path'].startswith(str(ROOT)) else prof['_path']})",
        f"설명: {prof.get('description', '-')}",
        f"출력 언어: {r.get('language', 'ko')}",
        f"읽는 관점: {r.get('lens', '-')}",
        "판정 기준:" + "".join(f"\n  {i}. {c}" for i, c in enumerate(r.get("criteria", []), 1)),
        f"관심 주제: {', '.join(prof.get('interests', {}).get('topics', []))}",
        f"관심 목록: {', '.join(prof.get('watch', {}).get('models', []) + prof.get('watch', {}).get('keywords', []))}",
        f"따라잡기 시작: {prof.get('catchup_from', '-')}",
        f"후보 소스: {', '.join(d.get('sources', ['hf', 'hn', 's2']))} · S2 분야: {', '.join(d.get('s2_fields', ['Computer Science']))}"
        f" · 신호 기준: {d.get('thresholds', {})}",
    ]
    private = Path(prof["_path"]).with_suffix(".private.md")
    if private.exists():
        lines.append(f"개인 맥락(비공개): {private.relative_to(ROOT) if str(private).startswith(str(ROOT)) else private}"
                     " — 실무 판정·notes.private.md 에 쓴다")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile")
    ap.add_argument("--use", help="현재 프로필로 지정할 이름 또는 경로 (profiles/active 에 기록)")
    a = ap.parse_args()
    if a.use:
        path = resolve_path(a.use)
        ACTIVE.write_text(path.name if path.parent == PROFILES.resolve() else str(path))
        print(f"현재 프로필 → {path.name}")
    print(summary(load(a.profile)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
