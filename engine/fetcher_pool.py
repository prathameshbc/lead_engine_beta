"""
Concurrent URL fetcher — ThreadPoolExecutor based.

Workers: configurable (default 4), safe on a low-RAM machine.
Each URL gets one automatic retry with a longer timeout.
Blocked domains and non-HTML file extensions are skipped without a network call.
"""
from __future__ import annotations

import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx

from config import DOMAIN_BLACKLIST, FETCH_WORKERS

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LeadEngine/5.0; "
        "+https://github.com/your-org/lead-engine)"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
}

SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".mp4", ".mp3", ".avi", ".mov",
    ".exe", ".dmg", ".apk", ".msi",
})


def _is_blocked(url: str) -> bool:
    """Return True if the URL should be skipped before any network call."""
    try:
        parsed = urlparse(url)
        host   = parsed.netloc.lower().lstrip("www.")
        for blocked in DOMAIN_BLACKLIST:
            if host == blocked or host.endswith("." + blocked):
                return True
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
            return True
    except Exception:
        return True
    return False


def _fetch_one(url: str) -> tuple[str, Optional[str]]:
    """
    Fetch a single URL with one automatic retry.

    Returns (url, html_text) on success, (url, None) on failure.
    """
    if _is_blocked(url):
        return url, None

    for attempt in range(2):
        timeout = 10 if attempt == 0 else 18
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers=HEADERS,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            ) as client:
                resp = client.get(url)
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type or "text/plain" in content_type:
                    return url, resp.text
                return url, None
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt == 0:
                continue       # one retry
            return url, None
        except Exception:
            return url, None

    return url, None


def fetch_concurrent(
    url_list: list[str],
    emit:     Callable,
    workers:  int = FETCH_WORKERS,
) -> list[tuple[str, str]]:
    """
    Fetch all URLs in parallel using a ThreadPoolExecutor.

    Emits SSE progress events as each URL completes.
    Returns only (url, html) tuples for successful fetches.
    """
    total:   int                      = len(url_list)
    done:    int                      = 0
    fetched: list[tuple[str, str]]    = []

    emit("progress", stage="fetch", current=0, total=total, pct=0)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(_fetch_one, url): url for url in url_list}

        for future in as_completed(future_map):
            done += 1
            url, html = future.result()
            pct = round(done / total * 100)

            emit("progress", stage="fetch", current=done, total=total, pct=pct)

            if html:
                fetched.append((url, html))
                emit("log", level="dim", msg=f"[{done}/{total}] ✓ {url[:75]}")
            else:
                emit("log", level="dim", msg=f"[{done}/{total}] ✗ {url[:75]}")

    return fetched
