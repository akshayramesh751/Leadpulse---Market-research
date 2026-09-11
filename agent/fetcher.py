"""Fetch layer using async Playwright with resource blocking, concurrency pooling, and resilience."""

import asyncio
from dataclasses import dataclass
from typing import Optional, Sequence
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging
from config import settings
from agent.logger import logger

# Signatures that indicate anti-bot challenge or block
BOT_BLOCK_TITLE_SIGNATURES = [
    "attention required! | cloudflare",
    "just a moment...",
    "security check",
    "access denied",
    "ddos protection by cloudflare",
    "bot verification",
    "verify you are human",
]

BOT_BLOCK_BODY_SIGNATURES = [
    "cf-browser-verification",
    "cf-challenge-running",
    "challenge-form",
    "turnstile",
    "g-recaptcha",
    "hcaptcha-box",
]

BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


from dataclasses import dataclass, field
from typing import Optional, Sequence, Dict

@dataclass
class FetchResult:
    """Result of fetching a single web page."""
    url: str
    status_code: Optional[int] = None
    html: Optional[str] = None
    error: Optional[str] = None
    is_bot_blocked: bool = False
    headers: Dict[str, str] = field(default_factory=dict)
    screenshot_path: Optional[str] = None
    logo_url: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return bool(self.html and not self.error and not self.is_bot_blocked)


def is_bot_blocked(html: str, title: str, status_code: Optional[int]) -> bool:
    """Checks for Cloudflare or CAPTCHA bot-block signatures."""
    if status_code in (403, 429):
        return True

    title_lower = title.lower()
    if any(sig in title_lower for sig in BOT_BLOCK_TITLE_SIGNATURES):
        return True

    html_lower = html.lower()
    if any(sig in html_lower for sig in BOT_BLOCK_BODY_SIGNATURES):
        return True

    return False


class PlaywrightFetcher:
    """Async Playwright browser pool with semaphore-bounded concurrency,

    resource blocking, stealth headers, and tenacity retries.
    """

    def __init__(
        self,
        max_concurrency: Optional[int] = None,
        timeout_ms: Optional[int] = None,
    ):
        self.max_concurrency = max_concurrency or settings.max_concurrency
        self.timeout_ms = timeout_ms or settings.request_timeout_ms
        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def __aenter__(self) -> "PlaywrightFetcher":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Initializes the shared Playwright Chromium instance."""
        if not self._playwright:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            logger.info(f"Playwright Chromium launched (concurrency={self.max_concurrency})")

    async def close(self) -> None:
        """Closes browser and Playwright runtime cleanly."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Playwright browser closed")

    async def _create_context(self) -> BrowserContext:
        """Creates a browser context with realistic viewport and stealth headers."""
        if not self._browser:
            raise RuntimeError("Browser is not running. Did you enter the context?")

        context = await self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            java_script_enabled=True,
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        return context

    async def fetch_page(
        self,
        url: str,
        capture_screenshot: bool = False,
        domain_name: Optional[str] = None,
    ) -> FetchResult:
        """Fetches a single page with retries and concurrency control."""
        async with self.semaphore:
            return await self._fetch_page_internal(
                url,
                capture_screenshot=capture_screenshot,
                domain_name=domain_name,
            )

    async def _fetch_page_internal(
        self,
        url: str,
        capture_screenshot: bool = False,
        domain_name: Optional[str] = None,
    ) -> FetchResult:
        """Internal worker executing navigation, resource blocking, and checks."""
        context: Optional[BrowserContext] = None

        @retry(
            stop=stop_after_attempt(2),
            wait=wait_exponential(multiplier=1, min=1, max=3),
            retry=retry_if_exception_type((PlaywrightTimeoutError, PlaywrightError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _attempt_goto(page):
            if not capture_screenshot:
                # Scrape-only subpages: aggressively block images/fonts/media for maximum speed & bandwidth savings
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                    else route.continue_(),
                )
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                return response
            else:
                # Visual screenshot pages (homepage): allow CSS, fonts, and images so the preview renders cleanly!
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in {"media"}
                    else route.continue_(),
                )
                response = await page.goto(
                    url,
                    wait_until="load",
                    timeout=self.timeout_ms,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    pass
                await page.wait_for_timeout(1500)
                return response

        try:
            context = await self._create_context()
            page = await context.new_page()

            response = await _attempt_goto(page)
            status_code = response.status if response else 200
            title = await page.title()
            html = await page.content()
            headers = response.headers if response else {}

            blocked = is_bot_blocked(html, title, status_code)
            if blocked:
                logger.warning(f"Bot block/challenge detected at {url} (status={status_code}, title='{title}')")
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html=html,
                    error="Bot challenge/block detected",
                    is_bot_blocked=True,
                    headers=headers,
                )

            # Extract visual assets & screenshot if requested
            screenshot_path: Optional[str] = None
            logo_url: Optional[str] = None
            if capture_screenshot:
                from agent.visual_extractor import capture_homepage_screenshot, extract_brand_assets
                screenshot_path = await capture_homepage_screenshot(page, domain_name or "homepage")
                logo_url, _ = extract_brand_assets(html, url)

            logger.info(f"Fetched {url} (status={status_code}, length={len(html)} chars)")
            return FetchResult(
                url=url,
                status_code=status_code,
                html=html,
                error=None,
                is_bot_blocked=False,
                headers=headers,
                screenshot_path=screenshot_path,
                logo_url=logo_url,
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.warning(f"Failed to fetch {url} after retries: {error_msg}")
            return FetchResult(
                url=url,
                status_code=None,
                html=None,
                error=error_msg,
                is_bot_blocked=False,
            )
        finally:
            if context:
                await context.close()

    async def fetch_urls(
        self,
        urls: Sequence[str],
        domain: Optional[str] = None,
    ) -> list[FetchResult]:
        """Concurrently fetches multiple URLs, capturing screenshot for the primary homepage."""
        tasks = []
        for i, url in enumerate(urls):
            # Capture screenshot on first URL (homepage)
            should_capture = (i == 0)
            tasks.append(
                self.fetch_page(
                    url,
                    capture_screenshot=should_capture,
                    domain_name=domain,
                )
            )
        return await asyncio.gather(*tasks)
