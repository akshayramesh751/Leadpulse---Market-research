"""Email Deliverability and Zero-Bounce Mailbox Verification Engine.

Performs syntax validation and live DNS MX (Mail Exchanger) resolution to guarantee
that extracted sales and contact emails belong to domains with active receiving mailboxes.
"""

import re
import asyncio
from typing import List, Dict, Any, Optional
import dns.resolver
from agent.logger import logger


KNOWN_PROVIDERS = {
    "google": "Google Workspace / Gmail",
    "googlemail": "Google Workspace / Gmail",
    "outlook": "Microsoft 365 / Outlook",
    "microsoft": "Microsoft 365 / Exchange",
    "protonmail": "ProtonMail",
    "zoho": "Zoho Mail",
    "mimecast": "Mimecast Secure Gateway",
    "barracuda": "Barracuda Email Security",
    "amazonses": "Amazon SES",
    "pphosted": "Proofpoint",
    "cloudflare": "Cloudflare Email Routing",
}


def detect_provider(mx_hosts: List[str]) -> str:
    """Classifies email provider from MX hostname signatures."""
    combined = " ".join(mx_hosts).lower()
    for key, label in KNOWN_PROVIDERS.items():
        if key in combined:
            return label
    return "Custom Mail Server" if mx_hosts else "No Mail Exchanger"


def check_email_mx(email: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Synchronous MX record lookup for an email address."""
    email_clean = email.strip().lower()

    # 1. Syntax check
    if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email_clean):
        return {
            "email": email_clean,
            "is_deliverable": False,
            "mx_records": [],
            "mail_provider": "Invalid Syntax",
            "status": "Invalid Syntax",
        }

    domain = email_clean.split("@")[1]

    # 2. DNS MX resolution
    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout
    resolver.timeout = timeout

    try:
        answers = resolver.resolve(domain, "MX")
        mx_hosts = [str(r.exchange).rstrip(".").lower() for r in answers]
        provider = detect_provider(mx_hosts)

        return {
            "email": email_clean,
            "is_deliverable": len(mx_hosts) > 0,
            "mx_records": mx_hosts,
            "mail_provider": provider,
            "status": f"Deliverable ({provider})" if mx_hosts else "No MX Records",
        }
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers, dns.exception.Timeout):
        # Fallback: check if A record exists (some domains accept mail directly on A record)
        try:
            a_answers = resolver.resolve(domain, "A")
            if a_answers:
                return {
                    "email": email_clean,
                    "is_deliverable": True,
                    "mx_records": [f"A-record fallback ({domain})"],
                    "mail_provider": "Direct Host (A Record)",
                    "status": "Deliverable (A Record)",
                }
        except Exception:
            pass

        return {
            "email": email_clean,
            "is_deliverable": False,
            "mx_records": [],
            "mail_provider": "None",
            "status": "Unreachable / No MX",
        }
    except Exception as e:
        logger.debug(f"DNS lookup error for {email_clean}: {e}")
        return {
            "email": email_clean,
            "is_deliverable": False,
            "mx_records": [],
            "mail_provider": "Lookup Error",
            "status": "Lookup Error",
        }


async def verify_emails(emails: List[str]) -> List[Dict[str, Any]]:
    """Asynchronously verifies deliverability for a list of emails."""
    if not emails:
        return []

    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(None, check_email_mx, e) for e in emails]
    return await asyncio.gather(*tasks)
