"""Autonomous Lead Enrichment Agent - CLI Entrypoint and Orchestrator.

Orchestrates multi-domain discovery, Playwright fetching, content cleaning,
LLM structured extraction with Groq + Instructor, resilience error handling,
and output sinks (JSON and CSV).
"""

import re
import sys
import json
import asyncio
import argparse
from pathlib import Path
from typing import List, Optional
import pandas as pd
from rich.console import Console
from rich.table import Table

from config import settings
from agent.logger import logger
from agent.discovery import discover_subpages, normalize_domain
from agent.fetcher import PlaywrightFetcher, FetchResult
from agent.cleaner import build_domain_context, extract_contact_info_from_html
from agent.schemas import CompanyIntelligence
from agent.extractor import extract_company_intelligence
from agent.search_fallback import enrich_leadership_linkedin
from agent.cost_tracker import CostTracker
from agent.tech_detector import detect_technologies
from agent.firmographics import enrich_firmographics
from agent.outreach_generator import generate_outreach_hooks
from agent.email_verifier import verify_emails

console = Console()


async def process_domain(
    domain: str,
    fetcher: PlaywrightFetcher,
    cost_tracker: CostTracker,
    model_override: Optional[str] = None,
) -> CompanyIntelligence:
    """Processes a single company domain end-to-end with full failure isolation."""
    clean_domain = normalize_domain(domain)
    errors: List[str] = []
    logger.info(f"=== Starting enrichment for {clean_domain} ===")

    try:
        # ------------------------------------------------------------------
        # 1. Discovery Layer: Find high-signal URLs (sitemap + link crawl)
        # ------------------------------------------------------------------
        logger.info(f"[{clean_domain}] Discovering target subpages...")
        target_urls = await discover_subpages(clean_domain)
        logger.info(f"[{clean_domain}] Discovered {len(target_urls)} URLs: {target_urls}")

        # ------------------------------------------------------------------
        # 2. Fetch Layer: Headless Chromium via Playwright (w/ Screenshot)
        # ------------------------------------------------------------------
        logger.info(f"[{clean_domain}] Fetching pages with Playwright...")
        fetch_results: List[FetchResult] = await fetcher.fetch_urls(target_urls, domain=clean_domain)

        successful_pages: List[tuple[str, str]] = []
        crawled_urls: List[str] = []
        is_partial = False

        screenshot_path = fetch_results[0].screenshot_path if fetch_results else None
        logo_url = fetch_results[0].logo_url if fetch_results else None
        homepage_html = fetch_results[0].html if fetch_results and fetch_results[0].html else ""
        homepage_headers = fetch_results[0].headers if fetch_results else {}

        for res in fetch_results:
            crawled_urls.append(res.url)
            if res.is_success and res.html:
                successful_pages.append((res.url, res.html))
            else:
                is_partial = True
                if res.is_bot_blocked:
                    errors.append(f"Bot block/challenge at {res.url}")
                elif res.error:
                    errors.append(f"Fetch failed for {res.url}: {res.error}")

        if not successful_pages:
            logger.warning(f"[{clean_domain}] No pages could be fetched successfully")
            errors.append("All discovered URLs failed to fetch (possible DNS, network error, or hard block)")
            return CompanyIntelligence(
                domain=clean_domain,
                company_overview="Domain unreachable or blocked during fetch.",
                target_audience="Unknown",
                contact_emails=[],
                key_leadership=[],
                data_confidence_score=0.0,
                pages_crawled=crawled_urls,
                extraction_status="failed",
                errors=errors,
            )

        # ------------------------------------------------------------------
        # 3. Tech Stack Detection
        # ------------------------------------------------------------------
        logger.info(f"[{clean_domain}] Fingerprinting technology stack...")
        techs_detected = detect_technologies(homepage_html, headers=homepage_headers)
        logger.info(f"[{clean_domain}] Detected {len(techs_detected)} technologies: {techs_detected}")

        # ------------------------------------------------------------------
        # 4. Clean Layer: Strip boilerplate & budget tokens
        # ------------------------------------------------------------------
        logger.info(f"[{clean_domain}] Cleaning HTML and assembling token context...")
        domain_markdown, stats = build_domain_context(successful_pages)

        if not domain_markdown.strip():
            logger.warning(f"[{clean_domain}] Empty content after cleaning")
            errors.append("Clean layer produced zero text from fetched pages")
            return CompanyIntelligence(
                domain=clean_domain,
                company_overview="No readable text extracted from domain pages.",
                target_audience="Unknown",
                contact_emails=[],
                key_leadership=[],
                data_confidence_score=0.0,
                pages_crawled=crawled_urls,
                extraction_status="failed",
                errors=errors,
            )

        # ------------------------------------------------------------------
        # 5. LLM Extraction Layer: Groq + Instructor + Pydantic
        # ------------------------------------------------------------------
        logger.info(f"[{clean_domain}] Extracting intelligence via LLM...")
        intel = await extract_company_intelligence(
            domain=clean_domain,
            markdown_content=domain_markdown,
            pages_crawled=crawled_urls,
            override_model=model_override,
        )

        # Extract deterministic contact info directly from all raw HTML pages
        html_emails = set()
        html_phones = set()
        for _, raw_html in successful_pages:
            ci = extract_contact_info_from_html(raw_html)
            html_emails.update(ci["emails"])
            html_phones.update(ci["phones"])

        # Merge deterministic emails and phones with LLM extraction (preserving order & uniqueness)
        existing_emails = getattr(intel, "contact_emails", []) or []
        intel.contact_emails = list(dict.fromkeys(existing_emails + sorted(list(html_emails))))
        
        existing_phones = getattr(intel, "phone_numbers", []) or []
        combined_phones = existing_phones + sorted(list(html_phones))
        deduped_phones = {}
        for p in sorted(combined_phones, key=lambda x: (len(x), " " in x or "-" in x), reverse=True):
            d_key = re.sub(r"[^\d]", "", p)
            if d_key and d_key not in deduped_phones:
                deduped_phones[d_key] = p
        
        try:
            intel.phone_numbers = list(deduped_phones.values())
        except Exception:
            pass

        # Zero-Bounce Deliverability Audit: resolve DNS MX records
        if intel.contact_emails:
            logger.info(f"[{clean_domain}] Auditing email deliverability via DNS MX resolution...")
            try:
                intel.verified_emails = await verify_emails(intel.contact_emails)
            except Exception as e:
                logger.debug(f"Email deliverability check error: {e}")

        intel.technologies_detected = techs_detected
        intel.screenshot_path = screenshot_path
        intel.logo_url = logo_url

        # Merge any warnings/errors from earlier layers
        if errors:
            intel.errors.extend(errors)
            if intel.extraction_status == "success":
                intel.extraction_status = "partial"

        # ------------------------------------------------------------------
        # 6. Bonus: Search Fallback for LinkedIn Profiles
        # ------------------------------------------------------------------
        if intel.key_leadership:
            enriched_leadership = await enrich_leadership_linkedin(
                leadership=intel.key_leadership,
                company_domain=clean_domain,
            )
            intel.key_leadership = enriched_leadership

        # ------------------------------------------------------------------
        # 7. Bonus: Firmographics & Funding Lookup (Grounded in Website Text)
        # ------------------------------------------------------------------
        logger.info(f"[{clean_domain}] Enriching firmographics & funding...")
        firmo = await enrich_firmographics(clean_domain, website_text=domain_markdown)
        intel.headquarters = firmo.headquarters
        intel.founding_year = firmo.founding_year
        intel.estimated_headcount = firmo.estimated_headcount
        intel.funding_stage = firmo.funding_stage

        # ------------------------------------------------------------------
        # 8. Bonus: AI Cold Outreach Generator
        # ------------------------------------------------------------------
        logger.info(f"[{clean_domain}] Drafting AI personalized outreach hooks...")
        lead_exec = intel.key_leadership[0] if intel.key_leadership else None
        intel.outreach_hooks = await generate_outreach_hooks(
            domain=clean_domain,
            overview=intel.company_overview,
            target_audience=intel.target_audience,
            executive=lead_exec,
        )

        # ------------------------------------------------------------------
        # 9. Bonus: Token & Cost Tracking
        # ------------------------------------------------------------------
        if intel.prompt_tokens is not None and intel.completion_tokens is not None:
            active_model = model_override or settings.groq_model
            cost = cost_tracker.record_usage(
                domain=clean_domain,
                model=active_model,
                prompt_tokens=intel.prompt_tokens,
                completion_tokens=intel.completion_tokens,
            )
            intel.estimated_cost_usd = cost

        logger.info(f"[{clean_domain}] Completed with status={intel.extraction_status}, confidence={intel.data_confidence_score}")
        return intel

    except Exception as e:
        # Top-level isolation: one domain's failure NEVER halts the entire batch
        error_msg = f"Unhandled domain exception: {type(e).__name__}: {str(e)}"
        logger.exception(f"[{clean_domain}] {error_msg}")
        errors.append(error_msg)
        return CompanyIntelligence(
            domain=clean_domain,
            company_overview="Failed due to an unexpected system error.",
            target_audience="Unknown",
            contact_emails=[],
            key_leadership=[],
            data_confidence_score=0.0,
            pages_crawled=[],
            extraction_status="failed",
            errors=errors,
        )


async def run_pipeline(
    domains: List[str],
    output_json: Path,
    output_csv: Path,
    concurrency: int,
    model_override: Optional[str] = None,
) -> List[CompanyIntelligence]:
    """Runs the lead enrichment pipeline over a list of domains in parallel."""
    if not domains:
        logger.warning("No domains supplied to enrich.")
        return []

    console.print(f"[bold cyan]Starting Lead Enrichment Agent for {len(domains)} domain(s)...[/bold cyan]")
    cost_tracker = CostTracker()

    async with PlaywrightFetcher(max_concurrency=concurrency) as fetcher:
        tasks = [
            process_domain(
                domain=d,
                fetcher=fetcher,
                cost_tracker=cost_tracker,
                model_override=model_override,
            )
            for d in domains
        ]
        results: List[CompanyIntelligence] = await asyncio.gather(*tasks)

    # ----------------------------------------------------------------------
    # Sink 1: JSON output
    # ----------------------------------------------------------------------
    output_json.parent.mkdir(parents=True, exist_ok=True)
    json_data = [res.model_dump(mode="json") for res in results]
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved JSON output to {output_json}")

    # ----------------------------------------------------------------------
    # Sink 2: CSV output (flattened for CRM / spreadsheet import)
    # ----------------------------------------------------------------------
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    flat_rows = []
    for r in results:
        emails_str = "; ".join(r.contact_emails)
        phones_str = "; ".join(r.phone_numbers)
        leaders_str = "; ".join(
            f"{m.name} ({m.title or 'N/A'}) - {m.linkedin_url or 'N/A'}"
            for m in r.key_leadership
        )
        flat_rows.append({
            "domain": r.domain,
            "company_overview": r.company_overview,
            "target_audience": r.target_audience,
            "contact_emails": emails_str,
            "phone_numbers": phones_str,
            "key_leadership": leaders_str,
            "technologies_detected": "; ".join(r.technologies_detected),
            "headquarters": r.headquarters or "N/A",
            "founding_year": r.founding_year or "N/A",
            "estimated_headcount": r.estimated_headcount or "N/A",
            "funding_stage": r.funding_stage or "N/A",
            "data_confidence_score": r.data_confidence_score,
            "extraction_status": r.extraction_status,
            "provider_used": r.provider_used,
            "pages_crawled_count": len(r.pages_crawled),
            "logo_url": r.logo_url or "",
            "screenshot_path": r.screenshot_path or "",
            "cold_email_hook": r.outreach_hooks.get("cold_email", ""),
            "linkedin_note": r.outreach_hooks.get("linkedin_note", ""),
            "errors": " | ".join(r.errors),
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "estimated_cost_usd": r.estimated_cost_usd,
        })
    df = pd.DataFrame(flat_rows)
    df.to_csv(output_csv, index=False, encoding="utf-8")
    logger.info(f"Saved CSV output to {output_csv}")

    # ----------------------------------------------------------------------
    # Sink 3: Cost report
    # ----------------------------------------------------------------------
    cost_tracker.save_report()

    # ----------------------------------------------------------------------
    # Display Rich Summary Table in Console
    # ----------------------------------------------------------------------
    table = Table(title="Lead Enrichment Results Summary", show_header=True, header_style="bold magenta")
    table.add_column("Domain", style="cyan", width=18)
    table.add_column("Status", style="bold", width=10)
    table.add_column("Provider", style="green", width=18)
    table.add_column("Confidence", justify="right", width=12)
    table.add_column("Emails", justify="center", width=8)
    table.add_column("Leaders", justify="center", width=8)
    table.add_column("Cost (USD)", justify="right", width=12)
    table.add_column("Overview", style="dim", width=40)

    for r in results:
        status_color = "green" if r.extraction_status == "success" else ("yellow" if r.extraction_status == "partial" else "red")
        overview_snippet = (r.company_overview[:37] + "...") if len(r.company_overview) > 40 else r.company_overview
        cost_str = f"${r.estimated_cost_usd:.5f}" if r.estimated_cost_usd is not None else "N/A"
        prov_str = r.provider_used or "None"

        table.add_row(
            r.domain,
            f"[{status_color}]{r.extraction_status}[/{status_color}]",
            prov_str,
            f"{r.data_confidence_score:.2f}",
            str(len(r.contact_emails)),
            str(len(r.key_leadership)),
            cost_str,
            overview_snippet,
        )

    console.print(table)
    console.print(f"[bold green]Enrichment complete! Artifacts written to {output_json} and {output_csv}[/bold green]")
    return results


def parse_args():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous Lead Enrichment Agent — Extracts structured company intelligence from websites."
    )
    parser.add_argument(
        "--domains", "-d",
        nargs="+",
        help="One or more company domains (e.g. --domains postman.com supabase.com vapi.ai)",
    )
    parser.add_argument(
        "--domains-file", "-f",
        type=Path,
        help="Path to a text file containing domains, one per line",
    )
    parser.add_argument(
        "--out", "-o",
        type=Path,
        default=settings.output_json,
        help=f"Path to output JSON file (default: {settings.output_json})",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=settings.output_csv,
        help=f"Path to output CSV file (default: {settings.output_csv})",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=settings.max_concurrency,
        help=f"Max concurrent pages/domains (default: {settings.max_concurrency})",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=settings.groq_model,
        help=f"Groq model override (default: {settings.groq_model})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    domains: List[str] = []

    if args.domains:
        domains.extend(args.domains)

    if args.domains_file:
        if args.domains_file.exists():
            lines = args.domains_file.read_text(encoding="utf-8").splitlines()
            for line in lines:
                clean = line.strip()
                if clean and not clean.startswith("#"):
                    domains.append(clean)
        else:
            console.print(f"[bold red]Error: Domains file {args.domains_file} does not exist.[/bold red]")
            sys.exit(1)

    if not domains:
        console.print("[bold yellow]No domains specified! Use --domains postman.com supabase.com or --domains-file domains.txt[/bold yellow]")
        sys.exit(1)

    asyncio.run(
        run_pipeline(
            domains=domains,
            output_json=args.out,
            output_csv=args.csv,
            concurrency=args.concurrency,
            model_override=args.model,
        )
    )


if __name__ == "__main__":
    main()
