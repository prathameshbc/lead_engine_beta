"""
Query Builder — LLM-powered with template fallback.

Primary path  : build_queries_with_llm()  → calls Ollama to generate
                contextually rich, industry-aware search queries.
Fallback path : build_queries_template()  → deterministic cross-product
                of locations × keywords × entity_types (no LLM required).

The public entry point build_queries() tries LLM first; if Ollama is
offline or returns garbage it silently falls back to the template path.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from config import OLLAMA_URL

log = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = (
    "You are a B2B lead-research assistant. "
    "Respond ONLY with a valid JSON object. No markdown, no explanations."
)

_USER_TMPL = """You are building a list of web search queries to find B2B leads.

INDUSTRY  : {industry}
LOCATIONS : {locations}
KEYWORDS  : {keywords}
ENTITY TYPES : {entity_types}

Generate {n_queries} diverse search queries that would surface company websites,
trade directories, contact pages, industry associations, and import/export records
for the parameters above.

Vary the phrasing — combine location + keyword + entity type in different orders,
include queries like "site:company.com", "contact", "wholesale", "distributor",
"importer", etc. as appropriate for the industry.

Return EXACTLY this JSON (no extra keys):
{{
  "queries": ["<query 1>", "<query 2>", ...]
}}"""


# ── LLM-powered builder ───────────────────────────────────────────────────────

def _call_ollama_for_queries(
    industry:     str,
    locations:    list[str],
    keywords:     list[str],
    entity_types: list[str],
    model:        str,
    n_queries:    int = 15,
) -> Optional[list[str]]:
    """Call Ollama and parse the JSON query list. Returns None on any failure."""
    prompt = _USER_TMPL.format(
        industry=industry,
        locations=", ".join(locations) or "any location",
        keywords=", ".join(keywords) or "general products",
        entity_types=", ".join(entity_types) or "company",
        n_queries=n_queries,
    )

    payload = {
        "model":   model,
        "prompt":  prompt,
        "system":  _SYSTEM,
        "stream":  False,
        "format":  "json",
        "options": {"temperature": 0.3, "top_p": 0.9},
    }

    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            return None

        raw = resp.json().get("response", "")

        # format:"json" should give us clean JSON, but strip fences anyway
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(raw)

        queries = data.get("queries", [])
        if not isinstance(queries, list):
            return None

        # Sanitise: strings only, non-empty
        return [str(q).strip() for q in queries if str(q).strip()]

    except Exception as exc:
        log.debug("LLM query generation failed: %s", exc)
        return None


# ── Template fallback ─────────────────────────────────────────────────────────

def build_queries_template(
    locations:    list[str],
    keywords:     list[str],
    entity_types: list[str],
    custom_queries: list[str] | None = None,
) -> list[str]:
    """
    Deterministic cross-product query builder — no LLM required.
    Used as fallback when Ollama is offline.
    """
    raw: list[str] = []
    for location in locations or [""]:
        for kw in keywords or [""]:
            for etype in entity_types or [""]:
                raw.append(f"{kw} {etype} {location}".strip())
            raw.append(f"{kw} supplier {location}".strip())
            raw.append(f"{kw} company {location} contact email".strip())
            raw.append(f"buy {kw} wholesale {location}".strip())

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for q in raw + [c.strip() for c in (custom_queries or []) if c.strip()]:
        if q and q not in seen:
            seen.add(q)
            result.append(q)
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def build_queries(
    industry:       str,
    locations:      list[str],
    keywords:       list[str],
    entity_types:   list[str],
    custom_queries: list[str] | None = None,
    model:          str = "qwen2.5",
    use_llm:        bool = True,
) -> list[str]:
    """
    Build search queries for the given parameters.

    With use_llm=True (default), attempts LLM generation first and falls
    back to the template builder if Ollama is unavailable or fails.
    """
    llm_queries: list[str] = []

    if use_llm:
        llm_queries = _call_ollama_for_queries(
            industry, locations, keywords, entity_types, model
        ) or []
        if llm_queries:
            log.debug("LLM generated %d queries", len(llm_queries))

    if not llm_queries:
        log.debug("Falling back to template query builder")
        llm_queries = build_queries_template(
            locations, keywords, entity_types
        )

    # Always append user-supplied custom queries (deduplicated)
    seen = set(llm_queries)
    for cq in (custom_queries or []):
        cq = cq.strip()
        if cq and cq not in seen:
            seen.add(cq)
            llm_queries.append(cq)

    return llm_queries
