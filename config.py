"""
Lead Intelligence Engine — Configuration
All paths use pathlib.Path for full cross-platform compatibility.
Override any value via environment variable or a .env file in the project root.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Optional dotenv support (not in requirements — graceful fallback) ─────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv not installed; env vars still work fine

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).parent.resolve()
DATA_DIR: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH:  Path = DATA_DIR / os.getenv("DB_NAME", "leads.db")
STATIC_DIR: Path = BASE_DIR / "static"

# ── SearXNG public instances (tried in order; unhealthy ones are skipped) ─────
SEARXNG_INSTANCES: list[str] = [
    inst.strip()
    for inst in os.getenv(
        "SEARXNG_INSTANCES",
        "https://searx.be,"
        "https://search.disroot.org,"
        "https://searxng.world,"
        "https://searx.tiekoetter.com,"
        "https://priv.au",
    ).split(",")
    if inst.strip()
]

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_URL:    str = os.getenv("OLLAMA_URL",    "http://localhost:11434")
DEFAULT_MODEL: str = os.getenv("OLLAMA_MODEL",  "qwen2.5")

# ── Crawl limits ──────────────────────────────────────────────────────────────
MAX_RESULTS_PER_QUERY: int = int(os.getenv("MAX_RESULTS_PER_QUERY", "5"))
MAX_TOTAL_URLS:        int = int(os.getenv("MAX_TOTAL_URLS",        "100"))

# ── Concurrent fetch workers (safe on a low-RAM machine) ─────────────────────
FETCH_WORKERS: int = int(os.getenv("FETCH_WORKERS", "4"))

# ── Server ────────────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

# ── Domains to skip (noise / non-lead sources) ────────────────────────────────
DOMAIN_BLACKLIST: frozenset[str] = frozenset({
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    "youtube.com", "tiktok.com", "pinterest.com", "reddit.com",
    "alibaba.com", "aliexpress.com", "amazon.com", "amazon.co.jp",
    "amazon.de", "ebay.com", "etsy.com", "shopify.com",
    "wikipedia.org", "wikimedia.org",
    "gov.uk", "gov.au", "gov.cn",
    "trustpilot.com", "glassdoor.com", "indeed.com",
    "bloomberg.com", "reuters.com", "ft.com", "wsj.com",
    "google.com", "bing.com", "yahoo.com", "baidu.com",
    "play.google.com", "apps.apple.com",
})
