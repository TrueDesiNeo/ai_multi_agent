# =============================================================================
# File: service.py
# Description:
#     NATS-backed Writer microservice that:
#       - Listens on a NATS subject for A2A envelopes from the Section Editor,
#       - Extracts drafting parameters from the payload,
#       - Delegates to WriterAgent to generate a section draft via LLM,
#       - Publishes a child envelope to the Verifier subject.
#
# Key Features:
#     - TLS support for NATS connections (optional custom CA)
#     - Graceful shutdown via SIGINT/SIGTERM
#     - Structured logging throughout the lifecycle
#     - A2A envelope trace/context propagation across services
#     - Pydantic v1/v2 JSON compatibility for publishing
#
# Subjects:
#     - Input:  demo.write.in
#     - Output: demo.verify.in
#
# Environment Variables:
#     - NATS_HOST        (default: 127.0.0.1)
#     - NATS_PORT        (default: 4222)
#     - NATS_USER        (default: "")
#     - NATS_PASS        (default: "")
#     - NATS_TLS         (default: "true")
#     - NATS_TLS_CAFILE  (default: None)  # path to custom CA bundle (PEM)
#
# Usage:
#     $ python writer_service.py
#
# Dependencies:
#     - Python 3.10+
#     - nats-py (nats.aio)
#     - pydantic (A2AEnvelope)
#     - Local modules: WriterAgent, common_envelope, logging_init
#
# ======================================================================

import asyncio
import json
import ssl
import signal
from typing import Optional, Any, List

from nats.aio.client import Client as NATS
from WriterAgent import WriterAgent
from common_envelope import A2AEnvelope
from logging_init import _env, _parse_bool, logger

# -----------------------------------------------------------------------------
# NATS Configuration
# -----------------------------------------------------------------------------
# Fetch NATS connection details from environment variables with defaults.
NATS_HOST = _env("NATS_HOST", "127.0.0.1")
NATS_PORT = _env("NATS_PORT", "4222")
NATS_USER = _env("NATS_USER", "")
NATS_PASS = _env("NATS_PASS", "")
NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))  # Enable TLS by default
NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")  # Optional custom CA bundle (PEM)

SERVICE_NAME = "writer@v1"
WRITE_IN_SUBJECT = "demo.write.in"
VERIFY_IN_SUBJECT = "demo.verify.in"

# -----------------------------------------------------------------------------
# TLS Context Builder
# -----------------------------------------------------------------------------
def _build_tls_context() -> Optional[ssl.SSLContext]:
    """
    Create and return an SSLContext if TLS is enabled; otherwise None.
    Logs the process and handles errors gracefully.
    """
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
# Helper: Convert Envelope to JSON Bytes
# -----------------------------------------------------------------------------
def _to_json_bytes(env) -> bytes:
    """
    Convert envelope object to UTF-8 encoded JSON bytes.
    Handles compatibility between Pydantic v1 and v2.
    """
    try:
        return env.model_dump_json().encode("utf-8")  # Pydantic v2
    except AttributeError:
        return env.json().encode("utf-8")  # Pydantic v1

# -----------------------------------------------------------------------------
# Writer Agent Initialization
# -----------------------------------------------------------------------------
_agent = WriterAgent()

# -----------------------------------------------------------------------------
# Message Handler
# -----------------------------------------------------------------------------
async def _handle(nc: NATS, msg) -> None:
    """
    Handle incoming messages for Writer service.
    Decodes message, extracts payload, generates draft, and sends to verifier.
    """
    try:
        raw = msg.data.decode("utf-8")
        data: dict[str, Any] = json.loads(raw)
        env = A2AEnvelope(**data)  # type: ignore[call-arg]

        cid = getattr(env, "conversation_id", None)
        retries = getattr(env, "retries", 0)
        p = env.payload or {}

        # Extract payload details
        topic = p.get("topic", "Untitled")
        section = p.get("section", "Section")
        style = p.get("style", "neutral, SEO-optimized, concise but informative")
        sources: List[str] = p.get("sources", []) or []
        feedback = p.get("feedback")
        max_retries = int(p.get("max_retries", 2))

        logger.info(f"[Writer] Received message: conversation_id={cid}, topic={topic}, section={section}, revision={bool(feedback)}")

        # Generate draft using WriterAgent
        draft = _agent.draft(topic, section, style, sources, feedback)
        logger.info(f"[Writer] Draft generated for section='{section}' in topic='{topic}'")

        # Prepare envelope for verifier
        out = env.child(
            sender=SERVICE_NAME,
            target="verifier@v1",
            payload={
                "role": "writer",
                "task": p.get("task", ""),
                "topic": topic,
                "section": section,
                "draft": draft,
                "sources": sources,
                "research_notes": p.get("research_notes", ""),
                "max_retries": max_retries,
                "retries": retries + 1,
            },
        )

        # Publish draft to verifier
        await nc.publish(VERIFY_IN_SUBJECT, _to_json_bytes(out))
        logger.info(f"[Writer] Sent draft to verifier: conversation_id={cid}, section={section}")

    except Exception as exc:
        logger.info(f"[Writer] Handler failure subject={getattr(msg, 'subject', '?')} error={exc}")

# -----------------------------------------------------------------------------
# Main Service Runner
# -----------------------------------------------------------------------------
async def run():
    """
    Connect to NATS, subscribe to Writer subject, and keep the service alive.
    """
    url = f"nats://{NATS_HOST}:{NATS_PORT}"
    tls = _build_tls_context()
    nc = NATS()

    logger.info(f"[Writer] Connecting to NATS at {url}")
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
    logger.info(f"[Writer] Connected to NATS at {url}")

    # Subscribe to Writer input subject
    async def _cb(msg): await _handle(nc, msg)
    await nc.subscribe(WRITE_IN_SUBJECT, cb=_cb)
    logger.info(f"[Writer] Subscribed to subject={WRITE_IN_SUBJECT}")

    # Keep service running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info(f"[Writer] Shutdown signal received.")
    finally:
        try:
            await nc.drain()
            await nc.close()
            logger.info(f"[Writer] NATS connection closed.")
        except Exception:
            logger.info(f"[Writer] Error occurred while closing NATS connection.")

# -----------------------------------------------------------------------------
# Signal Handling
# -----------------------------------------------------------------------------
def _install(loop):
    """
    Register signal handlers for clean shutdown.
    """
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, lambda: asyncio.create_task(_cancel(loop)))
            logger.info(f"[Writer] Signal handler installed for {s}")
        except Exception:
            logger.info(f"[Writer] Failed to install signal handler for {s}")

async def _cancel(loop):
    """
    Cancel all tasks and shutdown the loop.
    """
    logger.info(f"[Writer] Cancelling all tasks...")
    for t in asyncio.all_tasks(loop):
        if t.get_name() == "main":
            t.cancel()

# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
def main():
    """
    Main entry point for the Writer service.
    Initializes event loop and starts the service.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install(loop)
    task = loop.create_task(run(), name="main")

    try:
        loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        logger.info(f"[Writer] Event loop closed.")

if __name__ == "__main__":
    logger.info(f"Starting the [Writer] Server ....")
    main()