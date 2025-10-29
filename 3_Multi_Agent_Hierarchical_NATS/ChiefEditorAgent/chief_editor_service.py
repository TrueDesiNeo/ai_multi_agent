# =============================================================================
# File: chief_editor_service.py
# Description:
#     NATS-backed Chief Editor microservice that:
#       - Listens on a NATS subject for A2A envelopes,
#       - Extracts request payload (area, limits, etc.),
#       - Delegates to ChiefEditorAgent to propose topics,
#       - Fan-outs child envelopes to the Section Editor subject.
#
# Key Features:
#     - TLS support for NATS connections (custom CA optional)
#     - Graceful shutdown via SIGINT/SIGTERM
#     - Structured logging for observability
#     - A2A envelope tracing and conversation correlation
#
# Subjects:
#     - Input:  demo.chief.in
#     - Output: demo.section.in
#
# Environment Variables:
#     - NATS_HOST              (default: 127.0.0.1)
#     - NATS_PORT              (default: 4222)
#     - NATS_USER              (default: "")
#     - NATS_PASS              (default: "")
#     - NATS_TLS               (default: "true")
#     - NATS_TLS_CAFILE        (default: None)
#
# Usage:
#     $ python chief_editor_service.py
#
# Dependencies:
#     - Python 3.10+
#     - nats-py (nats.aio)
#     - pydantic (used by A2AEnvelope)
#     - Your local modules: ChiefEditorAgent, common_envelope, logging_init
#
# Notes:
#     - Child messages keep the conversation_id and update trace context
#     - Uses pydantic v2 JSON serialization (`model_dump_json`) for publish
# =============================================================================

import asyncio
import json
import ssl
import signal
from typing import Optional, List, Any

from nats.aio.client import Client as NATS
from ChiefEditorAgent import ChiefEditorAgent
from common_envelope import A2AEnvelope
from logging_init import _env, _parse_bool, logger

# -----------------------------------------------------------------------------
# NATS Configuration
# -----------------------------------------------------------------------------
NATS_HOST = _env("NATS_HOST", "127.0.0.1")
NATS_PORT = _env("NATS_PORT", "4222")
NATS_USER = _env("NATS_USER", "")
NATS_PASS = _env("NATS_PASS", "")
NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))
NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")

# -----------------------------------------------------------------------------
# Service Configuration
# -----------------------------------------------------------------------------
SERVICE_NAME = "chiefEditor@v1"
CHIEF_EDITOR_IN_SUBJECT = "demo.chief.in"
SECTION_EDITOR_IN_SUBJECT = "demo.section.in"

# -----------------------------------------------------------------------------
# TLS Context Builder
# -----------------------------------------------------------------------------
def _build_tls_context() -> Optional[ssl.SSLContext]:
    """Create and return an SSLContext if TLS is enabled; otherwise None."""
    if not NATS_TLS_ENABLED:
        logger.info(f"TLS is disabled for NATS connection.")
        return None

    try:
        if NATS_TLS_CAFILE:
            logger.info(f"Using custom CA file for TLS verification: {NATS_TLS_CAFILE}")
            ctx = ssl.create_default_context(cafile=NATS_TLS_CAFILE)
        else:
            logger.info(f"Using default SSL context for TLS.")
            ctx = ssl.create_default_context()
        return ctx
    except Exception as exc:
        logger.info(f"Failed to build TLS context; disabling TLS. error={exc}")
        return None

# -----------------------------------------------------------------------------
# Chief Editor Agent Initialization
# -----------------------------------------------------------------------------
_agent = ChiefEditorAgent()

# -----------------------------------------------------------------------------
# Message Handler
# -----------------------------------------------------------------------------
async def _handle(nc: NATS, msg) -> None:
    """Handle incoming messages for Chief Editor."""
    try:
        raw = msg.data.decode("utf-8")
        data: dict[str, Any] = json.loads(raw)
        env = A2AEnvelope(**data)  # type: ignore[call-arg]

        cid = getattr(env, "conversation_id", None)
        payload = env.payload or {}

        area = payload.get("area", "General")
        max_topics = int(payload.get("max_topics", 5))
        max_sections = int(payload.get("max_sections", 6))
        style = payload.get("style", "neutral, SEO-optimized, concise but informative")
        sources: List[str] = payload.get("sources", []) or []

        logger.info(f"[Chief] Received conversation_id={cid}, area={area}, max_topics={max_topics}")

        topics = _agent.propose(area, max_topics)
        logger.info(f"[Chief] Proposed topics: {topics}")

        for t in topics:
            out = env.child(
                sender=SERVICE_NAME,
                target="section@v1",
                payload={
                    "role": "chief",
                    "topic": t,
                    "max_sections": max_sections,
                    "style": style,
                    "sources": sources,
                    "max_retries": int(payload.get("max_retries", 2)),
                },
            )
            await nc.publish(SECTION_EDITOR_IN_SUBJECT, out.model_dump_json().encode("utf-8"))
            logger.info(f"[Chief] Published topic '{t}' to {SECTION_EDITOR_IN_SUBJECT}")

        logger.info(f"[Chief] Dispatched {len(topics)} topics for conversation_id={cid}")

    except Exception as exc:
        logger.info(f"[Chief] Handler failure subject={getattr(msg, 'subject', '?')} error={exc}")

# -----------------------------------------------------------------------------
# Main Service Runner
# -----------------------------------------------------------------------------
async def run() -> None:
    """Connect to NATS and subscribe to Chief Editor subject."""
    url = f"nats://{NATS_HOST}:{NATS_PORT}"
    tls = _build_tls_context()
    nc = NATS()

    logger.info(f"Attempting to connect to NATS at {url}")
    await nc.connect(
        servers=[url],
        user=NATS_USER or None,
        password=NATS_PASS or None,
        tls=tls,
        connect_timeout=10,
        reconnect_time_wait=2,
        max_reconnect_attempts=3,
        allow_reconnect=True,
        name=SERVICE_NAME,
    )
    logger.info(f"Connected to NATS server at {url}")

    async def _cb(msg): await _handle(nc, msg)
    await nc.subscribe(CHIEF_EDITOR_IN_SUBJECT, cb=_cb)
    logger.info(f"Subscribed to subject: {CHIEF_EDITOR_IN_SUBJECT}")

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info(f"Shutdown signal received; closing NATS connection...")
    finally:
        try:
            await nc.drain()
            await nc.close()
            logger.info(f"NATS connection closed successfully.")
        except Exception:
            logger.info(f"Error occurred while closing NATS connection.")

# -----------------------------------------------------------------------------
# Signal Handling
# -----------------------------------------------------------------------------
def _install(loop):
    """Register signal handlers for clean shutdown."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_cancel(loop)))
            logger.info(f"Signal handler installed for {sig}")
        except Exception:
            logger.info(f"Failed to install signal handler for {sig}")

async def _cancel(loop):
    """Cancel all tasks and shutdown the loop."""
    logger.info(f"Cancelling all tasks...")
    for t in asyncio.all_tasks(loop):
        if t.get_name() == "main":
            t.cancel()

# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
def main():
    """Main entry point for the Chief Editor service."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install(loop)
    task = loop.create_task(run(), name="main")

    try:
        loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        logger.info(f"Event loop closed.")

if __name__ == "__main__":
    logger.info(f"Starting the [ChiefEditor] Server ....")
    main()
    