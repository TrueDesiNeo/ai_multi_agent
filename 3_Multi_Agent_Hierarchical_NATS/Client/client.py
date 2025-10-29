# =============================================================================
# File: client.py
# Description:
#     Lightweight A2A client that:
#       - Connects to NATS (with optional TLS),
#       - Publishes a root request to the ChiefEditor subject,
#       - Listens for final "done" messages filtered by conversation_id,
#       - Streams results to logs until idle/overall timeout or expected count.
#
# Key Features:
#     - Environment-driven config via `Config` dataclass
#     - TLS support with optional custom CA bundle (PEM)
#     - Minimal A2A-compatible envelope
#     - Clean shutdown via signal handlers
#
# Usage:
#     python a2a_client.py 
#           --area "AI in Climate Modeling" 
#           --max-topics 2 
#           --max-sections 4 
#           --style "technical, SEO-aware, concise" 
#           --sources "IPCC 2023" "NASA EarthData" 
#           --research-notes "Focus on real-time inference and satellite data fusion." 
#           --expected-results 8
#
# Environment Variables:
#     - NATS_HOST (default: 127.0.0.1)
#     - NATS_PORT (default: 4222)
#     - NATS_USER (default: "")
#     - NATS_PASS (default: "")
#     - NATS_TLS  (default: "true")
#     - NATS_TLS_CAFILE (default: None)  # path to PEM bundle for custom CA
#     - CLIENT_IDLE_TIMEOUT_SEC (default: 120)
#     - CLIENT_OVERALL_TIMEOUT_SEC (default: 120)
#
# Dependencies:
#     - Python 3.10+
#     - nats-py (nats.aio)
#     - python-dotenv (via logging_init)
#     - Your local modules: logging_init
# =============================================================================

from __future__ import annotations
import asyncio
import json
import signal
import ssl
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
from logging_init import _env, _parse_bool, logger, _parse_float
# NATS client
from nats.aio.client import Client as NATS

# -----------------------------------------------------------------------------
# NATS Configuration
# -----------------------------------------------------------------------------
@dataclass
class Config:
    # NATS
    NATS_HOST = _env("NATS_HOST", "127.0.0.1")
    NATS_PORT = _env("NATS_PORT", "4222")
    NATS_USER = _env("NATS_USER", "")
    NATS_PASS = _env("NATS_PASS", "")
    NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))  # default to TLS on
    NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")  # optional custom CA bundle (PEM)    

    # Subjects
    SUBJ_CHIEF_IN = "demo.chief.in"
    SUBJ_DONE = "demo.done"

    # Client behavior
    idle_timeout_sec: float = _parse_float(_env("CLIENT_IDLE_TIMEOUT_SEC", "120"), 120.0)
    overall_timeout_sec: float = _parse_float(_env("CLIENT_OVERALL_TIMEOUT_SEC", "120"), 120.0)

    SERVICE_NAME = "client@v1"

# -----------------------------------------------------------------------------
# NATS Helpers
# -----------------------------------------------------------------------------
def _build_tls_context(cfg: Config) -> Optional[ssl.SSLContext]:
    """Create and return an SSLContext if TLS is enabled; otherwise None."""
    if not cfg.NATS_TLS_ENABLED:
        logger.info("TLS is disabled for NATS connection.")
        return None
    try:
        if Config.NATS_TLS_CAFILE:
            cfg.info(f"Using custom CA file for TLS verification:  {cfg.NATS_TLS_CAFILE}")
            ctx = ssl.create_default_context(cafile=cfg.NATS_TLS_CAFILE)
        else:
            ctx = ssl.create_default_context()
        return ctx
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build TLS context; disabling TLS. error=%s", exc)
        return None

# -----------------------------
# A2A Envelope (compatible)
# -----------------------------
def new_id() -> str:
    return str(uuid.uuid4())

def make_envelope(
    sender: str,
    target: str,
    payload: Dict[str, Any],
    conversation_id: Optional[str] = None,
    retries: int = 0,
    max_retries: int = 0,
) -> Dict[str, Any]:
    """
    Minimal A2A-compatible envelope (aligned with your reference services).
    """
    return {
        "message_id": new_id(),
        "conversation_id": conversation_id or new_id(),
        "sender": sender,
        "target": target,
        "payload": payload,
        "retries": retries,
        "max_retries": max_retries,
    }

# -----------------------------
# Client core
# -----------------------------
async def run_client(
    area: str,
    max_topics: int = 3,
    max_sections: int = 5,
    max_retries: int = 2,
    style: str = "neutral, SEO-optimized, concise but informative",
    sources: Optional[List[str]] = None,
    research_notes: str = "",
    expected_results: Optional[int] = None,
) -> None:
    cfg = Config()
    nats_url = f"nats://{cfg.NATS_HOST}:{cfg.NATS_PORT}"
    tls_ctx = _build_tls_context(cfg)

    nc = NATS()

    # Connect
    logger.info(f"Connecting to NATS... url={nats_url}, tls={bool(tls_ctx)}")
    await nc.connect(
        servers=[nats_url],
        user=cfg.NATS_USER or None,
        password=cfg.NATS_PASS or None,
        tls=tls_ctx,
        connect_timeout=10,
        reconnect_time_wait=2,
        max_reconnect_attempts=3,
        allow_reconnect=True,
        name=cfg.SERVICE_NAME,
    )
    logger.info(f"Connected to NATS url={nats_url}")

    # Prepare envelope
    envelope = make_envelope(
        sender="client@v1",
        target="chief@v1",
        payload={
            "area": area,
            "max_topics": max_topics,
            "max_sections": max_sections,
            "style": style,
            "sources": sources or [],
            "research_notes": research_notes,
            "max_retries": max_retries,
        },
    )
    conversation_id = envelope["conversation_id"]
    logger.info(f"Publishing seed request to Chief subject={cfg.SUBJ_CHIEF_IN}, conversation_id={conversation_id}")

    # Subscribe BEFORE publishing (avoid race on fast workers)
    done_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    async def _done_cb(msg):
        try:
            raw = msg.data.decode("utf-8")
            data = json.loads(raw)
            # Filter by the conversation_id we started
            if data.get("conversation_id") == conversation_id:
                await done_queue.put(data)
        except Exception as exc:
            logger.error(f"Failed to process done message error={str(exc)}")

    sid = await nc.subscribe(cfg.SUBJ_DONE, cb=_done_cb)
    logger.info(f"Subscribed to done subject subject={cfg.SUBJ_DONE}, sid={sid}")

    # Publish seed event
    await nc.publish(cfg.SUBJ_CHIEF_IN, json.dumps(envelope).encode("utf-8"))

    # Collect results until idle timeout or expected count reached
    received = 0
    first_msg_ts = None
    idle_start = time.monotonic()
    start_ts = time.monotonic()

    logger.info(f"Waiting for results... conversation_id={conversation_id}, idle_timeout_sec={cfg.idle_timeout_sec}")

    try:
        while True:
            # overall timeout
            if (time.monotonic() - start_ts) > cfg.overall_timeout_sec:
               logger.warn(f"Overall timeout reached; stopping conversation_id={conversation_id}")
               break

            try:
                item = await asyncio.wait_for(done_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # idle check
                if (time.monotonic() - idle_start) > cfg.idle_timeout_sec:
                    logger.info(f"Idle timeout reached; stopping conversation_id={conversation_id}")
                    break
                continue

            # reset idle timer
            idle_start = time.monotonic()
            received += 1
            if first_msg_ts is None:
                first_msg_ts = time.time()

            # Display the response nicely
            payload = item.get("payload", {})
            score = payload.get("score")
            draft = payload.get("draft", "")
            conv_id = item.get("conversation_id", {})
            msg_id = item.get("message_id", {})
            draft_preview = draft
            logger.info(
                f"Received final content conversation_id=item.{conv_id}, message_id=item.{msg_id},score={score},draft_preview={draft_preview}")

            # If you know how many to expect, exit early
            if expected_results and received >= expected_results:
                logger.info(f"Reached expected result count; stopping expected_results={expected_results}")
                break

    finally:
        try:
            await nc.drain()
            await nc.close()
        except Exception:
            pass

    logger.info(f"Client finished conversation_id={conversation_id}, results={received}")

# -----------------------------
# CLI & Entrypoint
# -----------------------------
def _install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _cancel_main():
        for t in asyncio.all_tasks(loop):
            if t.get_name() == "client-main":
                t.cancel()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _cancel_main)
        except NotImplementedError:
            pass  # e.g., Windows in some contexts

def main():
    import argparse
    p = argparse.ArgumentParser(description="A2A Client: publish request and display responses.")
    p.add_argument("--area", required=True, help='High-level area (e.g., "Edge AI for Robotics")')
    p.add_argument("--max-topics", type=int, default=3)
    p.add_argument("--max-sections", type=int, default=5)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--style", default="neutral, SEO-optimized, concise but informative")
    p.add_argument("--sources", nargs="*", default=[])
    p.add_argument("--research-notes", default="")
    p.add_argument("--expected-results", type=int, default=None, help="Stop after receiving this many final messages.")
    args = p.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    task = loop.create_task(
        run_client(
            area=args.area,
            max_topics=args.max_topics,
            max_sections=args.max_sections,
            max_retries=args.max_retries,
            style=args.style,
            sources=args.sources,
            research_notes=args.research_notes,
            expected_results=args.expected_results,
        ),
        name="client-main",
    )
    try:
        loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

if __name__ == "__main__":
    main()
    