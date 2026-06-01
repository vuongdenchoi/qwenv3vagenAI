"""
Script tien ich de chay toan bo he thong Design Check AI.
"""
import os
import sys
import subprocess
from pathlib import Path
from typing import List

# Load .env file nếu có
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass  # python-dotenv chưa cài, bỏ qua

ROOT    = Path(__file__).parent
BACKEND = ROOT / "backend"


def step(msg: str):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print('='*60)


def run(cmd: List[str], cwd=None, env=None):
    result = subprocess.run(cmd, cwd=cwd or ROOT, env=env or os.environ)
    if result.returncode != 0:
        print(f"\n[FAIL] Command failed: {' '.join(cmd)}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Design Check AI - runner")
    parser.add_argument(
        "action",
        choices=["install", "build-index", "serve", "all"],
        help=(
            "install     - cai thu vien Python\n"
            "build-index - tao TF-IDF index tu design rules\n"
            "serve       - chay FastAPI server\n"
            "all         - install + build-index + serve\n"
        )
    )
    parser.add_argument("--port", default="8000", help="Port cho FastAPI server (default: 8000)")
    args = parser.parse_args()

    if args.action in ("install", "all"):
        step("Buoc 1: Cai dat thu vien Python")
        run([sys.executable, "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt")])
        print("[OK] Da cai dat xong")

    if args.action in ("build-index", "all"):
        step("Buoc 2: Build TF-IDF knowledge base index")
        run([sys.executable, str(BACKEND / "knowledge_base" / "build_index.py")])
        print("[OK] Index da duoc tao")

    if args.action in ("serve", "all"):
        step(f"Buoc 3: Khoi dong FastAPI server tai http://localhost:{args.port}")
        print("  Nhan Ctrl+C de dung\n")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(BACKEND)
        try:
            subprocess.run(
                [sys.executable, "-m", "uvicorn", "main:app",
                 "--host", "0.0.0.0",
                 "--port", args.port,
                 "--reload"],
                cwd=str(BACKEND),
                env=env,
            )
        except KeyboardInterrupt:
            print("\n[STOP] Server da dung.")
