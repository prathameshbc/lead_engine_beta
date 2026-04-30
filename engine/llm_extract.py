"""
LLM Extraction — universal, schema-driven.

The extraction schema is a dict mapping field names to type/description strings.
A sensible default is provided; callers can pass a custom schema to extract
any fields relevant to their industry or use-case.

Schema format (value = type hint shown to the LLM):
    {
        "company":     "string or null",
        "revenue":     "string (e.g. '$5M–$10M') or null",
        "ceo_name":    "string or null",
        ...
    }

Core contact fields (email, phone) are always extracted via the schema so
the DB layer can pick them up reliably.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from config import OLLAMA_URL

log = logging.getLogger(__name__)

# ── Default extraction schema ─────────────────────────────────────────────────

DEFAULT_SCHEMA: dict[str, str] = {
    "company":     "string or null",
    "location":    "string in 'City, Country' format or null",
    "entity_type": (
        'one of ["importer","wholesaler","distributor","retailer",'
        '"agent","manufacturer","service_provider"] or null'
    ),
    "keywords":    "array of strings — products or services (max 5 items)",
    "description": "string — one sentence describing the company or null",
    "email":       "string or null",
    "phone":       "string or null",
}

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM = (
    "You are a B2B data extraction assistant. "
    "Respond ONLY with a valid JSON object matching the requested schema. "
    "Never add explanations, markdown, or keys not listed in the schema."
)

_USER_TMPL = """Extract structured company information from the webpage below.

URL: {url}

WEBPAGE TEXT:
{text}

Return a JSON object with EXACTLY these keys and value types:
{schema_json}

Rules:
- Use null for any field you cannot confidently determine.
- Do NOT invent data. Only use information present in the text.
- For string fields, reject placeholder values like "N/A", "Unknown", "None".
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_value(val: Any, expected_type: type, default: Any) -> Any:
    """Type-safe coercion with placeholder rejection."""
    if val is None:
        return default
    if isinstance(val, expected_type):
        if expected_type is str and val.strip().lower() in {
            "null", "none", "n/a", "unknown", "na", "", "-", "—"
        }:
            return None
        return val
    # Coerce comma-separated string → list
    if expected_type is list and isinstance(val, str):
        return [p.strip() for p in val.split(",") if p.strip()]
    return default


def _build_schema_json(schema: dict[str, str]) -> str:
    """Render the schema as a pretty JSON fragment for the prompt."""
    lines = ["{"]
    items = list(schema.items())
    for i, (key, type_hint) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(f'  "{key}": {type_hint}{comma}')
    lines.append("}")
    return "\n".join(lines)


# ── Main extraction function ──────────────────────────────────────────────────

def enrich_with_llm(
    text:   str,
    url:    str,
    model:  str = "qwen2.5",
    schema: dict[str, str] | None = None,
) -> Optional[dict[str, Any]]:
    """
    Send webpage text to Ollama and return a structured dict.

    Parameters
    ----------
    text   : Cleaned webpage text (will be truncated to ~7500 chars)
    url    : Source URL (given to the LLM for context)
    model  : Ollama model name
    schema : Field-name → type-hint dict. Falls back to DEFAULT_SCHEMA.

    Returns
    -------
    dict with one key per schema field, or None on any failure.
    """
    active_schema = schema if schema else DEFAULT_SCHEMA
    schema_json   = _build_schema_json(active_schema)
    prompt        = _USER_TMPL.format(
        url=url,
        text=text[:7500],
        schema_json=schema_json,
    )

    payload = {
        "model":   model,
        "prompt":  prompt,
        "system":  _SYSTEM,
        "stream":  False,
        "format":  "json",
        "options": {"temperature": 0.05, "top_p": 0.9},
    }

    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=120,
        )
        if resp.status_code != 200:
            return None

        raw = resp.json().get("response", "")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            data = json.loads(raw)

        if not isinstance(data, dict):
            return None

        # Build a cleaned result that matches the schema keys
        result: dict[str, Any] = {}
        for key in active_schema:
            raw_val = data.get(key)
            # Determine expected Python type from the hint string
            if "array" in active_schema[key] or "list" in active_schema[key]:
                result[key] = _clean_value(raw_val, list, [])
            else:
                result[key] = _clean_value(raw_val, str, None)

        return result

    except Exception as exc:
        log.debug("LLM enrichment failed for %s: %s", url, exc)
        return None


# ── Ollama utilities ──────────────────────────────────────────────────────────

def get_ollama_models() -> list[str]:
    """Return list of locally available model names."""
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        if resp.status_code == 200:
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass
    return []


def ollama_online() -> bool:
    """Quick liveness check for Ollama."""
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False
