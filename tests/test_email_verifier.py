"""Unit tests for the Zero-Bounce Email Deliverability Verifier."""

import pytest
from agent.email_verifier import check_email_mx, detect_provider


def test_detect_provider():
    assert detect_provider(["aspmx.l.google.com"]) == "Google Workspace / Gmail"
    assert detect_provider(["mail.protection.outlook.com"]) == "Microsoft 365 / Outlook"
    assert detect_provider(["mail.protonmail.ch"]) == "ProtonMail"
    assert detect_provider(["custom.myserver.com"]) == "Custom Mail Server"
    assert detect_provider([]) == "No Mail Exchanger"


def test_check_email_mx_valid_domain():
    # Google.com always has active MX records
    res = check_email_mx("test@google.com")
    assert res["is_deliverable"] is True
    assert len(res["mx_records"]) > 0
    assert "Google" in res["mail_provider"]


def test_check_email_mx_invalid_syntax():
    res = check_email_mx("invalid-email-no-at")
    assert res["is_deliverable"] is False
    assert res["status"] == "Invalid Syntax"


def test_check_email_mx_nonexistent_domain():
    res = check_email_mx("contact@this-is-a-definitely-fake-domain-987654321.org")
    assert res["is_deliverable"] is False
    assert "Unreachable" in res["status"] or "Lookup Error" in res["status"]
