"""Subpage discovery module for identifying high-signal company URLs.

Discovers relevant subpages (About, Team, Company, Contact, Pricing, Leadership)
using a sitemap/robots-first strategy with fallback to keyword-scored link crawling.
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional, Set
import httpx
from bs4 import BeautifulSoup
from config import settings
from agent.logger import logger

# High-value keyword targets for B2B company intelligence
KEYWORDS_SCORES = {
    "about": 10,
    "team": 10,
    "leadership": 10,
    "company": 9,
    "founders": 9,
    "people": 8,
    "executives": 8,
    "contact": 7,
    "pricing": 6,
    "story": 5,
    "careers": 3,
}

IGNORE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".mp4", ".mp3", ".css", ".js",
    ".xml", ".json", ".rss", ".atom"
}


def normalize_domain(domain: str) -> str:
    """Extracts a clean, normalized domain string without protocol or trailing slashes."""
    cleaned = domain.strip().lower()
    if cleaned.startswith("http://"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("https://"):
        cleaned = cleaned[8:]
    return cleaned.split("/")[0]


def is_valid_subpage(url: str, base_domain: str, disallowed_paths: Set[str]) -> bool:
    """Checks whether a URL belongs to the target domain, is HTTP(S), and is not ignored/disallowed."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        # Domain matching (e.g. www.postman.com matches postman.com)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        norm_base = base_domain.lower()
        if norm_base.startswith("www."):
            norm_base = norm_base[4:]

        if host != norm_base and not host.endswith("." + norm_base):
            return False

        # Ignore non-web assets
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in IGNORE_EXTENSIONS):
            return False

        # Check robots.txt disallowed paths
        for dis in disallowed_paths:
            if dis and path.startswith(dis):
                return False

        return True
    except Exception:
        return False


def score_url(url: str, anchor_text: str = "") -> int:
    """Computes a relevance score for a URL based on target keywords in URL path and anchor text."""
    parsed = urllib.parse.urlparse(url)
    text_to_check = f"{parsed.path.lower()} {parsed.query.lower()} {anchor_text.lower()}"
    
    score = 0
    for keyword, weight in KEYWORDS_SCORES.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", text_to_check) or f"/{keyword}" in parsed.path.lower():
            score += weight
    return score


def parse_robots_txt(robots_content: str) -> tuple[Set[str], Optional[str]]:
    """Parses robots.txt to extract disallowed paths for User-agent * and any Sitemap directives."""
    disallowed: Set[str] = set()
    sitemap_url: Optional[str] = None
    applies = False

    for line in robots_content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(":", 1)
        if len(parts) != 2:
            continue

        key = parts[0].strip().lower()
        val = parts[1].strip()

        if key == "user-agent":
            applies = (val == "*")
        elif key == "disallow" and applies and val:
            disallowed.add(val)
        elif key == "sitemap" and not sitemap_url:
            sitemap_url = val

    return disallowed, sitemap_url


def parse_sitemap_xml(xml_content: str) -> list[str]:
    """Parses sitemap.xml content and extracts all <loc> URL strings."""
    urls = []
    try:
        root = ET.fromstring(xml_content)
        # XML namespace handling
        for elem in root.iter():
            if elem.tag.endswith("loc") and elem.text:
                url = elem.text.strip()
                if url:
                    urls.append(url)
    except Exception as e:
        logger.debug(f"XML parse error on sitemap: {e}")
    return urls


def extract_links_from_html(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extracts all (href, anchor_text) links from HTML."""
    links = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            anchor_text = a_tag.get_text(separator=" ", strip=True)
            absolute_url = urllib.parse.urljoin(base_url, href)
            # Strip fragment
            clean_url = urllib.parse.urldefrag(absolute_url)[0]
            if clean_url:
                links.append((clean_url, anchor_text))
    except Exception as e:
        logger.debug(f"HTML link extraction error: {e}")
    return links


async def discover_subpages(
    domain: str,
    homepage_html: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
    max_pages: Optional[int] = None,
) -> list[str]:
    """Discovers high-signal subpages for a domain.

    Returns a prioritized list of URLs up to max_pages, always including
    the root homepage as the first entry.
    """
    limit = max_pages or settings.max_pages_per_domain
    norm_domain = normalize_domain(domain)
    base_url = f"https://{norm_domain}"
    results: list[str] = [base_url]
    disallowed_paths: Set[str] = set()

    own_client = False
    if client is None:
        client = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=10.0,
            follow_redirects=True,
        )
        own_client = True

    try:
        # 1. Inspect robots.txt
        custom_sitemap: Optional[str] = None
        try:
            robots_resp = await client.get(f"{base_url}/robots.txt")
            if robots_resp.status_code == 200:
                disallowed_paths, custom_sitemap = parse_robots_txt(robots_resp.text)
                logger.debug(f"[{domain}] robots.txt parsed: {len(disallowed_paths)} disallows, sitemap={custom_sitemap}")
        except Exception as e:
            logger.debug(f"[{domain}] Failed to fetch robots.txt: {e}")

        # 2. Try sitemap.xml
        sitemap_candidates = [custom_sitemap] if custom_sitemap else []
        sitemap_candidates.append(f"{base_url}/sitemap.xml")

        discovered_candidates: dict[str, int] = {}

        for s_url in sitemap_candidates:
            if not s_url:
                continue
            try:
                s_resp = await client.get(s_url)
                if s_resp.status_code == 200 and ("xml" in s_resp.headers.get("content-type", "") or s_resp.text.strip().startswith("<?xml") or "<urlset" in s_resp.text or "<sitemapindex" in s_resp.text):
                    s_urls = parse_sitemap_xml(s_resp.text)
                    for u in s_urls:
                        if is_valid_subpage(u, norm_domain, disallowed_paths):
                            score = score_url(u)
                            if score > 0:
                                discovered_candidates[u] = max(discovered_candidates.get(u, 0), score)
                    if discovered_candidates:
                        logger.info(f"[{domain}] Found {len(discovered_candidates)} relevant URLs in sitemap {s_url}")
                        break
            except Exception as e:
                logger.debug(f"[{domain}] Sitemap check failed for {s_url}: {e}")

        # 3. Fallback: Parse homepage links if sitemap didn't yield enough
        if len(discovered_candidates) < (limit - 1):
            html_to_parse = homepage_html
            if not html_to_parse:
                try:
                    hp_resp = await client.get(base_url)
                    if hp_resp.status_code == 200:
                        html_to_parse = hp_resp.text
                except Exception as e:
                    logger.debug(f"[{domain}] Homepage fetch for link extraction failed: {e}")

            if html_to_parse:
                page_links = extract_links_from_html(html_to_parse, base_url)
                for u, anchor in page_links:
                    if u != base_url and u != f"{base_url}/" and is_valid_subpage(u, norm_domain, disallowed_paths):
                        score = score_url(u, anchor)
                        if score > 0:
                            discovered_candidates[u] = max(discovered_candidates.get(u, 0), score)

        # 4. Rank candidates by score and select top (limit - 1)
        ranked = sorted(discovered_candidates.items(), key=lambda item: item[1], reverse=True)
        for u, _ in ranked:
            clean_u = u.rstrip("/")
            if clean_u not in [r.rstrip("/") for r in results]:
                results.append(u)
            if len(results) >= limit:
                break

    finally:
        if own_client:
            await client.aclose()

    logger.info(f"[{domain}] Discovered {len(results)} target pages: {results}")
    return results
