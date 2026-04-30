"""
Lead Intelligence Engine v5 — FastAPI application.

Changes from v4:
  • @app.on_event("startup") replaced with lifespan context manager (FastAPI ≥ 0.93)
  • asyncio.get_running_loop() replaces deprecated get_event_loop()
  • RunParams is now industry-agnostic:
      - `keywords`     replaces `products`
      - `entity_types` replaces `buyer_types`
      - `industry`     (new) — context for LLM query generation
      - `extra_fields` (new) — custom extraction schema fields
      - `use_llm_queries` (new) — toggle LLM-powered query building
  • STATIC_DIR uses pathlib (cross-platform)
"""
from __future__ import annotations

import asyncio
import json
import queue as thread_queue
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import OLLAMA_URL, STATIC_DIR
from engine import run_engine
from engine.db import (
    clear_leads, count_leads, get_all_leads, get_lead,
    get_runs, get_stats, init_db, update_lead,
    clear_url_cache, count_cached_urls,
)
from engine.export import export_csv, export_json
from engine.llm_extract import get_ollama_models
from engine.searx import reset_instance_cache


# ── Job store: job_id → Queue ─────────────────────────────────────────────────
_jobs: dict[str, thread_queue.Queue] = {}


# ── Lifespan (replaces deprecated @app.on_event) ─────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    init_db()
    yield
    # (teardown hooks can go here if needed)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Lead Intelligence Engine", version="5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

class RunParams(BaseModel):
    # Context
    industry:       str             = Field("general", description="Industry context for LLM query generation")

    # Search dimensions
    locations:      list[str]       = Field(default_factory=list,  description="Target countries or cities")
    keywords:       list[str]       = Field(default_factory=list,  description="Products, services, or topics")
    entity_types:   list[str]       = Field(default_factory=list,  description="Types of entity to find (importer, wholesaler, …)")
    custom_queries: list[str]       = Field(default_factory=list,  description="Additional raw search queries")

    # Extraction
    extra_fields:   dict[str, str]  = Field(default_factory=dict,  description="Extra schema fields: {field_name: type_hint}")

    # Engine settings
    max_urls:       int             = Field(100,   ge=1,  le=500)
    max_per_query:  int             = Field(5,     ge=1,  le=20)
    model:          str             = "qwen2.5"
    workers:        int             = Field(4,     ge=1,  le=16)
    use_llm_queries: bool           = Field(True,  description="Use LLM to generate search queries (falls back to template)")


class LeadPatch(BaseModel):
    status: Optional[str] = None
    notes:  Optional[str] = None


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    models:    list[str] = []
    ollama_ok: bool      = False
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                ollama_ok = True
                models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass

    return {
        "db":          "ok",
        "db_leads":    count_leads(),
        "cached_urls": count_cached_urls(),
        "ollama":      "ok" if ollama_ok else "offline",
        "models":      models,
        "version":     "5.0",
    }


# ── Engine run ────────────────────────────────────────────────────────────────

@app.post("/api/run")
async def start_run(params: RunParams):
    job_id = str(uuid.uuid4())
    q: thread_queue.Queue = thread_queue.Queue()
    _jobs[job_id] = q
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, run_engine, params.model_dump(), q)
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream_events(job_id: str):
    q = _jobs.get(job_id)
    if not q:
        raise HTTPException(status_code=404, detail="Job not found")

    async def generator():
        yield 'data: {"type":"connected"}\n\n'
        while True:
            try:
                event = await asyncio.to_thread(q.get, True, 2.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    _jobs.pop(job_id, None)
                    break
            except thread_queue.Empty:
                yield ": heartbeat\n\n"
            except Exception as exc:
                yield f'data: {{"type":"error","msg":"{exc}"}}\n\n'
                _jobs.pop(job_id, None)
                break

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Leads ─────────────────────────────────────────────────────────────────────

@app.get("/api/leads")
async def get_leads():
    return get_all_leads()


@app.get("/api/leads/{lead_id}")
async def get_single_lead(lead_id: int):
    lead = get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@app.patch("/api/leads/{lead_id}")
async def patch_lead(lead_id: int, body: LeadPatch):
    update_lead(lead_id, body.status, body.notes)
    return get_lead(lead_id)


@app.delete("/api/leads")
async def delete_leads():
    clear_leads()
    return {"ok": True}


# ── Stats & runs ──────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def stats():
    return get_stats()


@app.get("/api/runs")
async def runs():
    return get_runs(limit=10)


# ── Cache ─────────────────────────────────────────────────────────────────────

@app.delete("/api/cache")
async def clear_cache():
    clear_url_cache()
    reset_instance_cache()
    return {"ok": True, "msg": "URL cache and instance cache cleared"}


# ── Exports ───────────────────────────────────────────────────────────────────

@app.get("/api/export/csv")
async def download_csv():
    return Response(
        content=export_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.get("/api/export/json")
async def download_json():
    return Response(
        content=export_json(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=leads.json"},
    )
