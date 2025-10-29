# =============================================================================
# File: section_editor_service.py
# Description:
#     NATS-backed Section Editor microservice that:
#       - Listens on a NATS subject for A2A envelopes from the Chief Editor,
#       - Extracts topic and options from the payload,
#       - Delegates to SectionEditorAgent to generate article sections,
#       - Publishes child envelopes to the Writer subject.
#
# Key Features:
#     - TLS support for NATS connections (optional custom CA)
#     - Graceful shutdown via SIGINT/SIGTERM
#     - Structured logging throughout the lifecycle
#     - A2A envelope trace/context propagation across services
#
# Subjects:
#     - Input:  demo.section.in
#     - Output: demo.write.in
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
#     $ python section_editor_service.py
#
# Dependencies:
#     - Python 3.10+
#     - nats-py (nats.aio)
#     - pydantic (A2AEnvelope)
#     - Local modules: SectionEditorAgent, common_envelope, logging_init
#
# ==========================================================================
import asyncio
import json
import ssl
import signal
from typing import Optional, Any

from nats.aio.client import Client as NATS
from SectionEditorAgent import SectionEditorAgent
from common_envelope import A2AEnvelope
from logging_init import _env, _parse_bool, logger

# -----------------------------------------------------------------------------
# NATS Configuration
# -----------------------------------------------------------------------------
NATS_HOST = _env("NATS_HOST", "127.0.0.1")
NATS_PORT = _env("NATS_PORT", "4222")
NATS_USER = _env("NATS_USER", "")
NATS_PASS = _env("NATS_PASS", "")
NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))  # default to TLS on
NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")  # optional custom CA bundle (PEM)

SERVICE_NAME = "sectionEditor@v1"
SECTION_IN_SUBJECT = "demo.section.in"
WRITE_IN_SUBJECT = "demo.write.in"

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
            logger.info(f"Using custom CA file for TLS verification: {NATS_TLS_CAFILE}", NATS_TLS_CAFILE)
            ctx = ssl.create_default_context(cafile=NATS_TLS_CAFILE)
        else:
            logger.info(f"Using default SSL context for TLS.")
            ctx = ssl.create_default_context()
        return ctx
    except Exception as exc:
        logger.info(f"Failed to build TLS context; disabling TLS. error={exc}")
        return None

# -----------------------------------------------------------------------------
# Section Editor Agent Initialization
# -----------------------------------------------------------------------------
_agent = SectionEditorAgent()

# -----------------------------------------------------------------------------
# Message Handler
# -----------------------------------------------------------------------------
async def _handle(nc: NATS, msg) -> None:
    """Handle incoming messages for Section Editor."""
    try:
        raw = msg.data.decode("utf-8")
        data: dict[str, Any] = json.loads(raw)
        env = A2AEnvelope(**data)  # type: ignore[call-arg]

        cid = getattr(env, "conversation_id", None)
        p = env.payload or {}

        topic = p.get("topic", "Untitled")
        max_sections = int(p.get("max_sections", 6))
        style = p.get("style", "neutral, SEO-optimized, concise but informative")
        sources = p.get("sources", [])
        max_retries = int(p.get("max_retries", 2))

        logger.info(f"[Section] Received conversation_id={cid}, topic={topic}, max_sections={max_sections}")

        sections = _agent.plan(topic, max_sections)
        logger.info(f"[Section] Planned {len(sections)} sections for topic={topic}")

        for sec in sections:
            out = env.child(
                sender=SERVICE_NAME,
                target="writer@v1",
                payload={
                    "role": "section",
                    "topic": topic,
                    "section": sec,
                    "style": style,
                    "sources": sources,
                    "research_notes": p.get("research_notes", ""),
                    "task": p.get("task", ""),
                    "max_retries": max_retries,
                },
            )
            await nc.publish(WRITE_IN_SUBJECT, out.model_dump_json().encode("utf-8"))
            logger.info(f"[Section] Published section '{sec}' for topic={topic}")

        logger.info(f"[Section] Assigned sections conversation_id={cid}, topic={topic}, count={len(sections)}")

    except Exception as exc:
        logger.info(f"[Section] Handler failure subject={getattr(msg, 'subject', '?')} error={exc}")

# -----------------------------------------------------------------------------
# Main Service Runner
# -----------------------------------------------------------------------------
async def run():
    """Connect to NATS and subscribe to Section Editor subject."""
    url = f"nats://{NATS_HOST}:{NATS_PORT}"
    tls = _build_tls_context()
    nc = NATS()

    logger.info(f"[Section] Connecting to NATS at {url}")
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
    logger.info(f"[Section] Connected to NATS at {url}")

    async def _cb(msg): await _handle(nc, msg)
    await nc.subscribe(SECTION_IN_SUBJECT, cb=_cb)
    logger.info(f"[Section] Subscribed to subject={SECTION_IN_SUBJECT}")

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info(f"[Section] Shutdown signal received.")
    finally:
        try:
            await nc.drain()
            await nc.close()
            logger.info(f"[Section] NATS connection closed.")
        except Exception:
            logger.info(f"[Section] Error occurred while closing NATS connection.")

# -----------------------------------------------------------------------------
# Signal Handling
# -----------------------------------------------------------------------------
def _install(loop):
    """Register signal handlers for clean shutdown."""
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, lambda: asyncio.create_task(_cancel(loop)))
            logger.info(f"[Section] Signal handler installed for {s}", s)
        except Exception:
            logger.info(f"[Section] Failed to install signal handler for {s}")

async def _cancel(loop):
    """Cancel all tasks and shutdown the loop."""
    logger.info(f"[Section] Cancelling all tasks...")
    for t in asyncio.all_tasks(loop):
        if t.get_name() == "main":
            t.cancel()

# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
def main():
    """Main entry point for the Section Editor service."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install(loop)
    task = loop.create_task(run(), name="main")

    try:
        loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        logger.info(f"[Section] Event loop closed.")

if __name__ == "__main__":
    logger.info(f"Starting the [SectionEditor] Server ....")
    main()