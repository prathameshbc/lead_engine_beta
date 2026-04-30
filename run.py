#!/usr/bin/env python3
"""
Cross-platform run script for Lead Intelligence Engine.
Works on Windows, macOS, and Linux.

Usage:
    python run.py [--host 0.0.0.0] [--port 8000] [--no-browser]
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import time
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
VENV = ROOT / "venv"
DATA = ROOT / "data"

_SYSTEM = platform.system()  # "Windows", "Darwin", "Linux"


def _venv_python() -> Path:
    if _SYSTEM == "Windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _venv_uvicorn() -> Path:
    if _SYSTEM == "Windows":
        return VENV / "Scripts" / "uvicorn.exe"
    return VENV / "bin" / "uvicorn"


def _check_venv() -> None:
    if not _venv_python().exists():
        print("Virtual environment not found. Run:  python setup.py")
        sys.exit(1)


def _check_ollama() -> None:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
    except Exception:
        print("⚠  Ollama is offline — LLM features will be disabled.")
        print("   Start it with:  ollama serve")


def _open_browser(url: str, delay: float = 2.0) -> None:
    """Open the browser after a short delay (non-blocking)."""
    def _open():
        time.sleep(delay)
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    t = threading.Thread(target=_open, daemon=True)
    t.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Lead Intelligence Engine")
    parser.add_argument("--host",       default=os.getenv("HOST",  "0.0.0.0"))
    parser.add_argument("--port",       default=os.getenv("PORT",  "8000"))
    parser.add_argument("--no-browser", action="store_true", help="Skip browser auto-open")
    parser.add_argument("--reload",     action="store_true", help="Enable hot-reload (dev mode)")
    args = parser.parse_args()

    _check_venv()
    _check_ollama()
    DATA.mkdir(parents=True, exist_ok=True)

    url = f"http://localhost:{args.port}"
    print(f"Lead Intelligence Engine  →  {url}   (Ctrl+C to stop)")

    if not args.no_browser:
        _open_browser(url)

    cmd = [
        str(_venv_uvicorn()),
        "main:app",
        "--host", args.host,
        "--port", str(args.port),
        "--log-level", "warning",
    ]
    if args.reload:
        cmd.append("--reload")

    # Run from the project root so relative imports work correctly
    subprocess.run(cmd, cwd=str(ROOT), check=False)


if __name__ == "__main__":
    main()
