"""LLM extraction layer using Instructor and Groq with dual confidence scoring and self-repair."""

import re
import logging
from typing import Optional, List, Tuple
from groq import AsyncGroq, RateLimitError as GroqRateLimitError, APIConnectionError as GroqConnectionError
import instructor
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config import settings
from agent.logger import logger
from agent.schemas import RawExtraction, CompanyIntelligence, TeamMember

SYSTEM_PROMPT = """You are a rigorous, highly accurate B2B company intelligence extraction agent.
Your mission is to read web page markdown from a target company domain and extract structured intelligence.

CRITICAL EXTRACTION RULES:
1. Extract only verifiable facts directly supported by the source markdown.
2. NEVER hallucinate, invent, or guess email addresses, phone numbers, or LinkedIn profile URLs. If an email, phone number, or LinkedIn URL is not explicitly printed in the text, return an empty list or null.
3. company_overview: Write exactly a 2-sentence summary explaining what the company/organization does and what core problem or need it addresses.
4. target_audience: Clearly specify who the product or service is built for (Ideal Customer Profile / ICP - e.g. software developers, high school students preparing for competitive exams, enterprise sales teams).
5. contact_emails: Extract public contact or sales emails found in the text.
6. phone_numbers: Extract public phone numbers found in the text.
7. key_leadership: Extract founders, executive leaders (CEO, CTO, Directors, Principals) or key instructors/creators mentioned in the text. Include their title and LinkedIn URL only if present in the text.
8. model_confidence: Score yourself between 0.0 and 1.0 reflecting how complete, unambiguous, and authoritative the source text was.
"""


def compute_heuristic_confidence(raw: RawExtraction) -> float:
    """Computes a deterministic heuristic score (0.0 to 1.0) based on non-null field completeness."""
    score = 0.0

    # Company overview completeness
    if raw.company_overview and len(raw.company_overview.strip()) >= 30:
        score += 0.25

    # Target audience completeness
    if raw.target_audience and len(raw.target_audience.strip()) >= 15:
        score += 0.25

    # Contact emails or phone numbers found
    if raw.contact_emails:
        valid_emails = [e for e in raw.contact_emails if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e)]
        if valid_emails:
            score += 0.20
    elif raw.phone_numbers:
        score += 0.15

    # Key leadership found
    if raw.key_leadership:
        if len(raw.key_leadership) >= 2:
            score += 0.20
        elif len(raw.key_leadership) == 1:
            score += 0.15

        # Bonus if leadership has LinkedIn or titles
        has_linkedin = any(m.linkedin_url for m in raw.key_leadership)
        if has_linkedin:
            score += 0.10

    return min(round(score, 2), 1.0)


def reconcile_confidence(heuristic_score: float, model_confidence: float) -> float:
    """Computes final reconciled confidence score: 60% heuristic + 40% model self-assessment."""
    blended = (0.60 * heuristic_score) + (0.40 * model_confidence)
    clamped = max(0.0, min(1.0, blended))
    return round(clamped, 2)


import asyncio

# Global throttle semaphore to avoid simultaneous burst token limit on Groq free/dev tiers
_LLM_SEMAPHORE = asyncio.Semaphore(1)


def _is_retryable_groq_error(exc: BaseException) -> bool:
    """Checks if error is a rate limit or transient network error."""
    err_str = str(exc).lower()
    if "429" in err_str or "rate limit" in err_str or "rate_limit" in err_str:
        return True
    return isinstance(exc, (GroqRateLimitError, GroqConnectionError))


async def _extract_with_groq(
    domain: str,
    user_prompt: str,
    api_key: str,
    model: str,
) -> Tuple[RawExtraction, any]:
    """Executes structured extraction using Groq LPU inference via Instructor."""
    groq_client = AsyncGroq(api_key=api_key)
    instructor_client = instructor.from_groq(groq_client, mode=instructor.Mode.TOOLS)

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=6, min=8, max=35),
        retry=_is_retryable_groq_error,
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call():
        # Check if rate limit indicates a required wait time
        return await instructor_client.chat.completions.create_with_completion(
            model=model,
            response_model=RawExtraction,
            max_retries=2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

    async with _LLM_SEMAPHORE:
        res = await _call()
        # Brief 1s polite buffer between consecutive LLM calls
        await asyncio.sleep(1)
        return res


async def extract_company_intelligence(
    domain: str,
    markdown_content: str,
    pages_crawled: List[str],
    override_model: Optional[str] = None,
) -> CompanyIntelligence:
    """Extracts structured company intelligence from cleaned website markdown using Groq."""
    errors: List[str] = []

    # Guard 1: Empty text check
    if not markdown_content or not markdown_content.strip():
        logger.warning(f"[{domain}] No content available for LLM extraction")
        return CompanyIntelligence(
            domain=domain,
            company_overview="No content extracted from target domain.",
            target_audience="Unknown",
            contact_emails=[],
            key_leadership=[],
            data_confidence_score=0.0,
            pages_crawled=pages_crawled,
            extraction_status="failed",
            errors=["Empty content received from web crawl"],
        )

    groq_key = settings.groq_api_key
    groq_model = override_model or settings.groq_model

    # Guard 2: Missing API key
    if not groq_key:
        msg = "GROQ_API_KEY is not configured in .env"
        logger.warning(f"[{domain}] {msg}")
        return CompanyIntelligence(
            domain=domain,
            company_overview="Extraction skipped: GROQ_API_KEY is not set.",
            target_audience="Unknown",
            contact_emails=[],
            key_leadership=[],
            data_confidence_score=0.0,
            pages_crawled=pages_crawled,
            extraction_status="partial",
            errors=[msg],
        )

    user_prompt = (
        f"TARGET COMPANY DOMAIN: {domain}\n\n"
        f"WEBSITE CONTENT:\n"
        f"{markdown_content}\n\n"
        f"Extract the company intelligence according to the schema."
    )

    try:
        logger.info(f"[{domain}] Calling Groq LLM ({groq_model}) for structured extraction...")
        raw_extraction, completion_metadata = await _extract_with_groq(
            domain=domain,
            user_prompt=user_prompt,
            api_key=groq_key,
            model=groq_model,
        )

        prompt_tokens = getattr(completion_metadata.usage, "prompt_tokens", None) if hasattr(completion_metadata, "usage") else None
        completion_tokens = getattr(completion_metadata.usage, "completion_tokens", None) if hasattr(completion_metadata, "usage") else None

        heuristic = compute_heuristic_confidence(raw_extraction)
        reconciled = reconcile_confidence(heuristic, raw_extraction.model_confidence)

        logger.info(
            f"[{domain}] Groq extraction succeeded. Confidence: reconciled={reconciled} "
            f"(heuristic={heuristic}, model={raw_extraction.model_confidence})"
        )

        return CompanyIntelligence(
            domain=domain,
            company_overview=raw_extraction.company_overview,
            target_audience=raw_extraction.target_audience,
            contact_emails=raw_extraction.contact_emails,
            phone_numbers=raw_extraction.phone_numbers,
            key_leadership=raw_extraction.key_leadership,
            data_confidence_score=reconciled,
            pages_crawled=pages_crawled,
            extraction_status="success",
            errors=errors,
            provider_used=f"groq ({groq_model})",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    except Exception as e:
        err_msg = f"Groq extraction failed: {type(e).__name__}: {str(e)}"
        logger.error(f"[{domain}] {err_msg}")
        errors.append(err_msg)
        return CompanyIntelligence(
            domain=domain,
            company_overview="Extraction failed due to an error during Groq model inference.",
            target_audience="Unknown",
            contact_emails=[],
            phone_numbers=[],
            key_leadership=[],
            data_confidence_score=0.0,
            pages_crawled=pages_crawled,
            extraction_status="failed",
            errors=errors,
        )
