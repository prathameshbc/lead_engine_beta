# Lead Intelligence Engine

> A universal, LLM-powered B2B lead generation engine. Search any industry, extract any fields, export clean structured data.

---

## What it does

1. **Generates search queries** via an LLM (Ollama) based on your industry, target locations, keywords, and entity types — with an automatic template fallback when Ollama is offline.
2. **Searches the web** using federated SearXNG instances (no API keys required).
3. **Fetches pages concurrently** with a configurable worker pool.
4. **Extracts structured data** via a dynamic, schema-driven LLM prompt — default fields cover any B2B lead; add custom fields for your industry.
5. **Scores, deduplicates, and stores** results in a local SQLite database.
6. **Exports** to CSV or JSON from the built-in web UI.

---

## Quick Start

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| [Ollama](https://ollama.com/download) | Any recent |
| A pulled model | `ollama pull qwen2.5` |
| local searxng instance| (setup required edit searxng url with local url)

### Setup

```bash
git clone (https://github.com/prathameshbc/lead_engine_beta.git
cd lead-engine
python setup.py          # creates venv, installs deps, checks Ollama
```

### Run

```bash
python run.py
# → opens http://localhost:8000 automatically
```

Advanced options:
```bash
python run.py --port 9000 --no-browser   # custom port, no browser
python run.py --reload                   # hot-reload for development
```

---

## Configuration

Copy `.env.example` to `.env` and edit:

```ini
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5
DB_NAME=leads.db
MAX_TOTAL_URLS=100
FETCH_WORKERS=4
PORT=8000
```

All settings can also be passed as environment variables.

---

## Universal Field Mapping

The engine is **not hardcoded for any industry**. You control:

### Core parameters (UI)

| Parameter | Description | Example |
|---|---|---|
| `industry` | Context for LLM query generation | `"pharmaceutical"` |
| `locations` | Target countries or cities | `["Germany", "Japan"]` |
| `keywords` | Products, services, topics | `["APIs", "SaaS platform"]` |
| `entity_types` | Types of company to find | `["reseller", "distributor"]` |

### Custom extraction fields (API)

Add any field to the schema via `extra_fields` in the API request:

```json
POST /api/run
{
  "industry": "pharmaceutical",
  "locations": ["Germany", "Switzerland"],
  "keywords": ["generic drugs", "OTC medication"],
  "entity_types": ["wholesaler", "distributor"],
  "extra_fields": {
    "annual_revenue": "string (e.g. '$5M–$20M') or null",
    "certifications": "array of strings (ISO, GMP, etc.) or null",
    "num_employees":  "string (e.g. '50–200') or null"
  }
}
```

Custom fields are stored in a JSON `extra_data` column and included in CSV/JSON exports automatically.

---

## Architecture

```
lead_engine/
├── main.py                 # FastAPI application (lifespan, SSE streaming)
├── config.py               # Centralised config (pathlib, dotenv, env vars)
├── setup.py                # Cross-platform setup script
├── run.py                  # Cross-platform launcher (Windows/macOS/Linux)
├── requirements.txt
├── .env.example
├── .gitignore
├── engine/
│   ├── __init__.py         # Pipeline orchestrator (5-stage flow)
│   ├── queries.py          # LLM-powered query builder + template fallback
│   ├── searx.py            # SearXNG federated search client
│   ├── fetcher_pool.py     # Concurrent HTTP fetching (ThreadPoolExecutor)
│   ├── extractor.py        # HTML → clean text (trafilatura)
│   ├── regex_contact.py    # Email + phone regex extraction
│   ├── llm_extract.py      # Universal schema-driven LLM extraction
│   ├── verify.py           # Lead quality scoring
│   ├── db.py               # SQLite (WAL, per-thread pool, pathlib)
│   └── export.py           # CSV / JSON export with dynamic columns
└── static/
    └── index.html          # Single-file web UI
```

### Pipeline flow

```
build_queries (LLM / template)
       ↓
search_web (SearXNG federation)
       ↓
fetch_concurrent (ThreadPoolExecutor)
       ↓
extract_text (trafilatura)
       ↓
regex_contact + enrich_with_llm (dynamic schema)
       ↓
score_lead → insert_lead (SQLite WAL)
       ↓
SSE stream → browser
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/run` | Start a new engine run |
| `GET` | `/api/stream/{job_id}` | SSE stream of run events |
| `GET` | `/api/leads` | All leads (sorted by score) |
| `GET` | `/api/leads/{id}` | Single lead |
| `PATCH` | `/api/leads/{id}` | Update status / notes |
| `DELETE` | `/api/leads` | Clear all leads |
| `GET` | `/api/stats` | Aggregate statistics |
| `GET` | `/api/runs` | Recent run history |
| `DELETE` | `/api/cache` | Clear URL + instance cache |
| `GET` | `/api/export/csv` | Download leads as CSV |
| `GET` | `/api/export/json` | Download leads as JSON |
| `GET` | `/api/health` | DB + Ollama liveness check |

---

## Performance notes

- **4 fetch workers** is the safe default for an 8 GB laptop.  
  Increase `FETCH_WORKERS` (or the `workers` param) for faster crawls on bigger machines.
- The **URL cache** prevents re-fetching pages from earlier runs. Clear it via the UI or `DELETE /api/cache`.
- SQLite **WAL mode** allows concurrent reads during writes, avoiding blocking the FastAPI event loop.
- The **per-thread connection pool** (`threading.local`) eliminates connection setup overhead in the ThreadPoolExecutor.

---

## Upgrading from v4

| v4 field | v5 field | Notes |
|---|---|---|
| `products` | `keywords` | Renamed for universality |
| `buyer_types` | `entity_types` | Renamed for universality |
| `buyer_type` (DB col) | `entity_type` | Migration runs automatically |
| hardcoded textile schema | dynamic `extra_fields` | Pass any fields you need |
| bash `setup.sh` / `run.sh` | Python `setup.py` / `run.py` | Works on Windows too |

The database migrates automatically on first startup — existing data is preserved.

---

## License

MIT
