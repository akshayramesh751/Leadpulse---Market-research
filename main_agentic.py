"""Optional Agentic Entrypoint - State Machine Workflow for Lead Enrichment.

Demonstrates an agentic node-and-edge pipeline with conditional evaluation
as an alternative entrypoint to the primary deterministic pipeline.
"""

import asyncio
import argparse
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
from rich.console import Console

from config import settings
from agent.logger import logger
from agent.discovery import discover_subpages, normalize_domain
from agent.fetcher import PlaywrightFetcher, FetchResult
from agent.cleaner import build_domain_context
from agent.schemas import CompanyIntelligence
from agent.extractor import extract_company_intelligence
from agent.search_fallback import enrich_leadership_linkedin
from agent.cost_tracker import CostTracker

console = Console()


@dataclass
class AgentState:
    """State carried through the agentic state machine."""
    domain: str
    target_urls: List[str] = field(default_factory=list)
    fetch_results: List[FetchResult] = field(default_factory=list)
    cleaned_markdown: str = ""
    cleaning_stats: Dict[str, Any] = field(default_factory=dict)
    intelligence: Optional[CompanyIntelligence] = None
    errors: List[str] = field(default_factory=list)
    step: str = "DISCOVERY"


class AgenticLeadEnricher:
    """State-machine workflow with conditional routing."""

    def __init__(self, fetcher: PlaywrightFetcher, cost_tracker: CostTracker):
        self.fetcher = fetcher
        self.cost_tracker = cost_tracker

    async def step_discovery(self, state: AgentState) -> AgentState:
        logger.info(f"[Agentic: {state.domain}] Node 1: Discovering high-signal URLs")
        state.target_urls = await discover_subpages(state.domain)
        state.step = "FETCH"
        return state

    async def step_fetch(self, state: AgentState) -> AgentState:
        logger.info(f"[Agentic: {state.domain}] Node 2: Fetching {len(state.target_urls)} pages with Playwright")
        state.fetch_results = await self.fetcher.fetch_urls(state.target_urls)
        # Check if any pages succeeded
        successes = [r for r in state.fetch_results if r.is_success and r.html]
        if not successes:
            state.errors.append("All discovered URLs failed to fetch")
            state.step = "TERMINAL"
        else:
            state.step = "CLEAN"
        return state

    async def step_clean(self, state: AgentState) -> AgentState:
        logger.info(f"[Agentic: {state.domain}] Node 3: Cleaning boilerplate and budgeting tokens")
        pages = [(r.url, r.html) for r in state.fetch_results if r.is_success and r.html]
        state.cleaned_markdown, state.cleaning_stats = build_domain_context(pages)
        if not state.cleaned_markdown.strip():
            state.errors.append("Zero readable content extracted from pages")
            state.step = "TERMINAL"
        else:
            state.step = "EXTRACT"
        return state

    async def step_extract(self, state: AgentState) -> AgentState:
        logger.info(f"[Agentic: {state.domain}] Node 4: LLM extraction with Instructor + Groq")
        crawled = [r.url for r in state.fetch_results]
        intel = await extract_company_intelligence(
            domain=state.domain,
            markdown_content=state.cleaned_markdown,
            pages_crawled=crawled,
        )
        state.intelligence = intel

        # Conditional routing edge: check if leadership needs LinkedIn enrichment
        needs_linkedin = (
            intel.key_leadership and
            any(m.linkedin_url is None for m in intel.key_leadership) and
            (settings.tavily_api_key or settings.serpapi_key)
        )

        if needs_linkedin:
            state.step = "SEARCH_FALLBACK"
        else:
            state.step = "FINALIZE"
        return state

    async def step_search_fallback(self, state: AgentState) -> AgentState:
        logger.info(f"[Agentic: {state.domain}] Node 5: Enriching leadership with external search fallback")
        if state.intelligence and state.intelligence.key_leadership:
            state.intelligence.key_leadership = await enrich_leadership_linkedin(
                leadership=state.intelligence.key_leadership,
                company_domain=state.domain,
            )
        state.step = "FINALIZE"
        return state

    async def step_finalize(self, state: AgentState) -> AgentState:
        logger.info(f"[Agentic: {state.domain}] Node 6: Finalizing and recording metrics")
        if state.intelligence:
            if state.intelligence.prompt_tokens and state.intelligence.completion_tokens:
                cost = self.cost_tracker.record_usage(
                    domain=state.domain,
                    model=settings.groq_model,
                    prompt_tokens=state.intelligence.prompt_tokens,
                    completion_tokens=state.intelligence.completion_tokens,
                )
                state.intelligence.estimated_cost_usd = cost
            if state.errors:
                state.intelligence.errors.extend(state.errors)
        state.step = "TERMINAL"
        return state

    async def run(self, domain: str) -> CompanyIntelligence:
        norm_domain = normalize_domain(domain)
        state = AgentState(domain=norm_domain)

        # State machine transition loop
        while state.step != "TERMINAL":
            if state.step == "DISCOVERY":
                state = await self.step_discovery(state)
            elif state.step == "FETCH":
                state = await self.step_fetch(state)
            elif state.step == "CLEAN":
                state = await self.step_clean(state)
            elif state.step == "EXTRACT":
                state = await self.step_extract(state)
            elif state.step == "SEARCH_FALLBACK":
                state = await self.step_search_fallback(state)
            elif state.step == "FINALIZE":
                state = await self.step_finalize(state)
            else:
                break

        if not state.intelligence:
            return CompanyIntelligence(
                domain=norm_domain,
                company_overview="Agentic workflow terminated with no extraction.",
                target_audience="Unknown",
                contact_emails=[],
                key_leadership=[],
                data_confidence_score=0.0,
                pages_crawled=[r.url for r in state.fetch_results],
                extraction_status="failed",
                errors=state.errors,
            )

        return state.intelligence


async def main_agentic():
    parser = argparse.ArgumentParser(description="Agentic state-machine variant of Lead Enrichment Agent")
    parser.add_argument("--domains", "-d", nargs="+", default=["postman.com"], help="Domain(s) to process")
    args = parser.parse_args()

    console.print(f"[bold magenta]Starting Agentic Workflow for {args.domains}...[/bold magenta]")
    cost_tracker = CostTracker()

    async with PlaywrightFetcher() as fetcher:
        agent = AgenticLeadEnricher(fetcher=fetcher, cost_tracker=cost_tracker)
        for d in args.domains:
            res = await agent.run(d)
            console.print(f"[green]Result for {d}: status={res.extraction_status}, confidence={res.data_confidence_score}[/green]")
            console.print(f"[cyan]Overview:[/cyan] {res.company_overview}")


if __name__ == "__main__":
    asyncio.run(main_agentic())
