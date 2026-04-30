"""
Lead scoring — industry-agnostic quality signal.

Scoring criteria                        Max pts
──────────────────────────────────────────────
Company name present                       20
At least one email found                   25
At least one phone found                   15
Entity type identified                     15
Keywords / products listed                 10
Description provided                        8
Location identified                         7
──────────────────────────────────────────────
Total possible                            100
"""
from __future__ import annotations

from typing import Any


def score_lead(
    lead:   dict[str, Any],
    emails: list[str],
    phones: list[str],
) -> int:
    """
    Return an integer quality score in [0, 100].

    Parameters
    ----------
    lead   : Enriched lead dict (output of enrich_with_llm + contact data)
    emails : All emails found by regex extractor
    phones : All phones found by regex extractor
    """
    score = 0

    if lead.get("company"):                                        score += 20
    if emails:                                                     score += 25
    if phones:                                                     score += 15
    if lead.get("entity_type") not in (None, "", "null"):          score += 15
    if lead.get("keywords") and len(lead["keywords"]) > 0:         score += 10
    if lead.get("description"):                                    score +=  8
    if lead.get("location"):                                       score +=  7

    return min(score, 100)
