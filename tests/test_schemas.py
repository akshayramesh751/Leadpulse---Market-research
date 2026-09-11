"""Unit tests for schemas and confidence score calculations."""

import pytest
from pydantic import ValidationError
from agent.schemas import TeamMember, RawExtraction, CompanyIntelligence
from agent.extractor import compute_heuristic_confidence, reconcile_confidence, extract_company_intelligence


def test_team_member_validation():
    m = TeamMember(name="Abhinav Asthana", title="CEO", linkedin_url="https://www.linkedin.com/in/abhinavasthana")
    assert m.name == "Abhinav Asthana"
    assert m.linkedin_url == "https://www.linkedin.com/in/abhinavasthana"

    # Non-LinkedIn URL gets cleaned to None
    m2 = TeamMember(name="John Doe", linkedin_url="https://twitter.com/johndoe")
    assert m2.linkedin_url is None


def test_confidence_score_bounds():
    # Valid score
    valid = CompanyIntelligence(
        domain="example.com",
        company_overview="Example company overview text exceeding minimum characters.",
        target_audience="Software developers",
        data_confidence_score=0.85,
    )
    assert valid.data_confidence_score == 0.85

    # Invalid scores (> 1.0 or < 0.0) should raise ValidationError
    with pytest.raises(ValidationError):
        CompanyIntelligence(
            domain="example.com",
            company_overview="Overview",
            target_audience="Devs",
            data_confidence_score=1.5,
        )

    with pytest.raises(ValidationError):
        CompanyIntelligence(
            domain="example.com",
            company_overview="Overview",
            target_audience="Devs",
            data_confidence_score=-0.1,
        )


def test_heuristic_confidence_calculation():
    # Fully populated raw extraction
    full_raw = RawExtraction(
        company_overview="Postman is the leading collaborative platform for API development, used by over 30 million developers.",
        target_audience="Developers, DevOps teams, API architects, and enterprise engineering organizations.",
        contact_emails=["sales@postman.com", "support@postman.com"],
        key_leadership=[
            TeamMember(name="Abhinav Asthana", title="CEO", linkedin_url="https://linkedin.com/in/abhinavasthana"),
            TeamMember(name="Ankit Sobti", title="CTO", linkedin_url="https://linkedin.com/in/ankitsobti"),
        ],
        model_confidence=0.9,
    )
    score = compute_heuristic_confidence(full_raw)
    # 0.25 (overview) + 0.25 (audience) + 0.20 (emails) + 0.20 (leadership) + 0.10 (linkedin) = 1.0
    assert score == 1.0

    # Partially populated (missing emails and linkedin)
    partial_raw = RawExtraction(
        company_overview="Postman is an API platform for developers.",
        target_audience="Software engineers",
        contact_emails=[],
        key_leadership=[TeamMember(name="Abhinav Asthana", title="CEO")],
        model_confidence=0.7,
    )
    score_partial = compute_heuristic_confidence(partial_raw)
    # 0.25 (overview) + 0.25 (audience) + 0 (emails) + 0.15 (1 leader) = 0.65
    assert score_partial == 0.65


def test_reconcile_confidence():
    # 60% heuristic (0.80) + 40% model (0.90) = 0.48 + 0.36 = 0.84
    reconciled = reconcile_confidence(0.80, 0.90)
    assert reconciled == 0.84

    # Out of bounds clamping check
    assert reconcile_confidence(1.5, 1.2) == 1.0
    assert reconcile_confidence(-0.5, -0.2) == 0.0


@pytest.mark.asyncio
async def test_extractor_resilience_empty_markdown():
    res = await extract_company_intelligence(
        domain="empty.com",
        markdown_content="",
        pages_crawled=[],
    )
    assert res.extraction_status == "failed"
    assert "Empty content" in res.errors[0]
    assert res.data_confidence_score == 0.0


@pytest.mark.asyncio
async def test_extractor_resilience_missing_api_key(monkeypatch):
    import agent.extractor as extractor_mod
    monkeypatch.setattr(extractor_mod.settings, "groq_api_key", None)

    res = await extract_company_intelligence(
        domain="test.com",
        markdown_content="Postman builds API tooling.",
        pages_crawled=["https://test.com"],
    )
    # If no key configured, returns partial without crashing
    assert res.extraction_status in ("partial", "failed")
    assert any("GROQ_API_KEY is not configured" in err for err in res.errors)


@pytest.mark.asyncio
async def test_extractor_groq_success(monkeypatch):
    import agent.extractor as extractor_mod
    from agent.schemas import RawExtraction, TeamMember

    monkeypatch.setattr(extractor_mod.settings, "groq_api_key", "fake_groq_key")

    class MockCompletion:
        class usage:
            prompt_tokens = 500
            completion_tokens = 80

    mock_raw = RawExtraction(
        company_overview="Postman is the leading API development platform.",
        target_audience="Developers and engineers.",
        contact_emails=["team@postman.com"],
        key_leadership=[TeamMember(name="Abhinav Asthana", title="CEO")],
        model_confidence=0.9,
    )

    async def mock_groq_success(*args, **kwargs):
        return mock_raw, MockCompletion()

    monkeypatch.setattr(extractor_mod, "_extract_with_groq", mock_groq_success)

    result = await extractor_mod.extract_company_intelligence(
        domain="postman.com",
        markdown_content="Postman is an API platform.",
        pages_crawled=["https://postman.com"],
    )

    assert result.extraction_status == "success"
    assert "groq" in result.provider_used
    assert result.company_overview == "Postman is the leading API development platform."
    assert result.data_confidence_score > 0.0
    assert result.prompt_tokens == 500
    assert result.completion_tokens == 80

