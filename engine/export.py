"""
Export helpers — CSV and JSON.

CSV export uses a fixed set of core columns plus any keys found in the
extra_data JSON column, so custom industry fields are always included.
"""
from __future__ import annotations

import csv
import io
import json

from engine.db import get_all_leads

# Core columns that are always present
_CORE_COLUMNS: list[str] = [
    "id", "company", "location", "website", "email", "phone",
    "all_emails", "all_phones", "keywords", "entity_type",
    "description", "score", "status", "notes", "run_id", "created_at",
]


def _collect_columns(leads: list[dict]) -> list[str]:
    """
    Return ordered column list: core columns first, then any extra_data
    keys discovered across all leads.
    """
    extra_keys: list[str] = []
    seen: set[str] = set(_CORE_COLUMNS)

    for lead in leads:
        raw = lead.get("extra_data") or "{}"
        try:
            extra = json.loads(raw) if isinstance(raw, str) else raw
            for k in extra:
                if k not in seen:
                    seen.add(k)
                    extra_keys.append(k)
        except (json.JSONDecodeError, TypeError):
            pass

    return _CORE_COLUMNS + extra_keys


def _flatten_lead(lead: dict, columns: list[str]) -> dict:
    """
    Flatten a lead dict for CSV export:
    - Parse extra_data JSON and merge keys into the row.
    - Stringify list fields.
    """
    raw_extra = lead.get("extra_data") or "{}"
    try:
        extra = json.loads(raw_extra) if isinstance(raw_extra, str) else raw_extra
    except (json.JSONDecodeError, TypeError):
        extra = {}

    row: dict = {**lead, **extra}

    # Stringify any remaining list/dict values
    return {col: str(row.get(col, "")) for col in columns}


def export_csv() -> str:
    """Return all leads as a UTF-8 CSV string."""
    leads   = get_all_leads()
    columns = _collect_columns(leads)

    buf    = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow(_flatten_lead(lead, columns))

    return buf.getvalue()


def export_json() -> str:
    """Return all leads as a pretty-printed JSON string."""
    return json.dumps(get_all_leads(), indent=2, default=str)
