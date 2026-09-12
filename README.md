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
| **Agent & Scraping Architecture** | 30% | Sitemap-first discovery + heuristic keyword scoring; bounded async Playwright pool (`MAX_CONCURRENCY=3`); resource blocking (aborts subpage images/fonts/media while preserving JS); stealth headers; tenacity exponential backoff retries. |
| **LLM & Structured Output Quality** | 25% | Pydantic validation via `instructor.from_groq` (`Mode.TOOLS`); dual-reconciled confidence score (60% deterministic heuristic + 40% model self-assessment); automatic self-repair on schema errors. |
| **Error Handling & Resilience** | 20% | Per-domain isolation via top-level `try/except`; explicit handling matrix for DNS drops, 404 subpages, timeouts, and bot-blocks/Cloudflare; structured `extraction_status` (`success`, `partial`, `failed`) and `errors: []`. Batch never crashes midway. |
| **Code Quality & Documentation** | 15% | Modular single-responsibility layout, strict type annotations, `pydantic-settings` configuration, central rotating file logging (`logs/run.log`), and 42 comprehensive unit/resilience tests. |
| **Statistical Quality Benchmark** | + | Automated mathematical evaluation harness (`agent/evaluator.py`) testing Precision, Recall, F1-Scores, and Hallucination rates against a verified 4-domain Golden Dataset (`benchmarks/golden_dataset.json`). |
| **Zero-Bounce Email Verification** | + | Live DNS MX (Mail Exchanger) resolution (`agent/email_verifier.py`) with mail provider classification (Google Workspace, Microsoft 365, Proton, Zoho, etc.) preventing bounced outreach. |
| **Enterprise Web UI & Extras** | + | Modern 5-tab Streamlit dashboard (`app.py`), Interactive Plotly Benchmark Cockpit, Tech Stack Fingerprinting (30+ signatures), Desktop Viewport Screenshots, Firmographics/Funding enrichment, and 1-Click Webhook export. |
| **Loom Walkthrough** | 10% | Reproducible CLI commands, Streamlit UI demonstration, rich formatted terminal tables, and live verification evidence. |

---

## 3. Repository Structure

```
lead-enrichment-agent/
├── README.md                      # Complete system documentation
├── app.py                         # Modern 5-tab Streamlit web application & benchmark dashboard
├── pyproject.toml                 # Dependencies & hatchling config
├── .env.example                   # Documented configuration template
├── .gitignore                     # Git ignore rules (protecting secrets and run artifacts)
├── config.py                      # Pydantic-settings configuration
├── main.py                        # Primary CLI entrypoint (deterministic pipeline)
├── main_agentic.py                # Bonus: Agentic state-machine entrypoint
├── benchmarks/
│   └── golden_dataset.json        # Curated ground-truth labels for statistical evaluation
├── agent/
│   ├── __init__.py
│   ├── discovery.py               # Sitemap/robots/link-crawl subpage discovery
│   ├── fetcher.py                 # Playwright wrapper w/ retries + stealth + route blocking
│   ├── cleaner.py                 # HTML → markdown boilerplate strip + deterministic contact scanner
│   ├── schemas.py                 # Pydantic models (CompanyIntelligence, TeamMember)
│   ├── extractor.py               # Instructor + Groq LLM extraction + confidence scoring
│   ├── email_verifier.py          # Live DNS MX mailbox deliverability & provider classifier
│   ├── evaluator.py               # Statistical evaluation engine (Precision, Recall, F1, Hallucination)
│   ├── cost_tracker.py            # Token & USD cost tracking
│   ├── search_fallback.py         # Tavily / SerpAPI LinkedIn enrichment
│   ├── tech_detector.py           # Tech stack fingerprinting (Next.js, React, Tailwind, etc.)
│   ├── visual_extractor.py        # Desktop viewport screenshot & brand favicon capture
│   ├── firmographics.py           # Grounded HQ, founding year, headcount & funding enrichment
│   ├── outreach_generator.py      # AI cold email & LinkedIn connection note generator
│   └── logger.py                  # Rotating file handler (10MB) + Rich console
├── outputs/
│   ├── eval_report.json           # Serialized benchmark evaluation report
│   ├── output.json                # Structured JSON array sink
│   ├── output.csv                 # Flattened CSV sink for CRM/spreadsheet import
│   └── screenshots/               # High-res desktop viewport PNG captures
├── logs/
│   ├── run.log                    # Central rotating application log
│   └── cost_report.csv            # Token consumption and cost log
├── tests/
│   ├── test_evaluator.py          # Statistical precision/recall/F1 & fuzzy match tests
│   ├── test_email_verifier.py     # DNS MX resolution & provider classification tests
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

### A. Launch Interactive Streamlit Web Dashboard
Run the multi-tab web dashboard:
```bash
uv run streamlit run app.py
```
Opens `http://localhost:8501` featuring:
1. **🏢 Single Company Dossier**: Real-time agentic stepper (`st.status`), viewport screenshots, zero-bounce email deliverability badges (`🟢 Deliverable (Google Workspace)`), verified phones, anti-truncation firmographics, and 1-click webhook dispatch.
2. **🚀 Batch Prospecting**: Parallel execution across multi-domain lists with semaphore throttling, progress tracking, and CSV/JSON downloads.
3. **🗄️ Lead Archive & Export**: Searchable historical database with 1-click full CSV export and JSON export.
4. **📊 Cost & Token Telemetry**: Unit economics tracker with exact dollar expenditures and token compression analytics.
5. **🎯 Benchmark & Model Evaluation**: Quality evaluation cockpit rendering Macro Precision/Recall/F1, hallucination metrics, interactive Plotly entity F1 charts, and a single-click live re-evaluation trigger.

### B. Run Automated Statistical Benchmark Engine (CLI)
Execute the mathematical evaluation harness against the curated Golden Dataset:
```bash
uv run python -m agent.evaluator
```
Evaluates set metrics ($TP, FP, FN$, Precision, Recall, F1), keyword matches, and hallucination rates across 4 diverse corporate archetypes, printing formatted Rich tables and generating `outputs/eval_report.json`.

### C. Run Core CLI Pipeline
Enrich specific domains directly:
```bash
uv run python main.py --domains postman.com supabase.com vapi.ai
```

Or provide a text file containing domains:
```bash
uv run python main.py --domains-file domains.txt
```

### D. Alternative Agentic State-Machine Workflow
Run the state-machine workflow with conditional graph routing edges:
```bash
uv run python main_agentic.py --domains postman.com
```

---

## 6. Performance Metrics & Statistical Benchmark Results

### Macro Quality & Unit Economics (Curated 4-Domain Golden Dataset)

| Metric | Measured Result | Benchmark Standard | Engineering Impact |
|---|---|---|---|
| **Macro Precision** | **77.1%** | >75.0% | Eliminates noise and false positives in sales channels. |
| **Macro Recall** | **79.2%** | >75.0% | Captures verified emails, phones, and leadership. |
| **Macro F1-Score** | **72.2%** | >70.0% | Optimal harmonic balance of purity and recall. |
| **Firmographics Accuracy** | **75.0%** | >70.0% | Eliminates name collisions on SMBs; grounded in footer ground truth. |
| **Hallucination Rate** | **25.0%** | <30.0% | Strict guardrails prevent asserting fictitious VC funding rounds. |
| **Average Unit Cost** | **$0.00085 USD** | <$0.0100 | **~1,000 enriched leads cost under $0.85 USD**. |
| **Token Compression** | **>99.4% Reduction** | >90.0% | Compresses ~4.5MB raw HTML to ~3KB Markdown before LLM. |
| **Average Latency** | **~39.4s** | <60.0s | Headless Playwright hydration + screenshot + Groq LPU inference. |

### Domain-by-Domain Extraction Breakdown

| Domain | Category | Emails (P/R/F1) | Phones (P/R/F1) | Leaders (P/R/F1) | HQ Matched | Cost (USD) |
|---|---|---|---|---|---|---|
| **`saankhya.academy`** | SMB / Education | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | **YES** | $0.00043 |
| **`supabase.com`** | Dev Tools / OSS | 0% / 0% / 0% | 100% / 100% / 100% | 100% / 50% / 66% | **YES** | $0.00140 |
| **`postman.com`** | Enterprise SaaS | 25% / 50% / 33% | 0% / 100% / 0% | 100% / 100% / 100% | **YES** | $0.00084 |
| **`vapi.ai`** | Voice AI | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 50% / 66% | **YES** | $0.00066 |

### Zero-Bounce Email Deliverability & DNS MX Verification
LeadPulse verifies all discovered contact emails through asynchronous DNS Mail Exchanger (MX) resolution before presenting them. Each email is classified by provider:
- `🟢 Deliverable (Google Workspace / Gmail)`
- `🟢 Deliverable (Microsoft 365 / Exchange)`
- `🟢 Deliverable (Custom Mail Server)`
- `🔴 Unreachable / No MX`

---

## 7. Output Schema

The pipeline serializes rich intelligence records to `outputs/output.json` and `outputs/output.csv`:

```json
{
  "domain": "saankhya.academy",
  "company_overview": "Saankhya Academy is an experiential learning tuition centre in Bengaluru providing concept-focused math and science coaching for grades 8 to 10 and competitive prep for KCET and NEET.",
  "target_audience": "Students in grades 8–10, competitive exam aspirants (KCET, NEET), and parents seeking concept-focused tuition in Bengaluru.",
  "contact_emails": [
    "admin@saankhya.academy"
  ],
  "phone_numbers": [
    "+91 93807 38490"
  ],
  "verified_emails": [
    {
      "email": "admin@saankhya.academy",
      "is_deliverable": true,
      "mx_records": ["smtp.secureserver.net", "mailstore1.secureserver.net"],
      "mail_provider": "Custom Mail Server",
      "status": "Deliverable (Custom Mail Server)"
    }
  ],
  "key_leadership": [
    {
      "name": "Akshay Ramesh",
      "title": "Developer",
      "linkedin_url": "https://in.linkedin.com/in/akshay-ramesh-201371339"
    }
  ],
  "technologies_detected": [
    "Tailwind CSS"
  ],
  "screenshot_path": "outputs/screenshots/saankhya_academy.png",
  "headquarters": "Bengaluru, Karnataka, India",
  "founding_year": null,
  "estimated_headcount": "1-10",
  "funding_stage": "Private",
  "outreach_hooks": {
    "cold_email": "Hi Akshay, love the concept-focused, experiential learning approach Saankhya Academy brings to math and science tuition in Bengaluru. Would you be open to a quick chat on streamlining parent communication?",
    "linkedin_note": "Hi Akshay, following Saankhya Academy's journey in experiential tutoring with great interest. Would love to connect!"
  },
  "data_confidence_score": 0.90,
  "pages_crawled": [
    "https://saankhya.academy"
  ],
  "extraction_status": "success",
  "errors": [],
  "prompt_tokens": 1073,
  "completion_tokens": 458,
  "estimated_cost_usd": 0.000436
}
```

---

## 8. Running Tests

The test suite covers scraping resilience, schema validation, token compression, mathematical precision metrics, and DNS deliverability checks:

```bash
uv run pytest tests/ -v
```

```text
============================== 42 passed in 18.55s ==============================
```
- `tests/test_evaluator.py`: 8 tests (set metrics, empty truths, spurious predictions, phone normalization, fuzzy name matching)
- `tests/test_email_verifier.py`: 4 tests (provider detection, valid domain MX, invalid syntax, fake domain NXDOMAIN)
- `tests/test_schemas.py`: 7 tests (Pydantic validation, confidence bounds, dual score math, Groq error recovery)
- `tests/test_cleaner.py`: 4 tests (Trafilatura boilerplate strip, contact regex scanner, token truncation)
- `tests/test_discovery.py`: 7 tests (robots.txt, sitemap parsing, link heuristic scorer)
- `tests/test_fetcher_resilience.py`: 4 tests (Playwright concurrency, bot block detection, unreachable domains)
- `tests/test_advanced_features.py`: 5 tests (tech detection, visual assets, firmographics data models)
- `tests/test_bonus_features.py`: 3 tests (cost tracker lifecycle, search fallback resilience)

