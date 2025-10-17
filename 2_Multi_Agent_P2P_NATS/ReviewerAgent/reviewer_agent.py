#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A2A Verifier Service

- Subscribes to 'demo.verify.in' to score drafts.
- Uses an LLM (or a heuristic fallback) to score and provide feedback.
- Publishes feedback to 'demo.write.in' for revisions, or final output to 'demo.done'.
- Supports NATS TLS (optional) and graceful shutdown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import ssl
import sys
from typing import Any, List, Optional, Tuple

from dotenv import load_dotenv
from nats.aio.client import Client as NATS

# -----------------------------------------------------------------------------
# Import project-local modules (Common/a2a_protocol)
# -----------------------------------------------------------------------------
sys.path.append(os.path.abspath(os.path.join("..", "Common", "a2a_protocol")))
from Common.a2a_protocol.common_envelope import A2AEnvelope  # type: ignore[attr-defined]

# -----------------------------------------------------------------------------
# Constants & Subjects
# -----------------------------------------------------------------------------
SERVICE_NAME = "verifier@v1"
VERIFY_IN_SUBJECT = "demo.verify.in"
WRITE_IN_SUBJECT = "demo.write.in"
DONE_SUBJECT = "demo.done"

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# -----------------------------------------------------------------------------
# Environment & Logging
# -----------------------------------------------------------------------------
load_dotenv()

def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _parse_float(value: Optional[str], default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default

def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)

# Configure logging (UTC timestamps)
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=DATE_FORMAT)
logging.Formatter.converter = lambda *args: __import__("time").gmtime(*args)  # type: ignore[assignment]
logger = logging.getLogger("verifier_a2a")

# -----------------------------------------------------------------------------
# NATS Configuration
# -----------------------------------------------------------------------------
NATS_HOST = _env("NATS_HOST", "127.0.0.1")
NATS_PORT = _env("NATS_PORT", "4222")
NATS_USER = _env("NATS_USER", "")
NATS_PASS = _env("NATS_PASS", "")

NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))  # default to TLS on
NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")  # optional custom CA bundle (PEM)

# -----------------------------------------------------------------------------
# Scoring Settings
# -----------------------------------------------------------------------------
MIN_ACCEPTABLE_SCORE = _parse_float(_env("MIN_ACCEPTABLE_SCORE", "7.0"), 7.0)
MAX_FEEDBACK_CHARS = int(_env("MAX_FEEDBACK_CHARS", "280"))

# -----------------------------------------------------------------------------
# LLM Configuration (optional)
# -----------------------------------------------------------------------------
USE_OPENAI = _parse_bool(_env("USE_OPENAI", "false"))
MODEL_URL = _env("MODEL_URL", "https://api.openai.com/v1")
MODEL_API_KEY = _env("OPENAI_API_KEY", "EMPTY")  # harmless default
REVIEW_MODEL = _env("REVIEWER_MODEL_NAME", "llama-3-1-8b-instruct")
LLM_TEMPERATURE = _parse_float(_env("REVIEWER_TEMPERATURE", "0.3"), 0.3)


_llm = None
if USE_OPENAI:
    try:
        from langchain_openai import ChatOpenAI

        _llm = ChatOpenAI(
            base_url=MODEL_URL,
            api_key=MODEL_API_KEY,
            model=REVIEW_MODEL,
            temperature=LLM_TEMPERATURE,
        )
        logger.info("Using OpenAI-compatible model for reviewing: %s", REVIEW_MODEL)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OpenAI client init failed; falling back to heuristic scoring. error=%s",
            exc,
        )
        _llm = None
else:
    logger.info("LLM disabled; using heuristic scoring.")

# -----------------------------------------------------------------------------
# Heuristic & LLM Scoring
# -----------------------------------------------------------------------------
def heuristic_score(text: str) -> Tuple[float, str]:
    """
    Simple rule-based scoring function for evaluating draft quality.
    Returns a score (float) and feedback (str).
    """
    score = 5.5
    fb: List[str] = []

    if "Key points:" in text:
        score += 0.6
    if "Sources:" in text:
        score += 0.4
    if any(k in text.lower() for k in ["concise", "clear", "engineer", "policy"]):
        score += 0.3
    if len(text) > 300:
        score += 0.2

    if "Revision applied:" not in text:
        fb.append("Tighten language; add one explicit action for the reader.")
    if "Sources:" not in text:
        fb.append("Add 1–2 sources for credibility.")

    final_score = min(score, 10.0)
    feedback = " ".join(fb) or "Looks good."
    logger.debug("Heuristic score: %.1f, Feedback: %s", final_score, feedback)
    return final_score, feedback

# System prompt for LLM scoring
LLM_SYSTEM_PROMPT = (
    "You are a strict technical editor and safety reviewer for software-engineering content. "
    "Evaluate the provided DRAFT for clarity, conciseness, tone/professionalism, policy/safety risk, "
    "and use of provided sources. If sources are present, ensure the draft references them appropriately "
    "and avoids hallucinations. Provide actionable, concise feedback.\n\n"
    "Return ONLY a strict JSON object with keys:\n"
    "{\n"
    '  "score": number (1-10, floats allowed),\n'
    '  "feedback": string (<= 280 chars, actionable, no markdown, no quotes)\n'
    "}\n"
    "Do not include any extra keys or commentary."
)

def build_user_prompt(draft: str, sources: List[str], research_notes: str) -> str:
    src_str = ", ".join(sources[:5]) if sources else "None"
    notes = research_notes or "(not provided)"
    return (
        "TASK: You are a strict reviewer of tone, safety, and policy adherence.\n\n"
        f"SOURCES: {src_str}\n\n"
        f"RESEARCH_NOTES:\n{notes}\n\n"
        f"DRAFT:\n{draft}\n\n"
        "Scoring rubric (holistic):\n"
        "- Clarity & conciseness for the target audience\n"
        "- Tone & professionalism; avoid hype\n"
        "- Policy/safety risk (no PII, no prohibited content, no unsafe claims)\n"
        "- Use of sources (if present): attribution and correctness\n"
        "- Technical accuracy relative to the notes\n\n"
        "Output JSON only."
    )

async def score_with_llm(
    draft: str, sources: List[str], research_notes: str
) -> Tuple[float, str]:
    """
    Uses LLM to score the draft. Falls back to heuristic scoring on error.
    Returns (score: float, feedback: str).
    Uses non-blocking ainvoke or runs invoke in a thread.
    """
    if _llm is None:
        return heuristic_score(draft)

    try:
        messages = [("system", LLM_SYSTEM_PROMPT), ("user", build_user_prompt(draft, sources, research_notes))]

        # Prefer non-blocking ainvoke if available
        if hasattr(_llm, "ainvoke"):
            resp = await _llm.ainvoke(messages)  # type: ignore[func-returns-value]
        else:
            resp = await asyncio.to_thread(_llm.invoke, messages)  # type: ignore[attr-defined]

        content = getattr(resp, "content", None)
        if not content:
            logger.warning("LLM returned empty content; using heuristic scoring.")
            return heuristic_score(draft)

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON content; using heuristic. content=%r", content[:200])
            return heuristic_score(draft)

        score = float(data.get("score", 0))
        feedback = str(data.get("feedback", "")).strip()

        # Bounds & defaults
        score = max(1.0, min(10.0, score))
        if not feedback:
            feedback = "Clarify the main point; add 1–2 concrete, testable tips."
        if len(feedback) > MAX_FEEDBACK_CHARS:
            feedback = feedback[: max(0, MAX_FEEDBACK_CHARS - 3)] + "..."

        logger.debug("LLM score: %.1f, Feedback: %s", score, feedback)
        return score, feedback

    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM scoring failed; using heuristic. error=%s", exc)
        return heuristic_score(draft)

# -----------------------------------------------------------------------------
# NATS Helpers
# -----------------------------------------------------------------------------
def _build_tls_context() -> Optional[ssl.SSLContext]:
    """Create and return an SSLContext if TLS is enabled; otherwise None."""
    if not NATS_TLS_ENABLED:
        logger.info("TLS is disabled for NATS connection.")
        return None
    try:
        if NATS_TLS_CAFILE:
            logger.info("Using custom CA file for TLS verification: %s", NATS_TLS_CAFILE)
            ctx = ssl.create_default_context(cafile=NATS_TLS_CAFILE)
        else:
            ctx = ssl.create_default_context()
        return ctx
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build TLS context; disabling TLS. error=%s", exc)
        return None

async def _message_handler(nc: NATS, msg) -> None:
    """
    Handles incoming messages on VERIFY_IN_SUBJECT.
    Scores the draft and publishes feedback (to writer) or final result (to client).
    """
    try:
        raw = msg.data.decode("utf-8")
    except Exception:
        logger.error("Received non-UTF-8 message; dropping.")
        return

    correlation = None
    try:
        data: dict[str, Any] = json.loads(raw)
        env = A2AEnvelope(**data)  # type: ignore[call-arg]
        correlation = getattr(env, "conversation_id", None)

        payload: dict[str, Any] = env.payload or {}
        draft: str = payload.get("draft", "") or ""
        sources: List[str] = payload.get("sources", []) or []
        research_notes: str = payload.get("research_notes", "") or ""
        task: str = payload.get("task", "") or ""

        logger.info(
            "[Verifier] Scoring | conversation_id=%s | retries=%s | draft_len=%d | sources=%d",
            correlation,
            getattr(env, "retries", 0),
            len(draft),
            len(sources),
        )

        score, fb = await score_with_llm(draft, sources, research_notes)

        logger.info(
            "[Verifier] Scored | conversation_id=%s | score=%.1f | retries=%s",
            correlation,
            score,
            getattr(env, "retries", 0),
        )

        # Decide to request revision or finalize
        retries = getattr(env, "retries", 0)
        max_retries = getattr(env, "max_retries", 0)

        if score < MIN_ACCEPTABLE_SCORE and retries < max_retries:
            # Send feedback to writer for revision
            out = env.child(
                sender=SERVICE_NAME,
                target="writer@v1",
                payload={
                    "role": "verifier",
                    "task": task,
                    "sources": sources,
                    "feedback": fb,
                },
                retries=retries + 1,
            )
            await nc.publish(WRITE_IN_SUBJECT, json.dumps(out.model_dump()).encode("utf-8"))
            logger.info(
                "[Verifier] Sent feedback to writer | conversation_id=%s | next_retry=%d",
                correlation,
                retries + 1,
            )
        else:
            # Finalize and send to client
            out = env.child(
                sender=SERVICE_NAME,
                target="client@v1",
                payload={
                    "role": "verifier",
                    "draft": draft,
                    "score": score,
                    "sources": sources,
                },
            )
            await nc.publish(DONE_SUBJECT, json.dumps(out.model_dump()).encode("utf-8"))
            logger.info("[Verifier] Sent final draft to client | conversation_id=%s", correlation)

    except json.JSONDecodeError:
        logger.exception("Invalid JSON on subject=%s; dropping message.", msg.subject)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Handler failure | subject=%s | conversation_id=%s | error=%s",
            getattr(msg, "subject", "?"),
            correlation,
            exc,
        )

# -----------------------------------------------------------------------------
# Main Service Loop
# -----------------------------------------------------------------------------
async def run() -> None:
    """
    Connect to NATS, subscribe to VERIFY_IN_SUBJECT with a coroutine callback,
    and run until cancelled.
    """
    nat_url = f"nats://{NATS_HOST}:{NATS_PORT}"
    tls_ctx = _build_tls_context()
    nc = NATS()

    logger.info(
        "Connecting to NATS | url=%s | tls=%s | user=%s",
        nat_url,
        bool(tls_ctx),
        "set" if NATS_USER else "none",
    )

    try:
        await nc.connect(
            servers=[nat_url],
            user=NATS_USER or None,
            password=NATS_PASS or None,
            tls=tls_ctx,
            connect_timeout=10,
            reconnect_time_wait=2,
            max_reconnect_attempts=3,
            allow_reconnect=True,
            name=SERVICE_NAME,
        )
        logger.info("Connected to NATS.")
        logger.info("[Verifier] Connected to %s (LLM=%s)", nat_url, "ON" if _llm else "OFF")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error connecting to NATS: %s", exc)
        raise

    # IMPORTANT: NATS requires a coroutine function for the subscription callback
    async def _subscription_cb(msg) -> None:
        await _message_handler(nc, msg)

    sid = await nc.subscribe(VERIFY_IN_SUBJECT, cb=_subscription_cb)
    logger.info("[Verifier] Subscribed to '%s' | sid=%s", VERIFY_IN_SUBJECT, sid)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Shutdown signal received; closing NATS...")
    finally:
        try:
            await nc.drain()
            await nc.close()
            logger.info("NATS connection closed.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error while closing NATS: %s", exc)

def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Register SIGINT/SIGTERM handlers to cancel the main task."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_cancel_main(loop)))
        except NotImplementedError:
            # Windows and some environments may not support this
            pass

async def _cancel_main(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel the main task if running."""
    tasks = [t for t in asyncio.all_tasks(loop) if t.get_name() == "main"]
    for t in tasks:
        t.cancel()

def main() -> None:
    """Entrypoint: start the event loop and run the service."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    main_task = loop.create_task(run(), name="main")
    try:
        loop.run_until_complete(main_task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

if __name__ == "__main__":
    main()