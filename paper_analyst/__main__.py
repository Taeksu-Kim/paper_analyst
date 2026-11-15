"""python -m paper_analyst serve [--port 8768]   — 화면 (127.0.0.1 고정)"""
from __future__ import annotations

import argparse
import sys

from paper_analyst import ROOT


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m paper_analyst")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="화면 띄우기")
    s.add_argument("--port", type=int, default=8768)
    a = ap.parse_args()
    if a.cmd == "serve":
        import uvicorn
        from paper_analyst.app import create_app
        print(f"paper_analyst: http://127.0.0.1:{a.port}")
        uvicorn.run(create_app(ROOT), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
