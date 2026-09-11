"""Firmographic and funding enrichment module via Tavily / SerpAPI search and Groq parsing."""

import json
from typing import Optional, Tuple
import httpx
from pydantic import BaseModel, Field
from groq import AsyncGroq
import instructor

from config import settings
from agent.logger import logger


class FirmographicData(BaseModel):
    """Structured firmographic data extracted from external search results."""
    headquarters: Optional[str] = Field(None, description="City, State/Country of company headquarters (e.g. 'San Francisco, USA')")
    founding_year: Optional[int] = Field(None, description="Year the company was founded (e.g. 2014)")
    estimated_headcount: Optional[str] = Field(None, description="Estimated employee headcount range (e.g. '100-250' or '500+')")
    funding_stage: Optional[str] = Field(None, description="Latest funding round or status (e.g. 'Series C', 'Public', 'Bootstrapped')")


async def search_firmographics_tavily(domain: str, api_key: str) -> str:
    """Queries Tavily API scoped specifically to the target domain."""
    query = f'"{domain}" company headquarters location founded employees funding'
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": 4,
    }
    snippets = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    snippets.append(item.get("content", ""))
    except Exception as e:
        logger.debug(f"Tavily firmographics search error for {domain}: {e}")
    return "\n\n".join(snippets)


async def search_firmographics_serpapi(domain: str, api_key: str) -> str:
    """Queries SerpAPI scoped specifically to the target domain."""
    query = f'"{domain}" company headquarters location founded employees'
    url = "https://serpapi.com/search.json"
    params = {
        "api_key": api_key,
        "engine": "google",
        "q": query,
        "num": 4,
    }
    snippets = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("organic_results", []):
                    snippets.append(item.get("snippet", ""))
    except Exception as e:
        logger.debug(f"SerpAPI firmographics search error for {domain}: {e}")
    return "\n\n".join(snippets)


async def enrich_firmographics(domain: str, website_text: str = "") -> FirmographicData:
    """Extracts firmographics using website text as primary ground truth, supplemented by domain-scoped search."""
    tavily_key = settings.tavily_api_key
    serpapi_key = settings.serpapi_key
    groq_key = settings.groq_api_key

    if not groq_key:
        return FirmographicData()

    search_text = ""
    if tavily_key:
        search_text = await search_firmographics_tavily(domain, tavily_key)
    elif serpapi_key:
        search_text = await search_firmographics_serpapi(domain, serpapi_key)

    # If neither search text nor website text exists, return empty
    if not search_text.strip() and not website_text.strip():
        return FirmographicData()

    try:
        groq_client = AsyncGroq(api_key=groq_key)
        instructor_client = instructor.from_groq(groq_client, mode=instructor.Mode.TOOLS)

        prompt = (
            f"TARGET COMPANY DOMAIN: {domain}\n\n"
            f"WEBSITE CONTENT (PRIMARY GROUND TRUTH):\n{website_text[:3500]}\n\n"
            f"EXTERNAL SEARCH RESULTS FOR '{domain}':\n{search_text[:2500]}\n\n"
            f"CRITICAL EXTRACTION RULES:\n"
            f"1. You are extracting firmographics ONLY for the exact company, academy, or business at '{domain}'.\n"
            f"2. Inspect the website content carefully for physical locations, city, state, country. If an explicit street address is not given, infer the country/state from phone calling codes (e.g. '+91' indicates India) and regional exam/service context (e.g. 'KCET' indicates Karnataka, India).\n"
            f"3. STRICT ANTI-COLLISION RULE: Never confuse '{domain}' with famous or foreign corporations that happen to share a similar prefix in other countries. If '{domain}' is a local school/academy, agency, or independent SaaS, do NOT attribute details from a foreign enterprise.\n"
            f"4. If no institutional VC funding round (e.g. Seed, Series A-D, IPO) is verified for THIS EXACT domain, output 'Self-funded / Private' or null. Never hallucinate venture capital rounds.\n"
            f"5. If founding year or employee headcount is not explicitly stated or verifiable, return null."
        )

        data = await instructor_client.chat.completions.create(
            model=settings.groq_model,
            response_model=FirmographicData,
            max_retries=2,
            messages=[
                {"role": "system", "content": "Extract verified company firmographics accurately without hallucinating foreign entities."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        logger.info(f"[{domain}] Firmographics enriched: HQ={data.headquarters}, Founded={data.founding_year}, Team={data.estimated_headcount}, Funding={data.funding_stage}")
        return data
    except Exception as e:
        logger.debug(f"[{domain}] Firmographics extraction error: {e}")
        return FirmographicData()
