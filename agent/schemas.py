"""Pydantic data models for structured company intelligence extraction."""

from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr, confloat, field_validator


class TeamMember(BaseModel):
    """Represents an executive or key team member."""
    name: str = Field(..., description="Full name of the executive or team member")
    title: Optional[str] = Field(None, description="Job title or role (e.g. CEO, CTO, Co-Founder)")
    linkedin_url: Optional[str] = Field(None, description="Personal or professional LinkedIn profile URL")

    @field_validator("linkedin_url", mode="before")
    @classmethod
    def clean_linkedin_url(cls, v):
        if not v or not isinstance(v, str):
            return None
        v = v.strip()
        if "linkedin.com" in v:
            return v
        return None


class RawExtraction(BaseModel):
    """Intermediate model for LLM structured output via Instructor."""
    company_overview: str = Field(
        ...,
        description="2-sentence summary of what the company does and its core offering",
    )
    target_audience: str = Field(
        ...,
        description="Who the product is built for (Ideal Customer Profile / ICP)",
    )
    contact_emails: List[str] = Field(
        default_factory=list,
        description="Public contact or sales emails found in the text. Do NOT hallucinate.",
    )
    phone_numbers: List[str] = Field(
        default_factory=list,
        description="Public contact or customer support phone numbers found in the text.",
    )
    key_leadership: List[TeamMember] = Field(
        default_factory=list,
        description="Identified founders, C-level executives, and key leadership team members",
    )
    model_confidence: confloat(ge=0.0, le=1.0) = Field(
        ...,
        description="Model self-reported confidence (0.0 to 1.0) on the completeness and accuracy of extraction based on the provided text",
    )


class CompanyIntelligence(BaseModel):
    """Final validated company intelligence record for sinks and exports."""
    domain: str = Field(..., description="Target company root domain")
    company_overview: str = Field(..., description="2-sentence summary of what the company does")
    target_audience: str = Field(..., description="Who the product is built for (ICP)")
    contact_emails: List[str] = Field(default_factory=list, description="Public contact emails")
    phone_numbers: List[str] = Field(default_factory=list, description="Public contact phone numbers")
    key_leadership: List[TeamMember] = Field(default_factory=list, description="Key leadership team")
    data_confidence_score: confloat(ge=0.0, le=1.0) = Field(
        ...,
        description="Reconciled confidence score (weighted average: 60% heuristic + 40% model self-assessment)",
    )
    pages_crawled: List[str] = Field(default_factory=list, description="List of URLs crawled for this domain")
    extraction_status: str = Field(
        default="success",
        description="Status: 'success', 'partial', or 'failed'",
    )
    errors: List[str] = Field(default_factory=list, description="List of warnings or failure messages")
    provider_used: Optional[str] = Field(default=None, description="LLM provider used: 'gemini' or 'groq (fallback)'")

    # Advanced Enterprise Intelligence Fields
    technologies_detected: List[str] = Field(default_factory=list, description="Tech stack and tools detected on the domain")
    logo_url: Optional[str] = Field(default=None, description="High-resolution logo or favicon URL")
    screenshot_path: Optional[str] = Field(default=None, description="Local path to homepage screenshot preview")
    headquarters: Optional[str] = Field(default=None, description="Company headquarters location (City, Country)")
    founding_year: Optional[int] = Field(default=None, description="Year the company was founded")
    estimated_headcount: Optional[str] = Field(default=None, description="Estimated number of employees (e.g. '50-200')")
    funding_stage: Optional[str] = Field(default=None, description="Latest funding round or capital raised")
    outreach_hooks: dict[str, str] = Field(default_factory=dict, description="Generated cold email and LinkedIn message hooks")

    prompt_tokens: Optional[int] = Field(default=None, description="Tokens in the extraction prompt")
    completion_tokens: Optional[int] = Field(default=None, description="Tokens in the model completion")
    estimated_cost_usd: Optional[float] = Field(default=None, description="Calculated API cost in USD")
    verified_emails: List[dict] = Field(default_factory=list, description="Zero-bounce deliverability audit results with DNS MX records")
