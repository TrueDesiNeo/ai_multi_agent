# =============================================================================
# File: llm_openai.py
# Description:
#     OpenAI-compatible client wrapper that drafts well-structured article
#     sections. Provides resilient retries via Tenacity and environment-driven
#     configuration (model name, base URL, temperature).
#
# Key Features:
#     - Configurable base_url and API key for OpenAI-compatible servers
#     - Exponential backoff retries for transient failures
#     - Helper to draft a section using topic, section title, style, sources,
#       and optional reviewer feedback
#
# Usage:
#     text = draft_section(
#         topic="Edge AI in Healthcare",
#         section="Benefits and Use Cases",
#         style="neutral, SEO-optimized, concise but informative",
#         sources=["WHO report 2024", "FDA SaMD guidance"],
#         feedback="Tighten the intro; add a concrete example."
#     )
#     print(text)
#
# Environment Variables:
#     - MODEL_URL 
#     - OPENAI_API_KEY
#     - WRITER_MODEL_NAME
#     - WRITER_MODEL_LLM_TEMPERATURE
#
# Dependencies:
#     - Python 3.10+
#     - openai (OpenAI-compatible client)
#     - tenacity
#     - logging_init: provides _env, _parse_float, logger
#
# Notes:
#     - Designed to work with OpenAI-compatible inference servers.
#     - Returns model text `.strip()`ed for cleaner downstream formatting.
# ================================================================

from openai import OpenAI
from typing import List, Optional
from tenacity import retry, wait_exponential, stop_after_attempt
from logging_init import _env, _parse_float, logger

# -----------------------------------------------------------------------------
# LLM Configuration
# -----------------------------------------------------------------------------
# Fetch configuration from environment variables with sensible defaults.
MODEL_URL = _env("MODEL_URL", "EMPTY")
MODEL_API_KEY = _env("OPENAI_API_KEY", "EMPTY")  # Default placeholder
WRITER_MODEL = _env("WRITER_MODEL_NAME", "llama-3-1-8b-instruct")
WRITER_MODEL_LLM_TEMPERATURE = _parse_float(
    _env("WRITER_MODEL_LLM_TEMPERATURE", "0.5"), 0.5
)

# Initialize OpenAI client
_client = OpenAI(
    base_url=MODEL_URL,
    api_key=MODEL_API_KEY)
logger.info(f"Connected to LLM at {MODEL_URL}")

# -----------------------------------------------------------------------------
# Completion Helper
# -----------------------------------------------------------------------------
@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
def _complete(system: str, user: str) -> str:
    """
    Send a chat completion request to the LLM with system and user messages.
    Retries on failure using exponential backoff.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    logger.info(f"Sending request to LLM model={WRITER_MODEL}")
    r = _client.chat.completions.create(
        model=WRITER_MODEL,
        temperature=WRITER_MODEL_LLM_TEMPERATURE,
        messages=messages,
    )
    logger.info(f"Received response from LLM")
    return r.choices[0].message.content.strip()

# -----------------------------------------------------------------------------
# Draft Section Generator
# -----------------------------------------------------------------------------
def draft_section(
    topic: str,
    section: str,
    style: str,
    sources: List[str],
    feedback: Optional[str],
) -> str:
    """
    Generate a well-structured draft for a given section of an article.
    
    Parameters:
        topic (str): The main article topic.
        section (str): The section title to draft.
        style (str): Writing style (e.g., SEO-friendly, concise).
        sources (List[str]): Optional list of sources for factual accuracy.
        feedback (Optional[str]): Reviewer feedback to incorporate.
    
    Returns:
        str: Drafted section content.
    """
    # System prompt defines the role and tone for the LLM
    system = (
        "You are a senior technical writer. Produce factual, well-structured content.\n"
        "Use short paragraphs, bullets when helpful, and a brief takeaway.\n"
        "US English. Avoid hype. Keep SEO-friendly headings."
    )

    # User prompt includes topic, section, style, and optional sources
    user = (
        f"Write the section '{section}' for the article on '{topic}'.\n"
        f"Style: {style}.\n"
        f"Sources (optional): {', '.join(sources[:5]) if sources else 'None'}.\n"
    )

    # If feedback is provided, include it in the prompt
    if feedback:
        user += f"\nIncorporate this reviewer feedback (keep changes concise):\n{feedback}\n"

    logger.info(f"Drafting section='{section}' for topic='{topic}' with style='{style}'")
    return _complete(system, user)