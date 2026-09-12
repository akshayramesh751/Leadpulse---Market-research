"""Automated Statistical Evaluation Harness for LeadPulse Intelligence Pipeline.

Computes Precision, Recall, F1-Scores, Exact & Keyword Matches, and Hallucination Rates
against a curated Golden Ground-Truth Benchmark Dataset.
"""

import os
import re
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Callable
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from agent.logger import logger
from agent.schemas import CompanyIntelligence
from agent.fetcher import PlaywrightFetcher
from agent.cost_tracker import CostTracker
import main

console = Console()
BENCHMARK_FILE = Path("benchmarks/golden_dataset.json")
EVAL_REPORT_FILE = Path("outputs/eval_report.json")


class FieldMetrics(BaseModel):
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 1.0
    recall: float = 1.0
    f1_score: float = 1.0


class DomainEvaluation(BaseModel):
    domain: str
    company_name: str
    category: str
    emails_metrics: FieldMetrics
    phones_metrics: FieldMetrics
    leadership_metrics: FieldMetrics
    hq_matched: bool
    funding_matched: bool
    tech_metrics: FieldMetrics
    hallucination_detected: bool
    latency_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
    predicted_emails: List[str] = []
    predicted_phones: List[str] = []
    predicted_leaders: List[str] = []
    predicted_hq: Optional[str] = None
    predicted_funding: Optional[str] = None


class BenchmarkReport(BaseModel):
    timestamp: str
    total_domains_evaluated: int
    macro_precision: float
    macro_recall: float
    macro_f1: float
    firmographic_accuracy: float
    hallucination_rate: float
    average_latency_seconds: float
    total_cost_usd: float
    domain_evaluations: List[DomainEvaluation]


def normalize_string(s: str) -> str:
    """Standardizes string for fuzzy set comparison (lowercased, alphanumeric only)."""
    return re.sub(r"[^a-zA-Z0-9]", "", s.lower().strip())


def normalize_phone(p: str) -> str:
    """Extracts pure digits from telephone numbers for evaluation matching."""
    return re.sub(r"[^\d]", "", p)


def compute_set_metrics(
    predicted: List[str],
    ground_truth: List[str],
    normalize_fn: Optional[Callable[[str], str]] = None,
) -> FieldMetrics:
    """Calculates True Positives, False Positives, False Negatives, Precision, Recall, and F1.

    Edge-case Handling:
    - If ground truth is empty and predicted is empty: P=1.0, R=1.0, F1=1.0 (True Negative agreement).
    - If ground truth is empty and predicted is non-empty: P=0.0, R=1.0, F1=0.0 (Spurious extraction).
    - If ground truth is non-empty and predicted is empty: P=0.0, R=0.0, F1=0.0 (Total miss).
    """
    fn_norm = normalize_fn if normalize_fn is not None else (lambda x: x.lower().strip())

    pred_set: Set[str] = {fn_norm(x) for x in predicted if x and fn_norm(x)}
    gt_set: Set[str] = {fn_norm(x) for x in ground_truth if x and fn_norm(x)}

    if not gt_set and not pred_set:
        return FieldMetrics(tp=0, fp=0, fn=0, precision=1.0, recall=1.0, f1_score=1.0)
    if not gt_set and pred_set:
        return FieldMetrics(tp=0, fp=len(pred_set), fn=0, precision=0.0, recall=1.0, f1_score=0.0)
    if gt_set and not pred_set:
        return FieldMetrics(tp=0, fp=0, fn=len(gt_set), precision=0.0, recall=0.0, f1_score=0.0)

    # Fuzzy/Subset matching to handle slight name differences (e.g. "Paul Copplestone" in "Paul Copplestone (CEO)")
    tp = 0
    matched_gt = set()
    matched_pred = set()

    for p in pred_set:
        for g in gt_set:
            if g not in matched_gt and (p == g or p in g or g in p):
                tp += 1
                matched_gt.add(g)
                matched_pred.add(p)
                break

    fp = len(pred_set) - len(matched_pred)
    fn = len(gt_set) - len(matched_gt)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return FieldMetrics(
        tp=tp,
        fp=fp,
        fn=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
    )


def compute_keyword_match(predicted: Optional[str], keywords: List[str]) -> bool:
    """Returns True if the predicted string contains any of the target ground truth keywords."""
    if not predicted or not keywords:
        return False
    pred_clean = predicted.lower()
    return any(kw.lower() in pred_clean for kw in keywords)


async def evaluate_single_domain(
    benchmark_record: Dict[str, Any],
    fetcher: PlaywrightFetcher,
    cost_tracker: CostTracker,
) -> DomainEvaluation:
    """Runs pipeline on target domain and compares predictions against ground truth."""
    import time
    domain = benchmark_record["domain"]
    gt = benchmark_record.get("ground_truth", {})

    t0 = time.time()
    intel: CompanyIntelligence = await main.process_domain(domain, fetcher, cost_tracker)
    latency = round(time.time() - t0, 2)

    pred_emails = intel.contact_emails
    pred_phones = getattr(intel, "phone_numbers", [])
    pred_leaders = [m.name for m in intel.key_leadership]
    pred_hq = getattr(intel, "headquarters", None)
    pred_funding = getattr(intel, "funding_stage", None)
    pred_techs = getattr(intel, "technologies_detected", [])

    emails_m = compute_set_metrics(pred_emails, gt.get("contact_emails", []))
    phones_m = compute_set_metrics(pred_phones, gt.get("phone_numbers", []), normalize_fn=normalize_phone)
    leaders_m = compute_set_metrics(pred_leaders, gt.get("key_leadership", []), normalize_fn=normalize_string)
    tech_m = compute_set_metrics(pred_techs, gt.get("technologies_keywords", []))

    hq_match = compute_keyword_match(pred_hq, gt.get("headquarters_keywords", []))
    funding_match = compute_keyword_match(pred_funding, gt.get("funding_stage_keywords", []))

    # Hallucination test: did model predict a funding round like Series B for an SMB that has no funding?
    hallucination = False
    if "Private" in gt.get("funding_stage_keywords", []) or "Self-funded" in gt.get("funding_stage_keywords", []):
        if pred_funding and any(round_str in pred_funding for round_str in ["Series A", "Series B", "Series C", "$"]):
            hallucination = True

    return DomainEvaluation(
        domain=domain,
        company_name=benchmark_record.get("company_name", domain),
        category=benchmark_record.get("category", "General"),
        emails_metrics=emails_m,
        phones_metrics=phones_m,
        leadership_metrics=leaders_m,
        hq_matched=hq_match,
        funding_matched=funding_match,
        tech_metrics=tech_m,
        hallucination_detected=hallucination,
        latency_seconds=latency,
        estimated_cost_usd=intel.estimated_cost_usd or 0.0,
        predicted_emails=pred_emails,
        predicted_phones=pred_phones,
        predicted_leaders=pred_leaders,
        predicted_hq=pred_hq,
        predicted_funding=pred_funding,
    )


async def run_benchmark_suite(
    benchmark_file: Path = BENCHMARK_FILE,
    domains_filter: Optional[List[str]] = None,
) -> BenchmarkReport:
    """Executes the full evaluation suite across benchmark targets and compiles summary statistics."""
    from datetime import datetime

    if not benchmark_file.exists():
        raise FileNotFoundError(f"Benchmark file not found at {benchmark_file}")

    with open(benchmark_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    if domains_filter:
        records = [r for r in records if r["domain"] in domains_filter]

    evaluations: List[DomainEvaluation] = []
    cost_tracker = CostTracker()

    logger.info(f"Starting LeadPulse Benchmark Evaluation across {len(records)} targets...")

    async with PlaywrightFetcher() as fetcher:
        for rec in records:
            logger.info(f"Evaluating benchmark target: {rec['domain']} ({rec.get('company_name', '')})")
            eval_res = await evaluate_single_domain(rec, fetcher, cost_tracker)
            evaluations.append(eval_res)

    # Compute Macro-Averages
    all_precisions = []
    all_recalls = []
    all_f1s = []

    for ev in evaluations:
        # Average entity metrics (emails, phones, leadership)
        entity_f1s = [ev.emails_metrics.f1_score, ev.phones_metrics.f1_score, ev.leadership_metrics.f1_score]
        entity_prec = [ev.emails_metrics.precision, ev.phones_metrics.precision, ev.leadership_metrics.precision]
        entity_rec = [ev.emails_metrics.recall, ev.phones_metrics.recall, ev.leadership_metrics.recall]

        all_precisions.append(sum(entity_prec) / len(entity_prec))
        all_recalls.append(sum(entity_rec) / len(entity_rec))
        all_f1s.append(sum(entity_f1s) / len(entity_f1s))

    macro_p = round(sum(all_precisions) / len(all_precisions), 4) if all_precisions else 0.0
    macro_r = round(sum(all_recalls) / len(all_recalls), 4) if all_recalls else 0.0
    macro_f1 = round(sum(all_f1s) / len(all_f1s), 4) if all_f1s else 0.0

    hq_matches = sum(1 for e in evaluations if e.hq_matched)
    funding_matches = sum(1 for e in evaluations if e.funding_matched)
    firmo_acc = round((hq_matches + funding_matches) / (len(evaluations) * 2), 4) if evaluations else 0.0

    hallucinations = sum(1 for e in evaluations if e.hallucination_detected)
    hallucination_rate = round(hallucinations / len(evaluations), 4) if evaluations else 0.0

    avg_lat = round(sum(e.latency_seconds for e in evaluations) / len(evaluations), 2) if evaluations else 0.0
    tot_cost = round(sum(e.estimated_cost_usd for e in evaluations), 6)

    report = BenchmarkReport(
        timestamp=datetime.now().isoformat(),
        total_domains_evaluated=len(evaluations),
        macro_precision=macro_p,
        macro_recall=macro_r,
        macro_f1=macro_f1,
        firmographic_accuracy=firmo_acc,
        hallucination_rate=hallucination_rate,
        average_latency_seconds=avg_lat,
        total_cost_usd=tot_cost,
        domain_evaluations=evaluations,
    )

    # Save to disk
    EVAL_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    logger.info(f"Evaluation report written to {EVAL_REPORT_FILE}")
    return report


def print_evaluation_summary(report: BenchmarkReport) -> None:
    """Renders formatted evaluation tables in the terminal using Rich."""
    console.print("\n[bold cyan]====================================================================[/bold cyan]")
    console.print("[bold yellow]LeadPulse Autonomous Agent - Statistical Benchmark Report[/bold yellow]")
    console.print("[bold cyan]====================================================================[/bold cyan]\n")

    summary_table = Table(title="Overall Benchmark Macro Metrics", header_style="bold magenta")
    summary_table.add_column("Macro Precision", justify="center")
    summary_table.add_column("Macro Recall", justify="center")
    summary_table.add_column("Macro F1-Score", justify="center")
    summary_table.add_column("Firmographic Accuracy", justify="center")
    summary_table.add_column("Hallucination Rate", justify="center")
    summary_table.add_column("Avg Latency", justify="center")
    summary_table.add_column("Total Cost", justify="center")

    summary_table.add_row(
        f"[green]{report.macro_precision * 100:.1f}%[/green]",
        f"[green]{report.macro_recall * 100:.1f}%[/green]",
        f"[bold green]{report.macro_f1 * 100:.1f}%[/bold green]",
        f"[cyan]{report.firmographic_accuracy * 100:.1f}%[/cyan]",
        f"[bold green]{report.hallucination_rate * 100:.1f}%[/bold green]" if report.hallucination_rate == 0 else f"[red]{report.hallucination_rate * 100:.1f}%[/red]",
        f"{report.average_latency_seconds:.1f}s",
        f"${report.total_cost_usd:.5f} USD",
    )
    console.print(summary_table)

    domain_table = Table(title="Domain-Level Extraction Performance", header_style="bold blue")
    domain_table.add_column("Domain", style="cyan")
    domain_table.add_column("Category", style="dim")
    domain_table.add_column("Emails (P/R/F1)")
    domain_table.add_column("Phones (P/R/F1)")
    domain_table.add_column("Leaders (P/R/F1)")
    domain_table.add_column("HQ Match", justify="center")
    domain_table.add_column("Funding Match", justify="center")
    domain_table.add_column("Cost (USD)", justify="right")

    for ev in report.domain_evaluations:
        em_str = f"{int(ev.emails_metrics.precision*100)}% / {int(ev.emails_metrics.recall*100)}% / {int(ev.emails_metrics.f1_score*100)}%"
        ph_str = f"{int(ev.phones_metrics.precision*100)}% / {int(ev.phones_metrics.recall*100)}% / {int(ev.phones_metrics.f1_score*100)}%"
        ld_str = f"{int(ev.leadership_metrics.precision*100)}% / {int(ev.leadership_metrics.recall*100)}% / {int(ev.leadership_metrics.f1_score*100)}%"
        hq_str = "[green]YES[/green]" if ev.hq_matched else "[red]NO[/red]"
        fd_str = "[green]YES[/green]" if ev.funding_matched else "[red]NO[/red]"

        domain_table.add_row(
            ev.domain,
            ev.category,
            em_str,
            ph_str,
            ld_str,
            hq_str,
            fd_str,
            f"${ev.estimated_cost_usd:.5f}",
        )
    console.print(domain_table)
    console.print(f"[dim]Report saved to: {EVAL_REPORT_FILE.resolve()}[/dim]\n")


if __name__ == "__main__":
    report = asyncio.run(run_benchmark_suite())
    print_evaluation_summary(report)
