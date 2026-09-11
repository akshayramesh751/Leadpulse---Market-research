# Autonomous Lead Enrichment Agent — Build Roadmap
### SoftwareBrio AI Engineer Intern Assignment

This roadmap turns the assignment brief into a concrete, hour-by-hour execution plan. It is written so that every rubric line item (Agent & Scraping Architecture 30%, LLM & Structured Output Quality 25%, Error Handling & Resilience 20%, Code Quality & Documentation 15%, Loom Walkthrough 10%) is explicitly covered by at least one deliverable below.

---

## 0. System at a Glance

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

The full detailed rationale for **why** this shape was chosen (vs. LangGraph agentic loops, sync scraping, raw-HTML LLM calls, etc.) lives in the companion document, `02_Architecture_Decisions.md`.

---

## 1. Repository Skeleton (build this first — 30 min)

```
lead-enrichment-agent/
├── README.md
├── pyproject.toml               # or requirements.txt
├── .env.example
├── .gitignore
├── config.py                    # settings via pydantic-settings
├── main.py                      # CLI entrypoint
├── agent/
│   ├── __init__.py
│   ├── discovery.py              # subpage discovery (sitemap/robots/link-crawl)
│   ├── fetcher.py                 # Playwright wrapper w/ retries + stealth
│   ├── cleaner.py                  # HTML → markdown, boilerplate strip
│   ├── extractor.py                 # LLM call + Instructor/Pydantic schema
│   ├── search_fallback.py            # (bonus) SerpAPI/Tavily LinkedIn lookup
│   ├── cost_tracker.py                # (bonus) token + $ logging
│   └── schemas.py                      # Pydantic models
├── outputs/
│   ├── output.json
│   └── output.csv
├── logs/
│   └── run.log
└── tests/
    ├── test_cleaner.py
    ├── test_schemas.py
    └── test_fetcher_resilience.py
```

Rationale for this specific layout (single-responsibility modules, no monolithic script) maps directly to the "Code Quality & Documentation — clean functions, separation of concerns" rubric line.

---

## 2. Phase Breakdown

### Phase 1 — Environment & Config (Hour 0–2)
- [ ] `uv init` or `poetry init` → `pyproject.toml` with pinned deps: `playwright`, `trafilatura`, `instructor[groq]`, `groq`, `pydantic`, `httpx`, `tenacity`, `python-dotenv`, `rich` (for CLI logs), `pandas` (CSV export).
- [ ] `playwright install chromium --with-deps`.
- [ ] `.env.example` with `GROQ_API_KEY`, `SERPAPI_KEY` (optional), `MAX_CONCURRENCY`, `REQUEST_TIMEOUT_MS`.
- [ ] Pick a current, non-deprecated Groq model at build time (`console.groq.com/docs/models`) — as of writing, Groq has deprecated `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`; `openai/gpt-oss-120b` (or the smaller `openai/gpt-oss-20b` for a cheaper/faster run) is the current recommended general-purpose/reasoning model on their platform. Keep the model name in `config.py`, not hardcoded in `extractor.py`, so a future deprecation is a one-line fix.
- [ ] `config.py` using `pydantic-settings.BaseSettings` so nothing is hardcoded.
- [ ] Set up `logs/run.log` via Python `logging` with rotating file handler.

**Deliverable check:** `requirements.txt`/`pyproject.toml` ✅

### Phase 2 — Discovery Layer (Hour 2–6)
Goal: given `postman.com`, find the small set of high-signal URLs worth visiting (not the whole site).

- [ ] Try `https://{domain}/sitemap.xml` first — parse for URLs matching keywords (`about`, `team`, `company`, `contact`, `pricing`, `leadership`).
- [ ] Fallback: fetch homepage, extract all `<a href>` via Playwright, score links by keyword match in path/anchor text, take top 5.
- [ ] Fallback: check `robots.txt` for disallowed paths (respect them) and for a sitemap directive.
- [ ] Cap total subpages per domain at 5–6 to bound latency and token cost.
- [ ] Unit test with a mocked HTML fixture (no live network needed for the test).

### Phase 3 — Fetch Layer (Hour 4–10, parallel with Phase 2 design)
- [ ] Async Playwright context manager (`async_playwright()`), one browser instance shared, one **page per domain** via a semaphore-bound worker pool (`MAX_CONCURRENCY=3` by default — polite to target sites).
- [ ] Set realistic `user_agent`, `viewport`, and block heavy resources (`image`, `font`, `media`) via `page.route()` to save bandwidth/time — but do NOT block `script`, since JS-rendered content is required.
- [ ] `page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)` with a secondary `networkidle` wait capped at 3s (many marketing sites never truly idle).
- [ ] Wrap every navigation in `tenacity.retry` (max 2 retries, exponential backoff) — catches `TimeoutError`, `net::ERR_*`.
- [ ] Detect bot-block signatures (Cloudflare challenge title, HTTP 403/429, captcha keywords) → log + skip page, don't crash the domain.
- [ ] Return raw HTML string per page, tagged with `{url, status, html|None, error|None}`.

### Phase 4 — Content Cleaning / Token Optimization (Hour 8–12)
- [ ] Use `trafilatura.extract(html, output_format="markdown", include_links=True, include_tables=True)` as primary extractor (purpose-built for exactly this: strips nav/scripts/CSS, keeps semantic text).
- [ ] Fallback to `readability-lxml` + `markdownify` if trafilatura returns `None` (some SPA-heavy pages need this).
- [ ] Regex-strip residual `mailto:` obfuscation patterns and collapse excess whitespace/newlines.
- [ ] Truncate combined markdown per domain to a token budget (e.g., ~6k tokens) using `tiktoken`/`anthropic` tokenizer, prioritizing homepage + about/team pages over pricing/contact if something must be cut.
- [ ] Log **before/after character count** per page — this becomes the evidence for the "token optimization" rubric line and for the bonus cost-tracking feature.

### Phase 5 — LLM Structured Extraction (Hour 10–16)
- [ ] Define `schemas.py` with Pydantic models (see section 3 below).
- [ ] Use `instructor.from_provider("groq/openai/gpt-oss-120b", async_client=True)` (or `instructor.from_groq(Groq(api_key=...), mode=instructor.Mode.TOOLS)` on older Instructor versions) so the LLM call directly returns a validated `CompanyIntelligence` object — no manual JSON parsing, no silent schema drift. Groq's OpenAI-compatible API + tool-calling mode is what Instructor's structured-output support relies on for this provider.
- [ ] System prompt: extraction-only persona, explicit instruction to output `null`/empty list rather than hallucinate emails or LinkedIn URLs not present in the text.
- [ ] Pass the **cleaned markdown from all pages of one domain concatenated with page-source headers** (`## Source: /about`) so the model can attribute claims.
- [ ] Compute `data_confidence_score` two ways and reconcile:
  - Heuristic score: proportion of schema fields the model filled non-null.
  - Model's own self-reported confidence (prompted explicitly).
  - Final score = weighted average (60% heuristic, 40% self-reported) — this avoids blindly trusting an LLM's self-assessment while still using its judgment on text quality/ambiguity.
- [ ] Retry the LLM call once on `ValidationError` with the error message fed back into the prompt (Instructor supports this natively via `max_retries`).
- [ ] Groq is fast but rate-limited on free/dev tiers (requests-per-minute and tokens-per-minute caps) — wrap the extraction call in the same `tenacity` retry/backoff used for fetching, catching `groq.RateLimitError` specifically, and keep `MAX_CONCURRENCY` modest so you don't burn through the per-minute quota across 3 domains firing near-simultaneously.

### Phase 6 — Resilience & Fallback Orchestration (Hour 14–18, cross-cutting)
- [ ] Wrap the **entire per-domain pipeline** in a top-level `try/except` inside the orchestrator so one domain's total failure never stops the batch — always emit a partial record with an `errors: []` field instead of crashing.
- [ ] Explicit handling matrix:

  | Failure | Handling |
  |---|---|
  | DNS/connection error | mark domain `unreachable`, skip, continue |
  | 404 on a subpage | drop that page, keep others |
  | Bot-block/Captcha | log warning, mark `partial_data=True`, continue with whatever was fetched pre-block |
  | Timeout | retry x2 with backoff, then skip page |
  | LLM validation error | retry once with error feedback, then emit partial record with `extraction_status="failed"` |
  | Empty extracted text | skip LLM call entirely (saves cost), mark `no_content=True` |

- [ ] Central `logging` (not just print) at INFO for progress, WARNING for recoverable issues, ERROR for domain-level failures — this log file itself becomes Loom-video evidence.

### Phase 7 — Bonus Features (Hour 16–20, if time permits)
- [ ] `search_fallback.py`: if `key_leadership` entries lack a `linkedin_url`, query Tavily/SerpAPI with `"{name} {company} LinkedIn"`, take the top result if domain is `linkedin.com/in/`.
- [ ] `cost_tracker.py`: capture `usage.prompt_tokens` / `usage.completion_tokens` from each Groq response, multiply by Groq's published per-model per-token pricing (check `groq.com/pricing`, since it varies by model and is generally cheap relative to Claude/GPT-4-class APIs), log per-domain and total cost to `logs/cost_report.csv`. Worth calling out in the README/Loom that Groq's low latency is exactly why the extraction step doesn't bottleneck the pipeline the way a slower provider might.
- [ ] Optional: a tiny LangGraph state machine that wraps Phases 2–5 as nodes with conditional edges (retry loop, search-fallback loop) — presented as an *alternate* entrypoint (`main_agentic.py`) so the primary deterministic pipeline stays the reliable default. (See architecture doc for why this is offered as *optional*, not default.)

### Phase 8 — Testing & Validation (Hour 18–22)
- [ ] Unit tests: cleaner strips scripts/nav correctly (fixture-based, no network); schema rejects malformed confidence score (`>1.0`); fetcher retry logic triggers on simulated timeout (mock).
- [ ] Integration run: execute `main.py --domains postman.com supabase.com vapi.ai --out outputs/output.json`.
- [ ] Manually spot-check 1 field per domain against the live site to sanity-check extraction accuracy.
- [ ] Confirm the script completes even if you intentionally break one domain (e.g., typo a domain) — proves resilience live.

### Phase 9 — Documentation (Hour 20–24)
- [ ] `README.md` sections: Overview → Architecture diagram (ASCII, copy from Section 0 above) → Setup (`.env`, `playwright install`) → Usage (`python main.py --domains ...`) → Output schema explanation → Known limitations → Bonus features toggle instructions.
- [ ] Docstrings + type hints on every public function (mypy-clean if time allows).
- [ ] `.env.example` fully commented.

### Phase 10 — Recording & Submission (Hour 22–26, well inside the 48–72h window)
- [ ] Record a 2–3 min Loom: (1) 30s code structure walkthrough in the repo tree, (2) 60–90s live terminal run against the 3 domains, (3) 30–60s scroll through `output.json` highlighting one fully-populated record and one gracefully-partial record (proves resilience on camera).
- [ ] Push to a public (or invite-shared) GitHub repo.
- [ ] Email `support@softwarebrio.com`, subject `[AI Intern Submission] - [Your Full Name]`, include LinkedIn profile and the explicit **Yes/No** answer to the 40%-manual-ops screening question, plus GitHub link, Loom link, and attach/link `output.json`.

---

## 3. Pydantic Schema (drop-in for `schemas.py`)

```python
from pydantic import BaseModel, Field, EmailStr, confloat
from typing import Optional

class TeamMember(BaseModel):
    name: str
    title: Optional[str] = None
    linkedin_url: Optional[str] = None

class CompanyIntelligence(BaseModel):
    domain: str
    company_overview: str = Field(..., description="2-sentence summary of what the company does")
    target_audience: str = Field(..., description="Who the product is built for (ICP)")
    contact_emails: list[str] = Field(default_factory=list)
    key_leadership: list[TeamMember] = Field(default_factory=list)
    data_confidence_score: confloat(ge=0.0, le=1.0)
    pages_crawled: list[str] = Field(default_factory=list)
    extraction_status: str = Field(default="success")  # success | partial | failed
    errors: list[str] = Field(default_factory=list)
```

---

## 4. Rubric Coverage Map

| Rubric Item | Weight | Covered By |
|---|---|---|
| Agent & Scraping Architecture | 30% | Phases 2–3: sitemap-first discovery, async Playwright pool, resource blocking, retry/backoff |
| LLM & Structured Output Quality | 25% | Phase 5: Instructor+Pydantic, self-repair on validation error, confidence scoring |
| Error Handling & Resilience | 20% | Phase 6 handling matrix, per-domain try/except, `extraction_status` field |
| Code Quality & Documentation | 15% | Repo skeleton, type hints, docstrings, README, tests |
| Loom Walkthrough | 10% | Phase 10 structured 3-beat recording plan |

---

## 5. Suggested 72-Hour Calendar (if you take the full window)

| Day | Focus |
|---|---|
| Day 1 (0–24h) | Repo skeleton, discovery + fetch layer, cleaning layer, first successful raw-markdown output for all 3 domains |
| Day 2 (24–48h) | LLM extraction + schema validation, resilience matrix, bonus features (search fallback, cost tracking) |
| Day 3 (48–72h) | Tests, README, polish, Loom recording, submission email |

Build in slack — aim to have a working end-to-end (even if rough) pipeline by hour 20, so the remaining time goes to resilience polish and documentation rather than first-time integration debugging.
