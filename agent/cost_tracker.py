"""Cost tracking module for Groq LLM token usage and estimated expenditures."""

import csv
from pathlib import Path
from typing import Optional
from datetime import datetime
from config import settings
from agent.logger import logger

# Published Groq pricing rates per 1M tokens (USD)
# Source: groq.com/pricing
MODEL_PRICING_PER_1M = {
    # Rates: (prompt_rate, completion_rate) per 1M tokens
    # Google Gemini Models
    "gemini-2.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    # Groq Models
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "mixtral-8x7b-32768": (0.24, 0.24),
}

DEFAULT_RATE = (0.15, 0.60)


def calculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "openai/gpt-oss-120b",
) -> float:
    """Calculates estimated cost in USD for a given token usage."""
    rates = MODEL_PRICING_PER_1M.get(model, DEFAULT_RATE)
    prompt_cost = (prompt_tokens / 1_000_000) * rates[0]
    completion_cost = (completion_tokens / 1_000_000) * rates[1]
    return round(prompt_cost + completion_cost, 6)


class CostTracker:
    """Tracks token consumption and expenditures per domain and logs to CSV."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or settings.cost_report_csv
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_usd = 0.0
        self.records = []

    def record_usage(
        self,
        domain: str,
        model: str,
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
    ) -> float:
        """Records token usage for a domain and returns estimated cost."""
        p_tok = prompt_tokens or 0
        c_tok = completion_tokens or 0
        cost = calculate_cost(p_tok, c_tok, model)

        self.total_prompt_tokens += p_tok
        self.total_completion_tokens += c_tok
        self.total_cost_usd = round(self.total_cost_usd + cost, 6)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "domain": domain,
            "model": model,
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": p_tok + c_tok,
            "estimated_cost_usd": cost,
        }
        self.records.append(entry)
        logger.info(
            f"[{domain}] Tokens: prompt={p_tok}, completion={c_tok}, cost=${cost:.6f} USD"
        )
        return cost

    def save_report(self) -> None:
        """Flushes recorded token usage entries to CSV."""
        if not self.records:
            return

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = self.log_path.exists()

        fieldnames = [
            "timestamp", "domain", "model", "prompt_tokens",
            "completion_tokens", "total_tokens", "estimated_cost_usd"
        ]

        try:
            with open(self.log_path, mode="a" if file_exists else "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                for rec in self.records:
                    writer.writerow(rec)
            logger.info(f"Cost report saved to {self.log_path}")
        except Exception as e:
            logger.warning(f"Failed to write cost report: {e}")
