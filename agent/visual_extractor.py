"""Visual asset extraction: homepage hero screenshot and brand logo/favicon resolution."""

import re
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from playwright.async_api import Page
from agent.logger import logger


def extract_brand_assets(html: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts high-resolution logo URL and favicon URL from HTML."""
    if not html:
        return None, None

    favicon_url: Optional[str] = None
    logo_url: Optional[str] = None

    try:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Favicon lookup
        icon_link = (
            soup.find("link", rel=lambda r: r and "icon" in r.lower())
            or soup.find("link", rel=lambda r: r and "apple-touch-icon" in r.lower())
        )
        if icon_link and icon_link.get("href"):
            favicon_url = urllib.parse.urljoin(base_url, icon_link["href"])

        # Default fallback favicon
        if not favicon_url:
            parsed = urllib.parse.urlparse(base_url)
            favicon_url = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

        # 2. OpenGraph Brand Image
        og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og_image and og_image.get("content"):
            logo_url = urllib.parse.urljoin(base_url, og_image["content"])

        # 3. Logo tag fallback
        if not logo_url:
            logo_img = soup.find("img", alt=re.compile(r"logo", re.I)) or soup.find("img", src=re.compile(r"logo", re.I))
            if logo_img and logo_img.get("src"):
                logo_url = urllib.parse.urljoin(base_url, logo_img["src"])

    except Exception as e:
        logger.debug(f"Brand asset extraction error for {base_url}: {e}")

    return logo_url, favicon_url


async def capture_homepage_screenshot(
    page: Page,
    domain: str,
    output_dir: Path = Path("outputs/screenshots"),
) -> Optional[str]:
    """Captures a clean desktop viewport screenshot of the target domain homepage."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = output_dir / f"{domain.replace('.', '_')}.png"

        # Viewport screenshot
        await page.screenshot(
            path=str(screenshot_path),
            full_page=False,
            timeout=5000,
        )
        logger.info(f"[{domain}] Captured homepage screenshot to {screenshot_path}")
        return str(screenshot_path)
    except Exception as e:
        logger.debug(f"[{domain}] Screenshot capture failed: {e}")
        return None
