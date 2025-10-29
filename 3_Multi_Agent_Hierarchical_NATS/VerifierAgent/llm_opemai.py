# =============================================================================
# File: llm_openai.py
# Description:
#     OpenAI-compatible scoring module for drafting quality control. Scores a
#     section draft for clarity, conciseness, tone, safety/compliance, and
#     factual soundness. Falls back to a heuristic scorer if the LLM request
#     fails or returns invalid JSON.
#
# Key Features:
#     - Configurable model/base URL/temperature via environment variables
#     - Tenacity-based retries with exponential backoff
#     - Strict JSON-only contract for LLM response
#     - Heuristic fallback with capped feedback length
#
# Usage:
#     score, feedback = score_with_llm(draft, sources, research_notes)
#
# Environment Variables:
#     - MODEL_URL                        
#     - OPENAI_API_KEY                   
#     - VERIFIER_MODEL_NAME              
#     - VERIFIER_MODEL_LLM_TEMPERATURE   
#     - MAX_FEEDBACK_CHARS               
#
# Dependencies:
#     - Python 3.10+
#     - openai (OpenAI-compatible client)
#     - tenacity
#     - logging_init: _env, _parse_float, _parse_int, logger
#
# Notes:
#     - The model must return ONLY JSON with keys: {"score": number, "feedback": string}
#     - Feedback is truncated to MAX_FEEDBACK_CHARS
#
# =============================================================================

import json
from openai import OpenAI
from typing import List, Tuple
from tenacity import retry, wait_exponential, stop_after_attempt
from logging_init import _env, _parse_float, logger, _parse_int

# -----------------------------------------------------------------------------
# LLM Configuration
# -----------------------------------------------------------------------------
MODEL_URL = _env("MODEL_URL", "EMPTY")
MODEL_API_KEY = _env("OPENAI_API_KEY", "EMPTY")
VERIFIER_MODEL = _env("VERIFIER_MODEL_NAME", "llama-3-1-8b-instruct")
VERIFIER_MODEL_LLM_TEMPERATURE = _parse_float(
    _env("VERIFIER_MODEL_LLM_TEMPERATURE", "0.3"), 0.3
)
MAX_FEEDBACK_CHARS = _parse_int(_env("MAX_FEEDBACK_CHARS", "500"), 500)

# System prompt for LLM scoring
SYSTEM_PROMPT = (
    "You are a strict technical editor and safety reviewer for software-engineering content. "
    "Evaluate the DRAFT for clarity, conciseness, tone, safety/compliance, and factual soundness. "
    "Return ONLY JSON with keys: {\"score\": number (1-10), \"feedback\": string (<=280 chars)}"
)

# -----------------------------------------------------------------------------
# Heuristic Fallback Scoring
# -----------------------------------------------------------------------------
def heuristic_score(text: str) -> Tuple[float, str]:
    """
    Provide a simple heuristic score when LLM is unavailable or fails.
    Adds points for structure and length, and gives basic feedback.
    """
    score = 5.5
    if "Key point" in text or "•" in text:
        score += 0.5
    if "Takeaway" in text:
        score += 0.3
    if len(text) > 300:
        score += 0.4

    feedback = "Looks good."
    if "Sources:" not in text:
        feedback = "Add 1–2 credible sources and tighten the lead sentence."

    return min(score, 10.0), feedback[:MAX_FEEDBACK_CHARS]

# -----------------------------------------------------------------------------
# Initialize OpenAI Client
# -----------------------------------------------------------------------------
_client = OpenAI(
    base_url=MODEL_URL,
    api_key=MODEL_API_KEY)
logger.info(f"Connected to LLM at {MODEL_URL}")

# -----------------------------------------------------------------------------
# LLM-based Scoring Function
# -----------------------------------------------------------------------------
@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
def score_with_llm(draft: str, sources: List[str], research_notes: str) -> Tuple[float, str]:
    """
    Score a draft using LLM for clarity, tone, compliance, and factual soundness.
    Returns a tuple of (score, feedback).
    Falls back to heuristic scoring if LLM fails or response is invalid.
    """
    if not _client:
        logger.info("LLM client unavailable; using heuristic scoring.")
        return heuristic_score(draft)

    # Build user prompt with sources and research notes
    user = (
        f"SOURCES: {', '.join(sources[:5]) if sources else 'None'}\n"
        f"RESEARCH_NOTES:\n{research_notes or '(not provided)'}\n\n"
        f"DRAFT:\n{draft}\n\n"
        "Output JSON only."
    )

    logger.info(f"Sending draft for scoring to LLM model={VERIFIER_MODEL}")
    r = _client.chat.completions.create(
        model=VERIFIER_MODEL,
        temperature=VERIFIER_MODEL_LLM_TEMPERATURE,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )

    content = r.choices[0].message.content.strip()
    logger.info(f"Received response from LLM")

    # Parse JSON response from LLM
    try:
        data = json.loads(content)
        score = float(data.get("score", 0))
        feedback = (data.get("feedback") or "").strip()
    except Exception as exc:
        logger.info(f"Failed to parse LLM response; using heuristic scoring. error={exc}")
        return heuristic_score(draft)

    # Normalize score and feedback
    score = max(1.0, min(10.0, score))
    if not feedback:
        feedback = "Clarify the main point and provide a concrete example."

    logger.info(f"Final score={score}, feedback_length={len(feedback)}")
    return score, feedback[:MAX_FEEDBACK_CHARS]