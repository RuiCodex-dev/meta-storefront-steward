"""One command, no keys: build the demo database from demo/*.jsonl and open the app on it.

    python scripts/run_demo.py [--port 8765]

Every review in the demo is synthetic (written by Muse Spark Open); crash issues and releases are the studio's own.
Store sync and posting are off. Browsing needs no API key; "Run the morning pass now" and "Try it" call Muse Spark
and therefore need a Meta Model API key (see the README).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    db_path = ROOT / "data" / "demo" / "steward_demo.db"
    env = dict(os.environ, STEWARD_DB=str(db_path), STEWARD_DEMO="1")
    env.pop("STEWARD_LIVE", None)                      # the demo can never post
    subprocess.run([sys.executable, "-m", "steward.demo", "load"], cwd=ROOT, env=env, check=True)
    print(f"Open http://127.0.0.1:{a.port}/  (Ctrl+C stops the server)")
    return subprocess.call([sys.executable, "-m", "uvicorn", "steward.web.app:app", "--host", "127.0.0.1",
                            "--port", str(a.port)], cwd=ROOT, env=env)


if __name__ == "__main__":
    sys.exit(main())
