"""Content cleaning and token optimization layer.

Converts raw HTML into clean, semantic Markdown using Trafilatura
with Readability-lxml fallback, collapses boilerplate, and enforces
token budgets via tiktoken.
"""

import re
from typing import Optional, Sequence
import tiktoken
import trafilatura
from readability import Document
from markdownify import markdownify as md
from config import settings
from agent.logger import logger

# Universal BPE tokenizer for token counting and budgeting
try:
    TOKENIZER = tiktoken.get_encoding("cl100k_base")
except Exception:
    TOKENIZER = None


def count_tokens(text: str) -> int:
    """Counts tokens using tiktoken (cl100k_base) or whitespace approximation."""
    if not text:
        return 0
    if TOKENIZER:
        return len(TOKENIZER.encode(text, disallowed_special=()))
    # Fallback approximation: 1 token ~ 4 characters
    return len(text) // 4


def truncate_tokens(text: str, max_tokens: int) -> str:
    """Truncates text to fit within max_tokens."""
    if not text or max_tokens <= 0:
        return ""
    if TOKENIZER:
        tokens = TOKENIZER.encode(text, disallowed_special=())
        if len(tokens) <= max_tokens:
            return text
        truncated = TOKENIZER.decode(tokens[:max_tokens])
        return truncated + "\n\n... [Content truncated due to token budget]"
    else:
        char_limit = max_tokens * 4
        if len(text) <= char_limit:
            return text
        return text[:char_limit] + "\n\n... [Content truncated due to token budget]"


def post_process_markdown(text: str) -> str:
    """Cleans up markdown text: normalizes mailto, removes redundant spaces and blank lines."""
    if not text:
        return ""

    # Replace [email](mailto:user@domain.com) with user@domain.com
    cleaned = re.sub(r"\[.*?\]\(mailto:([^\s\)]+)\)", r"\1", text)
    cleaned = re.sub(r"mailto:([^\s\)\"\'>]+)", r"\1", cleaned)

    # Collapse lines with only whitespace
    lines = [line.strip() for line in cleaned.splitlines()]
    collapsed = "\n".join(lines)

    # Collapse 3 or more consecutive newlines into 2
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)

    return collapsed.strip()


def extract_contact_info_from_html(html: str) -> dict[str, list[str]]:
    """Extracts verified public emails and phone numbers directly from HTML anchors and text."""
    if not html:
        return {"emails": [], "phones": []}

    emails: set[str] = set()
    phones: set[str] = set()

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # 1. Inspect mailto: and tel: links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                clean_e = href.split("?")[0].replace("mailto:", "").strip()
                if "@" in clean_e and "." in clean_e.split("@")[1]:
                    emails.add(clean_e.lower())
            elif href.lower().startswith("tel:"):
                clean_p = href.replace("tel:", "").strip()
                p_digits = re.sub(r"[^\d+]", "", clean_p)
                if len(p_digits) >= 7:
                    phones.add(clean_p)

        # 2. Extract from raw page text
        text = soup.get_text(" ", strip=True)

        # Email regex
        raw_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
        for e in raw_emails:
            e_lower = e.lower().strip(".")
            if not any(e_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".js", ".css"]):
                if not any(junk in e_lower for junk in ["sentry.io", "w3.org", "schema.org", "example.com"]):
                    emails.add(e_lower)

        # Phone regex (international & domestic patterns with formatting)
        raw_phones = re.findall(
            r'(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?)?\d{3,5}[\s.-]?\d{3,5}',
            text
        )
        for p in raw_phones:
            p_strip = p.strip()
            digits = re.sub(r"[^\d]", "", p_strip)
            if 8 <= len(digits) <= 15:
                if p_strip.startswith("+") or " " in p_strip or "-" in p_strip or "(" in p_strip:
                    if not p_strip.isdigit():
                        phones.add(p_strip)

    except Exception as e:
        logger.debug(f"Contact extraction error: {e}")

    # Deduplicate phones by digit sequence, preferring formatted strings (e.g. "+91 93807 38490" over "+919380738490")
    deduped_phones = {}
    for p in sorted(phones, key=lambda x: (len(x), " " in x or "-" in x), reverse=True):
        d_key = re.sub(r"[^\d]", "", p)
        if d_key and d_key not in deduped_phones:
            deduped_phones[d_key] = p

    return {
        "emails": sorted(list(emails)),
        "phones": sorted(list(deduped_phones.values())),
    }


def clean_html(html: str, url: str = "") -> str:
    """Converts HTML to clean Markdown text.

    Uses Trafilatura as primary extractor (stripping nav, footer, scripts, CSS),
    with readability-lxml + markdownify as fallback for SPAs or irregular layouts.
    Guarantees that footer contact info (emails, phones) is never discarded.
    """
    if not html or not html.strip():
        return ""

    raw_len = len(html)
    cleaned_md: Optional[str] = None

    # 1. Primary: Trafilatura
    try:
        cleaned_md = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_comments=False,
            include_formatting=True,
            favor_recall=True,
        )
    except Exception as e:
        logger.debug(f"Trafilatura extraction failed on {url}: {e}")

    # 2. Fallback: Readability-lxml + markdownify
    if not cleaned_md or len(cleaned_md.strip()) < 50:
        logger.debug(f"Falling back to readability-lxml for {url}")
        try:
            doc = Document(html)
            summary_html = doc.summary()
            cleaned_md = md(
                summary_html,
                heading_style="ATX",
                strip=["script", "style", "nav", "footer", "iframe", "noscript"],
            )
        except Exception as e:
            logger.debug(f"Readability fallback failed on {url}: {e}")
            cleaned_md = ""

    # 3. Post-process
    final_text = post_process_markdown(cleaned_md or "")

    # Prepend HTML title if available and not already prominent at the start
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        page_title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        if page_title and page_title.lower() not in final_text[:200].lower():
            final_text = f"# {page_title}\n\n{final_text}".strip()

    # 4. Guarantee footer & contact info preservation
    contact_data = extract_contact_info_from_html(html)
    extra_contact_md = []
    if contact_data["emails"]:
        extra_contact_md.append(f"**Emails:** {', '.join(contact_data['emails'])}")
    if contact_data["phones"]:
        extra_contact_md.append(f"**Phone Numbers:** {', '.join(contact_data['phones'])}")

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        footer_el = soup.find("footer") or soup.find(class_=re.compile(r"footer", re.I))
        if footer_el:
            footer_txt = footer_el.get_text(" ", strip=True)
            if footer_txt and len(footer_txt) < 800 and footer_txt[:40].lower() not in final_text.lower():
                extra_contact_md.append(f"**Footer & Location Notes:** {footer_txt}")
    except Exception:
        pass

    if extra_contact_md:
        final_text += "\n\n## Verified Contact & Footer Information\n" + "\n".join(f"- {item}" for item in extra_contact_md)

    clean_len = len(final_text)
    reduction = ((raw_len - clean_len) / raw_len * 100) if raw_len > 0 else 0
    logger.info(
        f"Cleaned {url or 'page'}: raw={raw_len} chars -> clean={clean_len} chars "
        f"({reduction:.1f}% reduction, ~{count_tokens(final_text)} tokens)"
    )

    return final_text


def prioritize_page(url: str) -> int:
    """Returns sorting priority (lower is higher priority) for token budgeting."""
    u = url.lower()
    # Homepage gets highest priority
    if u.endswith("/") or u.count("/") <= 3:
        return 0
    # Core company info
    if any(k in u for k in ("about", "team", "leadership", "company", "founders", "executives")):
        return 1
    # Pricing & Contact
    if any(k in u for k in ("pricing", "contact")):
        return 2
    return 3


def build_domain_context(
    pages: Sequence[tuple[str, str]],
    max_tokens: Optional[int] = None,
) -> tuple[str, dict]:
    """Combines cleaned text from multiple pages into a budgeted domain context for the LLM.

    Args:
        pages: list of (url, raw_html) tuples.
        max_tokens: token limit for combined output (defaults to settings.max_tokens_per_domain).

    Returns:
        (combined_markdown, stats_dict)
    """
    limit = max_tokens or settings.max_tokens_per_domain
    raw_chars_total = 0
    clean_chars_total = 0

    # Sort pages by priority
    sorted_pages = sorted(pages, key=lambda p: prioritize_page(p[0]))

    cleaned_sections: list[tuple[str, str, int]] = []

    for url, html in sorted_pages:
        raw_chars_total += len(html)
        cleaned = clean_html(html, url=url)
        if cleaned:
            clean_chars_total += len(cleaned)
            sec_tokens = count_tokens(cleaned)
            cleaned_sections.append((url, cleaned, sec_tokens))

    # Assemble sections within token budget
    combined_parts = []
    used_tokens = 0
    included_urls = []

    for url, text, sec_tokens in cleaned_sections:
        header = f"## Source: {url}\n\n"
        header_tokens = count_tokens(header)

        available = limit - used_tokens - header_tokens
        if available <= 100:
            # Budget exhausted
            break

        if sec_tokens > available:
            # Partially include up to budget
            budgeted_text = truncate_tokens(text, available)
            combined_parts.append(header + budgeted_text)
            used_tokens += count_tokens(header + budgeted_text)
            included_urls.append(url)
            break
        else:
            combined_parts.append(header + text)
            used_tokens += header_tokens + sec_tokens
            included_urls.append(url)

    combined_markdown = "\n\n---\n\n".join(combined_parts)
    compression = ((raw_chars_total - clean_chars_total) / raw_chars_total * 100) if raw_chars_total > 0 else 0

    stats = {
        "raw_chars_total": raw_chars_total,
        "clean_chars_total": clean_chars_total,
        "compression_ratio_pct": round(compression, 1),
        "token_count": count_tokens(combined_markdown),
        "pages_included": included_urls,
    }

    logger.info(
        f"Domain context compiled: {len(included_urls)}/{len(pages)} pages included, "
        f"{stats['token_count']} tokens (raw={raw_chars_total} chars, clean={clean_chars_total} chars, "
        f"compression={stats['compression_ratio_pct']}%)"
    )

    return combined_markdown, stats
