#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NATS writer service.

- Subscribes to 'demo.write.in' for write requests.
- Produces a draft (via OpenAI or a local stub) and publishes to 'demo.verify.in'.
- TLS is supported (optional). Self-signed/internal CAs can be configured via env.
- Graceful shutdown on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import ssl
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from nats.aio.client import Client as NATS
from nats.errors import NoServersError

# -----------------------------------------------------------------------------
# Import project-local modules (Common/a2a_protocol)
# -----------------------------------------------------------------------------
# Keep the original relative path behavior. Prefer explicit sys.path update.
sys.path.append(os.path.abspath(os.path.join("..", "Common", "a2a_protocol")))
from Common.a2a_protocol.common_envelope import A2AEnvelope  # type: ignore[attr-defined]

# -----------------------------------------------------------------------------
# Constants & Defaults
# -----------------------------------------------------------------------------
SERVICE_NAME = "writer@v1"
TARGET_SERVICE = "verifier@v1"
WRITE_IN_SUBJECT = "demo.write.in"
VERIFY_IN_SUBJECT = "demo.verify.in"

LOG_FORMAT = (
    "%(asctime)s.%(msecs)03dZ | %(levelname)s | %(name)s | %(message)s"
)  # ISO-like with millis
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# -----------------------------------------------------------------------------
# Environment & Logging
# -----------------------------------------------------------------------------
load_dotenv()

def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse a boolean-like env var safely."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Convenience getter for environment variables with default."""
    return os.getenv(key, default)

# Configure logging early
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT)
# Ensure UTC timestamps in logs
logging.Formatter.converter = lambda *args: __import__("time").gmtime(*args)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Configuration from Environment
# -----------------------------------------------------------------------------
NATS_HOST = _env("NATS_HOST", "127.0.0.1")
NATS_PORT = _env("NATS_PORT", "4222")
NATS_USER = _env("NATS_USER", "")
NATS_PASS = _env("NATS_PASS", "")

# TLS
NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))  # default to TLS on
NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")  # optional CA bundle path for self-signed

# OpenAI / LLM
USE_OPENAI = _parse_bool(_env("USE_OPENAI", "false"))
MODEL_URL = os.getenv("MODEL_URL", "https://api.openai.com/v1")
MODEL_API_KEY = _env("OPENAI_API_KEY", "EMPTY")  # harmless default
WRITER_MODEL = _env("WRITER_MODEL_NAME", "llama-3-1-8b-instruct")
LLM_TEMPERATURE = float(_env("WRITER_TEMPERATURE", "0.3"))


# -----------------------------------------------------------------------------
# Optional OpenAI initialization (lazy)
# -----------------------------------------------------------------------------
_llm = None
if USE_OPENAI:
    try:
        from langchain_openai import ChatOpenAI

        _llm = ChatOpenAI(
            base_url=MODEL_URL,
            api_key=MODEL_API_KEY,
            model=WRITER_MODEL,
            temperature=LLM_TEMPERATURE,
        )
        logger.info("Using OpenAI-compatible model for drafting: %s", WRITER_MODEL)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to initialize OpenAI LLM; falling back to stub. error=%s", exc
        )
        USE_OPENAI = False
else:
    logger.info("Using stub draft generator (no OpenAI).")

# -----------------------------------------------------------------------------
# Drafting Logic
# -----------------------------------------------------------------------------
def draft_stub(
    task: str,
    notes: str,
    sources: Optional[List[str]],
    feedback: str,
) -> str:
    """
    Generate a simple draft response using provided task, notes, sources, and feedback.
    Used when OpenAI is disabled.
    """
    lines: List[str] = [f"Answer: {task.strip()}"]
    if notes:
        lines.append("Key points:")
        for ln in notes.splitlines():
            stripped = ln.strip()
            if stripped.startswith("-"):
                lines.append(stripped)
            if len(lines) >= 6:  # limit a bit: heading + up to 4 bullets
                break
    if feedback:
        lines.append(f"Revision applied: {feedback.strip()}")
    if sources:
        capped = [s for s in sources if s][:3]
        if capped:
            lines.append("Sources: " + ", ".join(capped))
    return "\n".join(lines)

async def generate_draft_async(
    task: str,
    notes: str,
    sources: Optional[List[str]],
    feedback: str,
) -> str:
    """
    Generate a draft, using OpenAI if enabled and available, otherwise stub.
    Uses non-blocking `ainvoke` when supported to avoid blocking the event loop.
    """
    if not USE_OPENAI or _llm is None:
        logger.debug("Draft generation via stub (OpenAI disabled or unavailable).")
        return draft_stub(task, notes, sources, feedback)

    # Prepare prompts
    system_msg = "You are a concise technical writer for software engineers."
    sources_str = ", ".join((sources or [])[:3]) if sources else ""
    user_msg = (
        f"Task: {task}\n"
        f"Use these research notes:\n{notes}\n"
        f"Sources: {sources_str}\n"
    )
    if feedback:
        user_msg += f"\nApply this feedback: {feedback}\n"

    try:
        # Prefer ainvoke if available
        if hasattr(_llm, "ainvoke"):
            resp = await _llm.ainvoke([("system", system_msg), ("user", user_msg)])  # type: ignore[func-returns-value]
        else:
            # Fallback: run the blocking call in a thread
            resp = await asyncio.to_thread(
                _llm.invoke,  # type: ignore[attr-defined]
                [("system", system_msg), ("user", user_msg)],
            )
        content = getattr(resp, "content", None)
        if not content:
            logger.warning("LLM returned empty content; falling back to stub.")
            return draft_stub(task, notes, sources, feedback)
        logger.debug("Draft generated using OpenAI-compatible model.")
        return content
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM draft generation failed; using stub. error=%s", exc)
        return draft_stub(task, notes, sources, feedback)

# -----------------------------------------------------------------------------
# NATS Connection & Service Loop
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
            # Default system CAs. Verification remains ON.
            ctx = ssl.create_default_context()
        return ctx
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build TLS context; TLS disabled. error=%s", exc)
        return None

async def _message_handler(nc: NATS, msg) -> None:
    """
    Callback handler for incoming messages on WRITE_IN_SUBJECT.
    Parses the payload, drafts a response, and publishes to VERIFY_IN_SUBJECT.
    """
    try:
        raw = msg.data.decode("utf-8")
    except Exception:  # noqa: BLE001
        logger.error("Received non-UTF-8 message; dropping.")
        return

    correlation = None
    try:
        data: Dict[str, Any] = json.loads(raw)
        env = A2AEnvelope(**data)  # type: ignore[call-arg]
        correlation = getattr(env, "conversation_id", None)

        payload: Dict[str, Any] = env.payload or {}

        task: str = payload.get("task", "") or ""
        notes: str = payload.get("research_notes", "") or ""
        sources: List[str] = payload.get("sources", []) or []
        feedback: str = payload.get("feedback", "") or ""

        logger.info(
            "[Writer] Drafting | conversation_id=%s | retry=%s",
            correlation,
            getattr(env, "retries", 0),
        )

        draft = await generate_draft_async(task, notes, sources, feedback)

        # Create a child envelope for the verifier
        out = env.child(
            sender=SERVICE_NAME,
            target=TARGET_SERVICE,
            payload={
                "role": "writer",
                "task": task,
                "draft": draft,
                "sources": sources,
            },
        )

        await nc.publish(
            VERIFY_IN_SUBJECT, json.dumps(out.model_dump()).encode("utf-8")
        )
        logger.info(
            "[Writer] Published draft to verifier | conversation_id=%s",
            correlation,
        )

    except json.JSONDecodeError:
        logger.exception("Invalid JSON on subject=%s; dropping message.", msg.subject)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Handler failure | subject=%s | conversation_id=%s | error=%s",
            getattr(msg, "subject", "?"),
            correlation,
            exc,
        )

async def run() -> None:
    """
    Main async function:
    - Connect to NATS with optional TLS.
    - Subscribe to WRITE_IN_SUBJECT and process messages.
    - Keep running until cancelled (SIGINT/SIGTERM).
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
    except NoServersError:
        logger.exception("Failed to connect to NATS servers: %s", nat_url)
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error connecting to NATS: %s", exc)
        raise

    # Subscribe to incoming write requests
    async def _cb(msg):
        await _message_handler(nc, msg)

    sid = await nc.subscribe(WRITE_IN_SUBJECT, cb=_cb)

    logger.info("[Writer] Subscribed to '%s' | sid=%s", WRITE_IN_SUBJECT, sid)

    # Wait forever (until cancelled)
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
            # Some platforms (e.g., Windows) may not support add_signal_handler
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