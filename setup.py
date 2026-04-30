#!/usr/bin/env python3
"""
Cross-platform setup script for Lead Intelligence Engine.
Works on Windows, macOS, and Linux.

Usage:
    python setup.py
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
VENV = ROOT / "venv"
REQ  = ROOT / "requirements.txt"
DATA = ROOT / "data"


# ── Colour helpers (gracefully degrade on Windows without ANSI support) ───────
_ANSI = sys.stdout.isatty() and platform.system() != "Windows"
G  = "\033[0;32m"  if _ANSI else ""
Y  = "\033[1;33m"  if _ANSI else ""
C  = "\033[0;36m"  if _ANSI else ""
R  = "\033[0;31m"  if _ANSI else ""
N  = "\033[0m"     if _ANSI else ""

def ok(msg: str)   -> None: print(f"  {G}✓ {msg}{N}")
def warn(msg: str) -> None: print(f"  {Y}⚠ {msg}{N}")
def err(msg: str)  -> None: print(f"  {R}✗ {msg}{N}")
def hdr(msg: str)  -> None: print(f"\n{C}{msg}{N}")


def check_python() -> None:
    hdr("[1/4] Checking Python version…")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        err(f"Python 3.10+ required (found {major}.{minor})")
        sys.exit(1)
    ok(f"Python {major}.{minor} OK")


def create_venv() -> None:
    hdr("[2/4] Creating virtual environment…")
    if VENV.exists():
        ok("venv already exists — skipping")
        return
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    ok("venv created")


def pip_install() -> None:
    hdr("[3/4] Installing dependencies…")
    pip = VENV / ("Scripts" if platform.system() == "Windows" else "bin") / "pip"
    subprocess.run([str(pip), "install", "--upgrade", "pip", "-q"], check=True)
    subprocess.run([str(pip), "install", "-r", str(REQ), "-q"], check=True)
    ok("Dependencies installed")


def check_ollama() -> None:
    hdr("[4/4] Checking Ollama…")
    import shutil
    if not shutil.which("ollama"):
        warn("Ollama not found in PATH.")
        print("     Install from https://ollama.com/download")
        print("     Then run:  ollama pull qwen2.5")
        return

    ok("Ollama found")
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        ok("Ollama is running")

        # Check if default model is available
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True
        )
        if "qwen2.5" not in result.stdout:
            warn("Model 'qwen2.5' not pulled yet. Run:  ollama pull qwen2.5")
    except Exception:
        warn("Ollama is not running. Start it with:  ollama serve")


def create_dirs() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    env_example = ROOT / ".env.example"
    env_file    = ROOT / ".env"
    if not env_file.exists() and env_example.exists():
        import shutil
        shutil.copy(env_example, env_file)
        ok(".env created from .env.example")


def main() -> None:
    print(f"\n{C}╔══════════════════════════════════════════╗")
    print(f"║    LEAD INTELLIGENCE ENGINE — SETUP      ║")
    print(f"╚══════════════════════════════════════════╝{N}\n")

    check_python()
    create_venv()
    pip_install()
    check_ollama()
    create_dirs()

    python_exe = (
        VENV / ("Scripts\\python.exe" if platform.system() == "Windows" else "bin/python")
    )
    print(f"\n{G}╔══════════════════════════════════════════╗")
    print(f"║         SETUP COMPLETE ✓                 ║")
    print(f"╚══════════════════════════════════════════╝{N}")
    print(f"\n  {C}Start:{N}  python run.py")
    print(f"  {C}Open:{N}   http://localhost:8000\n")


if __name__ == "__main__":
    main()
