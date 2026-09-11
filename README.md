# Autonomous Lead Enrichment Agent
### SoftwareBrio AI Engineer Intern Assignment

An autonomous, multi-domain B2B lead enrichment pipeline that visits company websites, dynamically handles JavaScript-rendered content via Playwright, strips page noise with Trafilatura, and extracts structured intelligence using Groq + Instructor + Pydantic. Designed for production reliability with zero mid-run crashes, polite concurrency throttling, and full token/cost visibility.

---

## 1. System Architecture

```
                        ┌─────────────────────────┐
                        │   domains.txt / CLI arg  │
                        │  postman.com, supabase.. │
                        └────────────┬─────────────┘
                                     │
                          ┌───────────▼────────────┐
                          │   Orchestrator (async)  │
                          │  asyncio.gather + sema  │
                          └───────────┬────────────┘
                                      │  per-domain task
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      ┌───────────────┐      ┌───────────────┐        ┌───────────────┐
      │ 1. Discovery   │      │ 2. Fetch Layer │        │ 3. Clean Layer │
      │ sitemap.xml,   │─────▶│ Playwright     │───────▶│ trafilatura /  │
      │ robots.txt,    │      │ (headless,     │        │ readability →  │
      │ homepage <a>   │      │ stealth, retry)│        │ markdown text  │
      └───────────────┘      └───────────────┘        └───────┬───────┘
                                                                 │
                                                        ┌────────▼────────┐
                                                        │ 4. LLM Extractor │
                                                        │ Instructor +     │
                                                        │ Pydantic schema  │
                                                        │ (Groq inference) │
                                                        └────────┬────────┘
                                                                 │
                                                        ┌────────▼────────┐
                                                        │ 5. Confidence &  │
                                                        │    Validator     │
                                                        └────────┬────────┘
                                                                 │
                                                        ┌────────▼────────┐
                                                        │ 6. Sink: JSON/   │
                                                        │  CSV + cost log  │
                                                        └─────────────────┘
```

---

## 2. Key Features & Rubric Alignment

| Rubric Item | Weight | How It's Addressed |
|---|---|---|
| **Agent & Scraping Architecture** | 30% | Sitemap-first discovery + heuristic keyword scoring; bounded async Playwright pool (`MAX_CONCURRENCY=3`); resource blocking (aborts images/fonts/media while preserving JS); stealth headers; tenacity exponential backoff retries. |
| **LLM & Structured Output Quality** | 25% | Pydantic validation via `instructor.from_groq` (`Mode.TOOLS`); dual-reconciled confidence score (60% deterministic heuristic + 40% model self-assessment); automatic self-repair on schema errors. |
| **Error Handling & Resilience** | 20% | Per-domain isolation via top-level `try/except`; explicit handling matrix for DNS drops, 404 subpages, timeouts, and bot-blocks/Cloudflare; structured `extraction_status` (`success`, `partial`, `failed`) and `errors: []`. Batch never crashes midway. |
| **Code Quality & Documentation** | 15% | Modular single-responsibility layout, strict type annotations, `pydantic-settings` configuration, central rotating file logging (`logs/run.log`), and 30 comprehensive unit/resilience tests. |
| **Enterprise Web UI & Extras** | + | Modern Streamlit dashboard (`app.py`), Tech Stack Fingerprinting (30+ signatures), Desktop Viewport Screenshots, Firmographics/Funding enrichment, and AI Cold Outreach Generation. |
| **Loom Walkthrough** | 10% | Reproducible CLI commands, Streamlit UI demonstration, rich formatted terminal tables, and live verification evidence. |

---

## 3. Repository Structure

```
lead-enrichment-agent/
├── README.md                      # Complete system documentation
├── app.py                         # Modern 4-tab Streamlit web application
├── pyproject.toml                 # Dependencies & hatchling config
├── .env.example                   # Documented configuration template
├── .gitignore                     # Git ignore rules
├── config.py                      # Pydantic-settings configuration
├── main.py                        # Primary CLI entrypoint (deterministic pipeline)
├── main_agentic.py                # Bonus: Agentic state-machine entrypoint
├── agent/
│   ├── __init__.py
│   ├── discovery.py               # Sitemap/robots/link-crawl subpage discovery
│   ├── fetcher.py                 # Playwright wrapper w/ retries + stealth + route blocking
│   ├── cleaner.py                 # HTML → markdown boilerplate strip + token budgeting
│   ├── schemas.py                 # Pydantic models (CompanyIntelligence, TeamMember)
│   ├── extractor.py               # Instructor + Groq LLM extraction + confidence scoring
│   ├── cost_tracker.py            # Token & USD cost tracking
│   ├── search_fallback.py         # Tavily / SerpAPI LinkedIn enrichment
│   ├── tech_detector.py           # Tech stack fingerprinting (Next.js, React, Tailwind, etc.)
│   ├── visual_extractor.py        # Desktop viewport screenshot & brand favicon capture
│   ├── firmographics.py           # HQ, founding year, headcount & funding enrichment
│   ├── outreach_generator.py      # AI cold email & LinkedIn connection note generator
│   └── logger.py                  # Rotating file handler (10MB) + Rich console
├── outputs/
│   ├── output.json                # Structured JSON array sink
│   ├── output.csv                 # Flattened CSV sink for CRM/spreadsheet import
│   └── screenshots/               # High-res desktop viewport PNG captures
├── logs/
│   ├── run.log                    # Central rotating application log
│   └── cost_report.csv            # Token consumption and cost log
├── tests/
│   ├── test_discovery.py          # Sitemap, robots.txt, and link crawler tests
│   ├── test_fetcher_resilience.py # Headless rendering and network failure tests
│   ├── test_cleaner.py            # Boilerplate stripping, markdown & token budgeting tests
│   ├── test_schemas.py            # Schema validation, confidence bounds, scoring math tests
│   ├── test_bonus_features.py     # Cost tracker and search fallback tests
│   └── test_advanced_features.py  # Tech detector, firmographics, and visual extraction tests
└── PHASEWISE_LOG.md               # Auditable phasewise implementation changelog
```

---

## 4. Setup & Installation

### Prerequisites
- Python 3.11+
- `uv` (recommended) or standard `pip`

```bash
# 1. Sync virtual environment and install all dependencies
uv sync --extra dev

# 2. Install Playwright Chromium headless browser
uv run playwright install chromium

# 3. Configure environment variables
cp .env.example .env
```

Edit `.env` and configure your API keys:
```ini
GROQ_API_KEY=gsk_your_actual_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
SERPAPI_KEY=your_serpapi_key_here          # Optional: executive LinkedIn & firmographics lookup
TAVILY_API_KEY=tvly-your_tavily_key_here    # Optional: fast search fallback
MAX_CONCURRENCY=3
REQUEST_TIMEOUT_MS=30000
```

---

## 5. Usage Guide

### A. Launch Interactive Streamlit Web UI
To run the interactive web application:
```bash
uv run streamlit run app.py
```
This opens `http://localhost:8501` featuring:
1. **🎯 Single Company Dossier**: Enter any domain (e.g. `supabase.com`) to generate an executive dossier with full-page screenshot preview, leadership profiles, email contacts, tech badges, firmographics, and copyable cold outreach drafts.
2. **🚀 Batch Prospecting**: Process dozens of domains simultaneously with real-time progress bars and concurrency control.
3. **🗄️ Lead Archive & Export**: Browse and search previously enriched leads with 1-click JSON and CSV exports.
4. **📊 Cost & Token Telemetry**: Track token usage, API latency, and real-time dollar expenditures.

### B. Run CLI Pipeline
Process target domains directly:
```bash
uv run python main.py --domains postman.com supabase.com vapi.ai
```

Or provide a text file containing domains:
```bash
uv run python main.py --domains-file domains.txt
```

### CLI Options
```
options:
  -h, --help            show this help message and exit
  --domains, -d DOMAINS [DOMAINS ...]
                        One or more company domains (e.g. postman.com supabase.com vapi.ai)
  --domains-file, -f DOMAINS_FILE
                        Path to a text file containing domains, one per line
  --out, -o OUT         Path to output JSON file (default: outputs/output.json)
  --csv CSV             Path to output CSV file (default: outputs/output.csv)
  --concurrency, -c CONCURRENCY
                        Max concurrent pages/domains (default: 3)
  --model, -m MODEL     Groq model override (default: openai/gpt-oss-120b)
```

### C. Bonus: Agentic State-Machine Entrypoint
To run the state-machine workflow with conditional routing edges:
```bash
uv run python main_agentic.py --domains postman.com
```

---

## 6. Output Schema

The pipeline produces two output sinks:
1. `outputs/output.json`:
```json
[
  {
    "domain": "postman.com",
    "company_overview": "Postman is the leading collaborative API development platform. It enables engineering teams to design, test, document, and monitor APIs at scale.",
    "target_audience": "Software developers, API engineers, DevOps professionals, and enterprise engineering teams.",
    "contact_emails": ["support@postman.com", "sales@postman.com"],
    "key_leadership": [
      {
        "name": "Abhinav Asthana",
        "title": "CEO & Co-Founder",
        "linkedin_url": "https://www.linkedin.com/in/abhinavasthana"
      },
      {
        "name": "Ankit Sobti",
        "title": "CTO & Co-Founder",
        "linkedin_url": null
      }
    ],
    "technologies_detected": ["Next.js", "React", "Tailwind CSS", "Vercel", "Google Analytics", "Segment"],
    "screenshot_path": "outputs/screenshots/postman_com.png",
    "favicon_url": "https://www.postman.com/favicon.ico",
    "headquarters": "San Francisco, California, USA",
    "founded_year": 2014,
    "estimated_headcount": "1000+",
    "funding_stage": "Series D",
    "outreach_hooks": {
      "cold_email": "Hi Abhinav, noticed Postman's incredible momentum unifying API workflows across 30M+ developers. Given your rapid platform expansion, teams often face hurdles consolidating API observability. Would you be open to exploring how we streamline developer telemetry?",
      "linkedin_connection_note": "Hi Abhinav, following Postman's developer-first journey with great admiration. Would love to connect and share insights on API tooling."
    },
    "data_confidence_score": 0.88,
    "pages_crawled": [
      "https://postman.com",
      "https://postman.com/company/about-us",
      "https://postman.com/pricing"
    ],
    "extraction_status": "success",
    "errors": [],
    "prompt_tokens": 1420,
    "completion_tokens": 185,
    "estimated_cost_usd": 0.000324
  }
]
```
2. `outputs/output.csv`: Flattened tabular view ready for direct CRM import or spreadsheet analysis.
3. `logs/cost_report.csv`: Real-time audit log of tokens and dollar cost per run.

---

## 7. Running Tests

Run the full test suite (30 unit & resilience tests):
```bash
uv run pytest tests/ -v
```

