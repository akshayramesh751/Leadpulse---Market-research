"""Fallback search module for finding missing leadership LinkedIn profiles via Tavily or SerpAPI."""

import re
from typing import List, Optional
import httpx
from config import settings
from agent.logger import logger
from agent.schemas import TeamMember


async def search_linkedin_tavily(name: str, company: str, api_key: str) -> Optional[str]:
    """Queries Tavily API for a person's LinkedIn profile."""
    query = f"{name} {company} LinkedIn"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "include_domains": ["linkedin.com/in/"],
        "max_results": 3,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    link = item.get("url", "")
                    if "linkedin.com/in/" in link:
                        return link
    except Exception as e:
        logger.debug(f"Tavily search failed for {name} ({company}): {e}")
    return None


async def search_linkedin_serpapi(name: str, company: str, api_key: str) -> Optional[str]:
    """Queries SerpAPI for a person's LinkedIn profile."""
    query = f"{name} {company} site:linkedin.com/in/"
    url = "https://serpapi.com/search.json"
    params = {
        "api_key": api_key,
        "engine": "google",
        "q": query,
        "num": 3,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("organic_results", []):
                    link = item.get("link", "")
                    if "linkedin.com/in/" in link:
                        return link
    except Exception as e:
        logger.debug(f"SerpAPI search failed for {name} ({company}): {e}")
    return None


async def enrich_leadership_linkedin(
    leadership: List[TeamMember],
    company_domain: str,
) -> List[TeamMember]:
    """Enriches leadership team members with LinkedIn URLs if missing and an API key is available."""
    tavily_key = settings.tavily_api_key
    serpapi_key = settings.serpapi_key

    if not tavily_key and not serpapi_key:
        logger.debug(f"[{company_domain}] Neither TAVILY_API_KEY nor SERPAPI_KEY configured; skipping LinkedIn search fallback")
        return leadership

    enriched_leadership = []
    company_name = company_domain.split(".")[0].capitalize()

    for member in leadership:
        if member.linkedin_url:
            enriched_leadership.append(member)
            continue

        linkedin_url: Optional[str] = None
        if tavily_key:
            linkedin_url = await search_linkedin_tavily(member.name, company_name, tavily_key)
        elif serpapi_key:
            linkedin_url = await search_linkedin_serpapi(member.name, company_name, serpapi_key)

        if linkedin_url:
            logger.info(f"[{company_domain}] Found LinkedIn for {member.name}: {linkedin_url}")
            enriched_leadership.append(
                TeamMember(
                    name=member.name,
                    title=member.title,
                    linkedin_url=linkedin_url,
                )
            )
        else:
            enriched_leadership.append(member)

    return enriched_leadership
