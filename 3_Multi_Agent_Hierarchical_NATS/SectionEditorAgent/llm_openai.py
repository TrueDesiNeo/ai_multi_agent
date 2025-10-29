# =============================================================================
# File: section_editor_llm.py
# Description:
#     OpenAI-compatible client wrapper that generates SEO-friendly article
#     sections from a given topic. Provides resilient retries via Tenacity
#     and environment-driven configuration (model name, base URL, temperature).
#
# Key Features:
#     - Configurable base_url and API key for OpenAI-compatible servers
#     - Exponential backoff retries for transient failures
#     - Simple helper to break a topic into strong, SEO-friendly sections
#
# Usage:
#     sections = break_into_sections("Edge AI in Healthcare", max_sections=6)
#     for s in sections:
#         print(s)
#
# Environment Variables:
#     - MODEL_URL 
#     - OPENAI_API_KEY 
#     - SECTION_EDITOR_MODEL_NAME 
#     - SECTION_EDITOR_MODEL_LLM_TEMPERATURE 
#
# Dependencies:
#     - Python 3.10+
#     - openai (OpenAI-compatible client)
#     - tenacity
#     - logging_init: provides _env, _parse_float, logger
#
# Notes:
#     - Designed to work with OpenAI-compatible inference servers.
#     - Returns up to `max_sections` sanitized lines from the model output.
#
# =============================================================================

from openai import OpenAI
from typing import List
from tenacity import retry, wait_exponential, stop_after_attempt
from logging_init import _env, _parse_float, logger

# -----------------------------------------------------------------------------
# LLM Configuration
# -----------------------------------------------------------------------------
MODEL_URL = _env("MODEL_URL","EMPTY")
MODEL_API_KEY = _env("OPENAI_API_KEY", "EMPTY") 
SECTION_EDITOR_MODEL = _env("SECTION_EDITOR_MODEL_NAME", "llama-3-1-8b-instruct")
SECTION_EDITOR_MODEL_LLM_TEMPERATURE = _parse_float(
    _env("SECTION_EDITOR_MODEL_LLM_TEMPERATURE", "0.4"), 0.4
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

    logger.info(f"Sending request to LLM model={SECTION_EDITOR_MODEL}")
    r = _client.chat.completions.create(
        model=SECTION_EDITOR_MODEL,
        temperature=SECTION_EDITOR_MODEL_LLM_TEMPERATURE,
        messages=messages,
    )
    logger.info(f"Received response from LLM")
    return r.choices[0].message.content.strip()

# -----------------------------------------------------------------------------
# Section Generator
# -----------------------------------------------------------------------------
def break_into_sections(topic: str, max_sections: int = 6) -> List[str]:
    """
    Break a topic into multiple SEO-friendly sections using LLM.
    """
    system = "You are a Section Editor who outlines an article into clear, SEO-friendly sections."
    user = f"Topic: {topic}\nGenerate <= {max_sections} strong sections. One per line. No numbering."

    logger.info(f"Requesting sections for topic={topic}, max_sections={max_sections}")
    text = _complete(system, user)
    sections = [s.strip("-• ").strip() for s in text.splitlines() if s.strip()]
    logger.info(f"Generated {len(sections)} sections for topic={topic}")
    return sections[:max_sections]