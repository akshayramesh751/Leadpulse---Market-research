"""AI Sales Outreach Generator using Groq.

Drafts personalized 3-sentence cold email hooks and concise LinkedIn connection notes
tailored to the prospect's ICP and leadership team.
"""

from typing import Optional, Dict
from pydantic import BaseModel, Field
from groq import AsyncGroq
import instructor

from config import settings
from agent.logger import logger
from agent.schemas import TeamMember


class OutreachHooks(BaseModel):
    """Generated personalized sales outreach copy."""
    cold_email: str = Field(..., description="Compelling 3-sentence personalized cold email hook addressing their specific value proposition and audience.")
    linkedin_note: str = Field(..., description="Personalized LinkedIn connection request note under 300 characters.")


async def generate_outreach_hooks(
    domain: str,
    overview: str,
    target_audience: str,
    executive: Optional[TeamMember] = None,
) -> Dict[str, str]:
    """Generates personalized cold email and LinkedIn message hooks using Groq."""
    groq_key = settings.groq_api_key
    if not groq_key or not overview:
        return {}

    exec_name = executive.name if executive else "the team"
    exec_title = f" ({executive.title})" if executive and executive.title else ""

    prompt = (
        f"COMPANY DOMAIN: {domain}\n"
        f"WHAT THEY DO: {overview}\n"
        f"WHO THEY SELL TO (ICP): {target_audience}\n"
        f"PROSPECT EXECUTIVE: {exec_name}{exec_title}\n\n"
        f"Task:\n"
        f"1. Write a 3-sentence high-converting B2B cold email hook that compliments their positioning and demonstrates understanding of their product.\n"
        f"2. Write a personalized, authentic LinkedIn connection request note (strictly under 300 characters) addressed to {exec_name}."
    )

    try:
        groq_client = AsyncGroq(api_key=groq_key)
        instructor_client = instructor.from_groq(groq_client, mode=instructor.Mode.TOOLS)

        result = await instructor_client.chat.completions.create(
            model=settings.groq_model,
            response_model=OutreachHooks,
            max_retries=2,
            messages=[
                {
                    "role": "system",
                    "content": "You are an elite B2B sales copywriter. Write punchy, non-spammy, hyper-personalized outreach based exclusively on factual company intelligence.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        logger.info(f"[{domain}] Generated personalized outreach hooks")
        return {
            "cold_email": result.cold_email,
            "linkedin_note": result.linkedin_note,
        }
    except Exception as e:
        logger.debug(f"[{domain}] Outreach hook generation error: {e}")
        return {}
