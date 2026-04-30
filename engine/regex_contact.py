"""
Regex-based email and phone extractor.

Intentionally kept as a fast pre-pass before the LLM stage.
The LLM can override/supplement these results, but regex is reliable
for well-formatted contacts.
"""
from __future__ import annotations

import re
from typing import Tuple

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}")

PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)\d{3,4}[\s\-.]?\d{3,4}"
)

# Email domains that are almost certainly junk / internal tooling
_JUNK_DOMAINS: frozenset[str] = frozenset({
    "example.com", "test.com", "domain.com", "email.com",
    "mail.com", "w3.org", "sentry.io", "googleapis.com",
    "schema.org", "placeholder.com",
})


def extract_contacts(text: str) -> Tuple[list[str], list[str]]:
    """
    Return (emails, phones) — deduplicated and filtered.
    Each list is capped at 8 items.
    """
    raw_emails = EMAIL_RE.findall(text)
    emails:  list[str] = []
    seen_e:  set[str]  = set()
    for e in raw_emails:
        e = e.lower().strip()
        domain = e.split("@")[-1]
        if e not in seen_e and domain not in _JUNK_DOMAINS:
            seen_e.add(e)
            emails.append(e)

    raw_phones = PHONE_RE.findall(text)
    phones: list[str] = []
    seen_p: set[str]  = set()
    for p in raw_phones:
        p      = p.strip()
        digits = re.sub(r"\D", "", p)
        if len(digits) >= 7 and digits not in seen_p:
            seen_p.add(digits)
            phones.append(p)

    return emails[:8], phones[:8]
