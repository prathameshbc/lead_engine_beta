"""
SearXNG federated search client.

Instances are probed once at first use and the live list is cached in memory.
On each query, live instances are tried in order; a failing instance is skipped.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import httpx

from config import SEARXNG_INSTANCES

log = logging.getLogger(__name__)

_live_instances: List[str] = []


def _probe_instances() -> List[str]:
    """Test every configured instance; return the ones that respond correctly."""
    live: List[str] = []
    for base in SEARXNG_INSTANCES:
        try:
            resp = httpx.get(
                f"{base}/search",
                params={"q": "test", "format": "json"},
                timeout=6,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200 and "results" in resp.text:
                live.append(base)
        except Exception:
            pass
    # Fallback: use all instances if none pass the probe (e.g. rate limits)
    return live or list(SEARXNG_INSTANCES)


def get_live_instances() -> List[str]:
    """Return cached live instances, probing on first call."""
    global _live_instances
    if not _live_instances:
        _live_instances = _probe_instances()
        log.debug("Live SearXNG instances: %s", _live_instances)
    return _live_instances


def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """
    Execute a search query across live SearXNG instances.
    Returns up to max_results result dicts.
    """
    for base in get_live_instances():
        try:
            resp = httpx.get(
                f"{base}/search",
                params={"q": query, "format": "json", "language": "en"},
                timeout=12,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; LeadEngine/5.0)"
                },
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])[:max_results]
                if results:
                    return results
        except Exception:
            continue
    return []


def reset_instance_cache() -> None:
    """Force a fresh instance probe on the next search call."""
    global _live_instances
    _live_instances = []
