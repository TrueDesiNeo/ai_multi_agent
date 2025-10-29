# =============================================================================
# File: llm_openai.py
# Description:
#     Thin wrapper around an OpenAI-compatible chat completion endpoint to
#     generate SEO-friendly topic ideas. Includes resilient retry logic via
#     Tenacity and environment-driven configuration for model, base URL,
#     and temperature.
#
# Key Features:
#     - OpenAI-compatible client with configurable base_url and API key
#     - Exponential backoff retries for transient failures
#     - Simple helper to produce trending topics for a given area
#
# Usage:
#     topics = list_topics("Edge AI", max_topics=7)
#     for t in topics:
#         print(t)
#
# Configuration (env vars):
#     - MODEL_URL 
#     - OPENAI_API_KEY 
#     - CHIEF_EDITOR_MODEL_NAME (default: llama-3-1-8b-instruct)
#     - CHIEF_EDITOR_MODEL_LLM_TEMPERATURE (default: 0.4)
#
# Dependencies:
#     - Python 3.10+
#     - openai (OpenAI-compatible client)
#     - tenacity
#     - logging_init: provides _env, _parse_float, logger
#
# Notes:
#     - Designed to work with OpenAI-compatible inference servers.
#     - Returns at most `max_topics` sanitized lines from the model output.
#
# =============================================================================

from openai import OpenAI
from tenacity import retry, wait_exponential, stop_after_attempt
from logging_init import _env, _parse_float, logger

# -----------------------------------------------------------------------------
# LLM Configuration
# -----------------------------------------------------------------------------
MODEL_URL = _env(
    "MODEL_URL",
    "EMPTY")
MODEL_API_KEY = _env(
    "OPENAI_API_KEY",
    "EMPTY") 
CHIEF_EDITOR_MODEL = _env(
    "CHIEF_EDITOR_MODEL_NAME",
    "llama-3-1-8b-instruct")
CHIEF_EDITOR_MODEL_LLM_TEMPERATURE = _parse_float(
    _env(
        "CHIEF_EDITOR_MODEL_LLM_TEMPERATURE", 
        "0.4"),
    0.4)

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

    logger.info(f"Sending request to LLM model={CHIEF_EDITOR_MODEL}")
    r = _client.chat.completions.create(
        model=CHIEF_EDITOR_MODEL,
        temperature=CHIEF_EDITOR_MODEL_LLM_TEMPERATURE,
        messages=messages,
    )
    logger.info(f"Received response from LLM - {r}")
    return r.choices[0].message.content.strip()

# -----------------------------------------------------------------------------
# Topic Generator
# -----------------------------------------------------------------------------
def list_topics(area: str, max_topics: int = 5):
    """
    Generate a list of trending, SEO-friendly topics for a given area.
    """
    sys = "You are an expert Chief Editor generating high-level, timely blog topics."
    usr = f"Area: {area}\nGenerate {max_topics} distinct, trending, SEO-friendly topics. Return one per line."

    logger.info(f"Requesting topics for area={area}, max_topics={max_topics}")
    text = _complete(sys, usr)
    topics = [t.strip("-• ").strip() for t in text.splitlines() if t.strip()][:max_topics]
    logger.info(f"Generated {len(topics)} topics for area={area}")
    return topics