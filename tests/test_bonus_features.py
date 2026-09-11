"""Unit tests for bonus features: Cost Tracker and Search Fallback."""

import pytest
from pathlib import Path
from agent.cost_tracker import calculate_cost, CostTracker
from agent.search_fallback import enrich_leadership_linkedin
from agent.schemas import TeamMember


def test_calculate_cost():
    # 1M prompt tokens at $0.15 + 1M completion tokens at $0.60 = $0.75
    cost = calculate_cost(1_000_000, 1_000_000, model="openai/gpt-oss-120b")
    assert cost == 0.75

    # 10k prompt tokens + 1k completion tokens
    cost_small = calculate_cost(10_000, 1_000, model="openai/gpt-oss-120b")
    assert cost_small > 0.0
    assert cost_small < 0.01


def test_cost_tracker_lifecycle(tmp_path: Path):
    csv_file = tmp_path / "cost_test.csv"
    tracker = CostTracker(log_path=csv_file)

    cost1 = tracker.record_usage("postman.com", "openai/gpt-oss-120b", 2000, 400)
    assert cost1 > 0
    assert tracker.total_prompt_tokens == 2000
    assert tracker.total_completion_tokens == 400

    tracker.save_report()
    assert csv_file.exists()
    content = csv_file.read_text(encoding="utf-8")
    assert "postman.com" in content
    assert "openai/gpt-oss-120b" in content


@pytest.mark.asyncio
async def test_search_fallback_graceful_without_keys():
    # Without keys, it should leave existing leadership intact without errors
    team = [
        TeamMember(name="Abhinav Asthana", title="CEO", linkedin_url="https://linkedin.com/in/abhinavasthana"),
        TeamMember(name="Ankit Sobti", title="CTO", linkedin_url=None),
    ]
    enriched = await enrich_leadership_linkedin(team, "postman.com")
    assert len(enriched) == 2
    assert enriched[0].name == "Abhinav Asthana"
    assert enriched[0].linkedin_url == "https://linkedin.com/in/abhinavasthana"
    assert enriched[1].name == "Ankit Sobti"
