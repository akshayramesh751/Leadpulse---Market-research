"""Unit tests for advanced platform features: Tech Detection, Brand Assets, and Outreach."""

import pytest
from agent.tech_detector import detect_technologies
from agent.visual_extractor import extract_brand_assets
from agent.firmographics import FirmographicData
from agent.outreach_generator import OutreachHooks


def test_detect_technologies_frameworks_and_tools():
    html = """
    <html>
      <head>
        <script src="/_next/static/chunks/main.js"></script>
        <script src="https://js.stripe.com/v3"></script>
        <script src="https://cdn.segment.com/analytics.js/v1/xyz/analytics.min.js"></script>
        <link rel="stylesheet" href="/tailwind.css">
      </head>
      <body>
        <div id="__next">
          <h1>Welcome</h1>
          <script src="https://widget.intercom.io/widget/abc"></script>
        </div>
      </body>
    </html>
    """
    detected = detect_technologies(html, headers={"server": "Vercel", "x-vercel-id": "iad1::123"})
    assert "Next.js" in detected
    assert "React" in detected  # Next.js implies React
    assert "Stripe" in detected
    assert "Segment" in detected
    assert "Intercom" in detected
    assert "Tailwind CSS" in detected
    assert "Vercel" in detected


def test_detect_technologies_empty():
    assert detect_technologies("") == []


def test_extract_brand_assets():
    html = """
    <html>
      <head>
        <link rel="icon" href="/assets/favicon-32x32.png">
        <meta property="og:image" content="https://example.com/images/og-banner.png">
      </head>
      <body>
        <header>
          <img src="/img/brand-logo.svg" alt="Company Logo" class="logo">
        </header>
      </body>
    </html>
    """
    logo, favicon = extract_brand_assets(html, "https://example.com")
    assert favicon == "https://example.com/assets/favicon-32x32.png"
    assert logo == "https://example.com/images/og-banner.png"


def test_firmographic_data_model():
    data = FirmographicData(
        headquarters="San Francisco, CA",
        founding_year=2014,
        estimated_headcount="500-1000",
        funding_stage="Series D",
    )
    assert data.founding_year == 2014
    assert data.funding_stage == "Series D"


def test_outreach_hooks_model():
    hooks = OutreachHooks(
        cold_email="Great product! Noticed you solve API testing for 30M developers. Let's connect.",
        linkedin_note="Hi Abhinav, love what you are building at Postman.",
    )
    assert "Postman" in hooks.linkedin_note
    assert len(hooks.linkedin_note) < 300
