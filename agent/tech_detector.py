"""Technology stack fingerprinting module.

Detects frontend frameworks, CMS, analytics, payments, authentication, and cloud
infrastructure by inspecting HTML markup, script tags, stylesheets, and headers.
"""

import re
from typing import List, Set, Optional

# Technology fingerprint definitions
TECH_SIGNATURES = {
    # Frontend Frameworks & Libraries
    "Next.js": [r"/_next/", r"__NEXT_DATA__", r"next/dist/client"],
    "React": [r"react(?:\.production|\.development)?\.js", r"__reactFiber", r"data-reactroot"],
    "Vue.js": [r"vue(?:\.runtime)?(?:\.esm)?\.js", r"data-v-[a-f0-9]", r"__NUXT__"],
    "Webflow": [r"webflow(?:\.[a-z0-9]+)?\.js", r"data-wf-page", r"w-nav"],
    "WordPress": [r"/wp-content/", r"/wp-includes/", r'<meta name="generator" content="WordPress'],
    "Shopify": [r"cdn\.shopify\.com", r"Shopify\.theme"],
    "Tailwind CSS": [r"tailwind(?:\.[a-z0-9]+)?\.css", r'class="[^"]*(?:flex|grid|hidden|bg-[a-z0-9]+|text-[a-z0-9]+|px-\d|py-\d)'],
    "Gatsby": [r"___gatsby", r"gatsby-image"],
    "Astro": [r"astro-island", r'<html[^>]*class="[^"]*astro-'],

    # Analytics & Telemetry
    "Google Analytics 4": [r"gtag\(['\"]config['\"],", r"googletagmanager\.com/gtag/js", r"google-analytics\.com/analytics\.js"],
    "Segment": [r"cdn\.segment\.com/analytics\.js", r"analytics\.load\("],
    "PostHog": [r"app\.posthog\.com", r"posthog\.init\("],
    "Mixpanel": [r"cdn\.mxpnl\.com", r"mixpanel\.init\("],
    "Hotjar": [r"static\.hotjar\.com", r"_hjSettings"],
    "Datadog RUM": [r"datadoghq-browser-rum"],

    # Payments & Billing
    "Stripe": [r"js\.stripe\.com/v3", r"stripe\.com/checkout", r"__stripe"],
    "Paddle": [r"cdn\.paddle\.com", r"Paddle\.Setup"],
    "Chargebee": [r"js\.chargebee\.com"],
    "PayPal": [r"paypal\.com/sdk/js"],

    # Authentication & Backend
    "Supabase": [r"supabase\.co", r"@supabase/supabase-js"],
    "Clerk": [r"clerk\.dev", r"clerk\.com", r"__clerk"],
    "Auth0": [r"cdn\.auth0\.com", r"auth0\.com/js"],
    "Firebase": [r"firebasejs/", r"firebaseio\.com"],

    # Hosting & Infrastructure
    "Vercel": [r"x-vercel-id", r"/_vercel/", r"vercel\.app"],
    "Cloudflare": [r"cloudflare\.com", r"cf-ray", r"cloudflare-static"],
    "AWS": [r"amazonaws\.com", r"cloudfront\.net", r"x-amz-"],

    # Customer Support & CRM
    "Intercom": [r"widget\.intercom\.io", r"Intercom\("],
    "HubSpot": [r"js\.hs-scripts\.com", r"hubspot\.com"],
    "Zendesk": [r"static\.zdassets\.com", r"zendesk\.com"],
}


def detect_technologies(html: str, headers: Optional[dict] = None) -> List[str]:
    """Detects technologies and tools from HTML content and HTTP headers.

    Returns a deduplicated, sorted list of detected technologies.
    """
    detected: Set[str] = set()
    if not html:
        return []

    combined_text = html
    if headers:
        header_str = " ".join(f"{k}: {v}" for k, v in headers.items())
        combined_text += " " + header_str

    for tech_name, patterns in TECH_SIGNATURES.items():
        for pat in patterns:
            if re.search(pat, combined_text, re.IGNORECASE):
                detected.add(tech_name)
                break

    # Implied dependencies (e.g. Next.js implies React)
    if "Next.js" in detected or "Gatsby" in detected:
        detected.add("React")

    return sorted(list(detected))
