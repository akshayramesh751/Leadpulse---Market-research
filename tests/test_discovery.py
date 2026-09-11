"""Unit tests for agent.discovery module."""

import pytest
from agent.discovery import (
    normalize_domain,
    score_url,
    parse_robots_txt,
    parse_sitemap_xml,
    extract_links_from_html,
    is_valid_subpage,
    discover_subpages,
)


def test_normalize_domain():
    assert normalize_domain("https://postman.com/") == "postman.com"
    assert normalize_domain("http://supabase.com/docs") == "supabase.com"
    assert normalize_domain("  vapi.ai  ") == "vapi.ai"
    assert normalize_domain("sub.example.com") == "sub.example.com"


def test_score_url():
    assert score_url("https://postman.com/company/about-us") > 0
    assert score_url("https://postman.com/team") > 0
    assert score_url("https://postman.com/pricing") > 0
    assert score_url("https://postman.com/random-blog-post-123") == 0
    assert score_url("https://postman.com/page", anchor_text="Our Leadership Team") > 0


def test_parse_robots_txt():
    robots = """
    User-agent: Googlebot
    Disallow: /private

    User-agent: *
    Disallow: /admin
    Disallow: /internal/
    Sitemap: https://example.com/custom-sitemap.xml
    """
    disallowed, sitemap = parse_robots_txt(robots)
    assert "/admin" in disallowed
    assert "/internal/" in disallowed
    assert sitemap == "https://example.com/custom-sitemap.xml"


def test_parse_sitemap_xml():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.com/</loc>
      </url>
      <url>
        <loc>https://example.com/about</loc>
      </url>
      <url>
        <loc>https://example.com/team</loc>
      </url>
    </urlset>
    """
    urls = parse_sitemap_xml(xml)
    assert urls == [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/team",
    ]


def test_is_valid_subpage():
    base = "example.com"
    disallowed = {"/admin"}
    assert is_valid_subpage("https://example.com/about", base, disallowed) is True
    assert is_valid_subpage("https://www.example.com/about", base, disallowed) is True
    assert is_valid_subpage("https://otherdomain.com/about", base, disallowed) is False
    assert is_valid_subpage("https://example.com/admin/settings", base, disallowed) is False
    assert is_valid_subpage("https://example.com/logo.png", base, disallowed) is False


def test_extract_links_from_html():
    html = """
    <html>
      <body>
        <a href="/about-us">About Us</a>
        <a href="https://example.com/pricing">Pricing Plans</a>
        <a href="/team#leadership">Leadership</a>
        <a href="https://twitter.com/example">Twitter</a>
      </body>
    </html>
    """
    links = extract_links_from_html(html, "https://example.com")
    urls = [u for u, _ in links]
    assert "https://example.com/about-us" in urls
    assert "https://example.com/pricing" in urls
    assert "https://example.com/team" in urls


@pytest.mark.asyncio
async def test_discover_subpages_with_homepage_html():
    html = """
    <html>
      <body>
        <a href="/company/about">About</a>
        <a href="/leadership">Leadership</a>
        <a href="/pricing">Pricing</a>
        <a href="/contact-sales">Contact</a>
        <a href="/careers">Careers</a>
        <a href="/blog/random-post">Random</a>
      </body>
    </html>
    """
    # Test discover_subpages using provided HTML without real network
    pages = await discover_subpages(
        domain="example.com",
        homepage_html=html,
        max_pages=4,
    )
    assert len(pages) <= 4
    assert pages[0] == "https://example.com"
    # Should have selected high-scoring links
    assert any("about" in p or "leadership" in p or "contact" in p for p in pages)
