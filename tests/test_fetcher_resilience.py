"""Resilience and behavior tests for agent.fetcher module."""

import pytest
from agent.fetcher import is_bot_blocked, FetchResult, PlaywrightFetcher


def test_is_bot_blocked_detection():
    # HTTP status code blocks
    assert is_bot_blocked("<html>ok</html>", "Home", 403) is True
    assert is_bot_blocked("<html>ok</html>", "Home", 429) is True

    # Cloudflare / CAPTCHA title signatures
    assert is_bot_blocked("<html>...</html>", "Just a moment...", 200) is True
    assert is_bot_blocked("<html>...</html>", "Attention Required! | Cloudflare", 200) is True
    assert is_bot_blocked("<html>...</html>", "Access Denied", 200) is True

    # Body signatures
    assert is_bot_blocked("<html><div class='cf-browser-verification'></div></html>", "Verify", 200) is True
    assert is_bot_blocked("<html><div id='turnstile'></div></html>", "Verify", 200) is True

    # Clean normal page
    assert is_bot_blocked("<html><h1>About Us</h1><p>We build APIs</p></html>", "About Postman", 200) is False


def test_fetch_result_properties():
    success = FetchResult(url="https://example.com", status_code=200, html="<h1>Hello</h1>")
    assert success.is_success is True

    failure = FetchResult(url="https://example.com", error="TimeoutError")
    assert failure.is_success is False

    blocked = FetchResult(url="https://example.com", is_bot_blocked=True, html="<html>cf</html>")
    assert blocked.is_success is False


@pytest.mark.asyncio
async def test_fetcher_html_rendering():
    """Verify PlaywrightFetcher launches headless browser, renders page, and extracts content."""
    async with PlaywrightFetcher(max_concurrency=2, timeout_ms=5000) as fetcher:
        test_url = "data:text/html,<html><head><title>Test Page</title></head><body><h1>Playwright Rendered</h1></body></html>"
        result = await fetcher.fetch_page(test_url)
        assert result.is_success is True
        assert result.html is not None
        assert "Playwright Rendered" in result.html
        assert result.status_code == 200


@pytest.mark.asyncio
async def test_fetcher_unreachable_domain_resilience():
    """Verify fetcher returns FetchResult with error rather than crashing on unreachable host."""
    async with PlaywrightFetcher(max_concurrency=1, timeout_ms=2000) as fetcher:
        # Invalid loopback port that refuses connection
        result = await fetcher.fetch_page("http://127.0.0.1:59998/offline")
        assert result.is_success is False
        assert result.error is not None
        assert result.html is None
