# =============================================================================
# File: verify_service.py
# Description:
#     NATS-backed Verifier microservice that:
#       - Listens on a NATS subject for A2A envelopes from the Writer,
#       - Scores the draft via LLM (with heuristic fallback),
#       - Requests a revision when score is below threshold and retries remain,
#       - Or finalizes and publishes the approved draft to the client subject.
#
# Key Features:
#     - TLS support for NATS connections (optional custom CA)
#     - Graceful shutdown via SIGINT/SIGTERM
#     - Structured logging throughout the lifecycle
#     - A2A envelope trace/context propagation across services
#
# Subjects:
#     - Input:  demo.verify.in
#     - Output (revision): demo.write.in
#     - Output (final):    demo.done
#
# Environment Variables:
#     - NATS_HOST              (default: 127.0.0.1)
#     - NATS_PORT              (default: 4222)
#     - NATS_USER              (default: "")
#     - NATS_PASS              (default: "")
#     - NATS_TLS               (default: "true")
#     - NATS_TLS_CAFILE        (default: None)  # path to custom CA bundle (PEM)
#     - MIN_ACCEPTABLE_SCORE   (default: 7.0)
#
# Dependencies:
#     - Python 3.10+
#     - nats-py (nats.aio)
#     - pydantic (A2AEnvelope)
#     - Local modules: common_envelope, llm_openai (score_with_llm), logging_init
#
# =============================================================================

import asyncio
import json
import ssl
import signal
from typing import Optional, Any, List

from nats.aio.client import Client as NATS
from common_envelope import A2AEnvelope
from llm_openai import score_with_llm
from logging_init import _env, _parse_bool, logger, _parse_float

# -----------------------------------------------------------------------------
# NATS Configuration
# -----------------------------------------------------------------------------
# Fetch NATS connection details and verifier settings from environment variables.
NATS_HOST = _env("NATS_HOST", "127.0.0.1")
NATS_PORT = _env("NATS_PORT", "4222")
NATS_USER = _env("NATS_USER", "")
NATS_PASS = _env("NATS_PASS", "")
NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))  # Enable TLS by default
NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")  # Optional custom CA bundle (PEM)
MIN_ACCEPTABLE_SCORE = _parse_float(_env("MIN_ACCEPTABLE_SCORE", "7.0"), 7.0)

# -----------------------------------------------------------------------------
# Service Configuration
# -----------------------------------------------------------------------------
SERVICE_NAME = "verifier@v1"
VERIFY_IN_SUBJECT = "demo.verify.in"
WRITE_IN_SUBJECT = "demo.write.in"
DONE_SUBJECT = "demo.done"

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
# Message Handler
# -----------------------------------------------------------------------------
async def _handle(nc: NATS, msg) -> None:
    """
    Handle incoming messages for Verifier service.
    Decodes message, scores draft using LLM, and decides whether to request revision or finalize.
    """
    cid = None
    try:
        # Decode and parse incoming message
        raw = msg.data.decode("utf-8")
        data: dict[str, Any] = json.loads(raw)
        env = A2AEnvelope(**data)  # type: ignore[call-arg]
        cid = getattr(env, "conversation_id", None)
        p: dict[str, Any] = env.payload or {}

        # Extract payload details
        draft: str = p.get("draft", "") or ""
        sources: List[str] = p.get("sources", []) or []
        notes: str = p.get("research_notes", "") or ""
        task: str = p.get("task", "") or ""
        retries = getattr(env, "retries", 0)
        max_retries = getattr(env, "max_retries", 0)

        logger.info(f"[Verifier] Received message: conversation_id={cid}, retries={retries}, draft_len={len(draft)}, sources={len(sources)}")

        # Score draft using LLM
        score, fb = score_with_llm(draft, sources, notes)
        logger.info(f"[Verifier] Scored draft: conversation_id={cid}, score={score}, retries={retries}")

        # Decide whether to request revision or finalize
        if score < MIN_ACCEPTABLE_SCORE and retries < max_retries:
            # Request revision from Writer
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
            logger.info(f"[Verifier] Requested revision: conversation_id={cid}, next_retry={retries + 1}")
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
            await nc.publish(DONE_SUBJECT, out.model_dump_json().encode("utf-8"))
            logger.info(f"[Verifier] Finalized draft: conversation_id={cid}, score={score}")

    except json.JSONDecodeError:
        logger.info(f"[Verifier] Invalid JSON received; dropping message on subject={getattr(msg, 'subject', '?')}")
    except Exception as exc:
        logger.info(f"[Verifier] Handler failure subject={getattr(msg, 'subject', '?')} conversation_id={cid} error={exc}")

# -----------------------------------------------------------------------------
# Main Service Runner
# -----------------------------------------------------------------------------
async def run() -> None:
    """
    Connect to NATS, subscribe to Verifier subject, and keep the service alive.
    """
    url = f"nats://{NATS_HOST}:{NATS_PORT}"
    tls = _build_tls_context()
    nc = NATS()

    logger.info(f"[Verifier] Connecting to NATS at {url}")
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
    logger.info(f"[Verifier] Connected to NATS at {url}")

    # Subscribe to Verifier input subject
    async def _cb(msg): await _handle(nc, msg)
    await nc.subscribe(VERIFY_IN_SUBJECT, cb=_cb)
    logger.info(f"[Verifier] Subscribed to subject={VERIFY_IN_SUBJECT}")

    # Keep service running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info(f"[Verifier] Shutdown signal received.")
    finally:
        try:
            await nc.drain()
            await nc.close()
            logger.info(f"[Verifier] NATS connection closed.")
        except Exception:
            logger.info(f"[Verifier] Error occurred while closing NATS connection.")

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
            logger.info(f"[Verifier] Signal handler installed for {s}")
        except Exception:
            logger.info(f"[Verifier] Failed to install signal handler for {s}")

async def _cancel(loop):
    """
    Cancel all tasks and shutdown the loop.
    """
    logger.info(f"[Verifier] Cancelling all tasks...")
    for t in asyncio.all_tasks(loop):
        if t.get_name() == "main":
            t.cancel()

# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
def main():
    """
    Main entry point for the Verifier service.
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
        logger.info(f"[Verifier] Event loop closed.")

if __name__ == "__main__":
    logger.info(f"Starting the [Verifier] Server ....")
    main()