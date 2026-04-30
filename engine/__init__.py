"""
Lead Intelligence Engine — universal pipeline.

Stage flow:
  1. build_queries  — LLM-powered (with template fallback)
  2. search_web     — SearXNG federated search
  3. fetch_concurrent — parallel HTTP fetching
  4. extract_text   — trafilatura main-content extraction
  5. enrich_with_llm — Ollama structured data extraction (dynamic schema)
  6. score_lead + insert_lead — quality score and persistence

All stages emit progress/log events onto a thread-safe Queue so the
FastAPI SSE endpoint can stream them to the browser in real time.
"""
from __future__ import annotations

import queue
from typing import Any

from engine.queries       import build_queries
from engine.searx         import search_web
from engine.fetcher_pool  import fetch_concurrent
from engine.extractor     import extract_text
from engine.regex_contact import extract_contacts
from engine.llm_extract   import enrich_with_llm, DEFAULT_SCHEMA
from engine.verify        import score_lead
from engine.db            import (
    init_db, insert_lead, is_url_cached, cache_url,
    start_run, finish_run,
)


def run_engine(params: dict[str, Any], q: queue.Queue) -> None:
    """
    Execute the full pipeline in a background thread.

    Parameters
    ----------
    params : RunParams dict (from main.py model_dump())
    q      : Thread-safe queue for SSE event dicts
    """

    def emit(type_: str, **kwargs: Any) -> None:
        q.put({"type": type_, **kwargs})

    run_id       = None
    urls_found   = 0
    urls_fetched = 0
    saved        = 0
    skipped      = 0

    try:
        init_db()

        # ── Unpack params ──────────────────────────────────────────────────────
        industry      = params.get("industry",       "general")
        locations     = params.get("locations",      [])
        keywords      = params.get("keywords",       [])
        entity_types  = params.get("entity_types",   [])
        custom_qs     = params.get("custom_queries", [])
        extra_fields  = params.get("extra_fields",   {})   # user-defined fields
        max_urls      = int(params.get("max_urls",       100))
        max_per_q     = int(params.get("max_per_query",   5))
        model         = params.get("model",          "qwen2.5")
        workers       = int(params.get("workers",        4))
        use_llm_qs    = bool(params.get("use_llm_queries", True))

        # Build extraction schema: default fields + any user-supplied extras
        schema = {**DEFAULT_SCHEMA, **extra_fields}

        run_id = start_run(params)
        emit("run_id", run_id=run_id)

        # ── STAGE 1: Build & search ────────────────────────────────────────────
        emit("stage", stage="search", status="active")
        queries = build_queries(
            industry, locations, keywords, entity_types,
            custom_queries=custom_qs,
            model=model,
            use_llm=use_llm_qs,
        )
        emit("queries", queries=queries)
        emit("log", level="info",
             msg=f"Built {len(queries)} queries for {', '.join(locations) or 'all locations'}")

        seen_urls: set[str]   = set()
        url_list: list[str]   = []
        cached_skipped        = 0

        for q_str in queries:
            if len(url_list) >= max_urls:
                break
            emit("log", level="dim", msg=f"→ {q_str}")
            results = search_web(q_str, max_per_q)
            for r in results:
                url = r.get("url", "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                if is_url_cached(url):
                    cached_skipped += 1
                    continue
                url_list.append(url)

        urls_found = len(url_list) + cached_skipped
        emit("log", level="info",
             msg=f"Collected {len(url_list)} new URLs "
                 f"({cached_skipped} already cached / skipped)")
        emit("stage", stage="search", status="done")

        if not url_list:
            emit("log", level="warn",
                 msg="No new URLs to process — try different queries or clear the cache.")
            finish_run(run_id, urls_found, 0, 0, 0, "done")
            emit("done", saved=0, skipped=0)
            return

        # ── STAGE 2: Concurrent fetch ──────────────────────────────────────────
        emit("stage", stage="fetch", status="active")
        emit("log", level="info",
             msg=f"Fetching {len(url_list)} URLs with {workers} workers…")

        fetched = fetch_concurrent(url_list, emit, workers=workers)
        urls_fetched = len(fetched)

        fetched_set = {url for url, _ in fetched}
        for url in url_list:
            cache_url(url, "ok" if url in fetched_set else "fail")

        emit("log", level="info",
             msg=f"Fetched {urls_fetched}/{len(url_list)} pages successfully")
        emit("stage", stage="fetch", status="done")

        # ── STAGE 3: Extract text ──────────────────────────────────────────────
        emit("stage", stage="extract", status="active")
        extracted: list[tuple[str, str]] = [
            (url, text)
            for url, html in fetched
            if (text := extract_text(html))
        ]
        emit("log", level="info",
             msg=f"Extracted readable text from {len(extracted)}/{urls_fetched} pages")
        emit("stage", stage="extract", status="done")

        if not extracted:
            emit("log", level="warn", msg="No readable text extracted from any page.")
            finish_run(run_id, urls_found, urls_fetched, 0, 0, "done")
            emit("done", saved=0, skipped=0)
            return

        # ── STAGE 4: LLM enrichment ────────────────────────────────────────────
        emit("stage", stage="enrich", status="active")
        emit("log", level="info",
             msg=f"LLM enrichment via Ollama ({model}) — {len(extracted)} pages…")

        enriched: list[tuple[str, list, list, dict]] = []
        total_e = len(extracted)

        for i, (url, text) in enumerate(extracted):
            pct = round((i + 1) / total_e * 100)
            emit("progress", stage="enrich", current=i + 1, total=total_e, pct=pct)
            emit("log", level="dim", msg=f"[{i+1}/{total_e}] Enriching {url[:65]}…")

            emails, phones = extract_contacts(text)
            result = enrich_with_llm(text, url, model, schema=schema)

            if result:
                enriched.append((url, emails, phones, result))
            else:
                emit("log", level="warn", msg="  ↳ LLM returned no data")

        emit("log", level="info", msg=f"Enriched {len(enriched)} leads")
        emit("stage", stage="enrich", status="done")

        # ── STAGE 5: Score & save ──────────────────────────────────────────────
        emit("stage", stage="score", status="active")

        for url, emails, phones, llm_data in enriched:
            lead: dict[str, Any] = {
                **llm_data,
                "website":    url,
                "email":      (emails[0] if emails else llm_data.get("email")) or None,
                "phone":      (phones[0] if phones else llm_data.get("phone")) or None,
                "all_emails": emails,
                "all_phones": phones,
                "run_id":     run_id,
            }
            lead["score"] = score_lead(lead, emails, phones)

            try:
                lead_id = insert_lead(lead)
                saved += 1
                emit("lead", lead={**lead, "id": lead_id})
                emit("log", level="success",
                     msg=f"✓ {lead.get('company', url[:40])} — score {lead['score']}")
            except Exception:
                skipped += 1
                emit("log", level="warn", msg=f"  ↳ Duplicate skipped: {url[:55]}")

        finish_run(run_id, urls_found, urls_fetched, saved, skipped, "done")
        emit("stage", stage="score", status="done")
        emit("log", level="success",
             msg=f"✅ Run #{run_id} complete — {saved} saved, {skipped} duplicates.")
        emit("done", saved=saved, skipped=skipped, run_id=run_id)

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        emit("log", level="error", msg=f"Fatal error: {exc}")
        emit("log", level="dim",   msg=tb[:600])
        if run_id:
            finish_run(run_id, urls_found, urls_fetched, saved, skipped, "error")
        emit("error", msg=str(exc))
