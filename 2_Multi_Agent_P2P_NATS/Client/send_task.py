#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demo Client

- Connects to NATS, publishes a task to 'demo.research.in',
  and waits for the final response on 'demo.done'.
- Matches responses by conversation_id for correctness.
- Supports TLS (optional) and configurable timeouts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import ssl
import sys
from typing import Any, Optional

from dotenv import load_dotenv
from nats.aio.client import Client as NATS

# -----------------------------------------------------------------------------
# Make Common module importable
# -----------------------------------------------------------------------------
sys.path.append(os.path.abspath(os.path.join("..", "Common", "a2a_protocol")))
from Common.a2a_protocol.common_envelope import (  # type: ignore[attr-defined]
    A2AEnvelope,
    new_root_envelope,
)

# -----------------------------------------------------------------------------
# Subjects & Constants
# -----------------------------------------------------------------------------
SERVICE_NAME = "client@v1"
RESEARCH_IN_SUBJECT = "demo.research.in"
DONE_SUBJECT = "demo.done"

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# -----------------------------------------------------------------------------
# Environment & Logging
# -----------------------------------------------------------------------------
load_dotenv()

def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse boolean-like string envs safely."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _parse_int(value: Optional[str], default: int) -> int:
    """Parse integer envs safely with fallback."""
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default

def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Env getter with default."""
    return os.getenv(key, default)

# Configure logging (UTC timestamps)
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=DATE_FORMAT)
logging.Formatter.converter = lambda *args: __import__("time").gmtime(*args)  # UTC
logger = logging.getLogger("demo_client")

# -----------------------------------------------------------------------------
# NATS Configuration
# -----------------------------------------------------------------------------
NATS_HOST = _env("NATS_HOST", "127.0.0.1")
NATS_PORT = _env("NATS_PORT", "4222")
NATS_USER = _env("NATS_USER", "")
NATS_PASS = _env("NATS_PASS", "")

# TLS options (verification ON by default; provide CA if needed)
NATS_TLS_ENABLED = _parse_bool(_env("NATS_TLS", "true"))
NATS_TLS_CAFILE = _env("NATS_TLS_CAFILE")  # optional PEM path

# -----------------------------------------------------------------------------
# Client Configuration
# -----------------------------------------------------------------------------
RESPONSE_TIMEOUT_SECONDS = _parse_int(_env("CLIENT_RESPONSE_TIMEOUT_SECONDS"), 120)
MAX_WAIT_MESSAGES = _parse_int(_env("CLIENT_MAX_WAIT_MESSAGES"), 200)  # safety valve

def _build_tls_context() -> Optional[ssl.SSLContext]:
    """
    Create an SSLContext if TLS is enabled; otherwise None.
    Verification remains ON. Provide a custom CA via NATS_TLS_CAFILE for internal CAs.
    """
    if not NATS_TLS_ENABLED:
        logger.info("TLS is disabled for NATS connection.")
        return None
    try:
        if NATS_TLS_CAFILE:
            logger.info("Using custom CA for TLS verification: %s", NATS_TLS_CAFILE)
            return ssl.create_default_context(cafile=NATS_TLS_CAFILE)
        return ssl.create_default_context()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build TLS context; disabling TLS. error=%s", exc)
        return None

async def main(task: str) -> None:
    """
    Connect to NATS, publish a task message, and wait for the final response
    that matches the conversation_id.

    Parameters
    ----------
    task : str
        The task/prompt to send to the demo researcher.
    """
    nc = NATS()
    nat_url = f"nats://{NATS_HOST}:{NATS_PORT}"
    tls_ctx = _build_tls_context()

    logger.info(
        "Connecting to NATS | url=%s | tls=%s | user=%s",
        nat_url,
        bool(tls_ctx),
        "set" if NATS_USER else "none",
    )

    # Establish connection
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

    # Create a root envelope for the task targeting the researcher
    env = new_root_envelope(task, to_role="researcher", max_retries=2)
    payload_bytes = json.dumps(env.model_dump()).encode("utf-8")

    # Publish the task
    logger.info(
        "Publishing task to '%s' | conversation_id=%s",
        RESEARCH_IN_SUBJECT,
        env.conversation_id,
    )
    await nc.publish(RESEARCH_IN_SUBJECT, payload_bytes)
    # Ensure the server processed the publish
    await nc.flush(timeout=2)

    # Subscribe to final results (pull-based subscription, no callback)
    logger.info("Subscribing for responses on '%s'…", DONE_SUBJECT)
    sub = await nc.subscribe(DONE_SUBJECT)

    # Process messages until we receive our matching conversation or timeout
    matched = False
    messages_checked = 0

    try:
        while messages_checked < MAX_WAIT_MESSAGES:
            messages_checked += 1
            logger.info(
                "Waiting for response message %d/%d (timeout=%ds)…",
                messages_checked,
                MAX_WAIT_MESSAGES,
                RESPONSE_TIMEOUT_SECONDS,
            )

            msg = await sub.next_msg(timeout=RESPONSE_TIMEOUT_SECONDS)
            raw = msg.data.decode("utf-8", errors="replace")

            try:
                data: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON message on '%s'; skipping.", DONE_SUBJECT)
                continue

            # Correlation check: ensure response belongs to our request
            msg_cid = data.get("conversation_id")
            if msg_cid != env.conversation_id:
                logger.debug(
                    "Received message for different conversation_id=%s; expecting=%s. Skipping.",
                    msg_cid,
                    env.conversation_id,
                )
                continue

            # (Optional) Validate via schema
            try:
                final_env = A2AEnvelope(**data)  # type: ignore[call-arg]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Envelope validation failed for conversation_id=%s: %s",
                    msg_cid,
                    exc,
                )
                final_env = None  # fall back to raw dict

            payload = (final_env.payload if final_env else data.get("payload")) or {}
            draft = payload.get("draft", "<no draft>")
            score = payload.get("score")
            sources = payload.get("sources", [])

            logger.info("Matched final response | conversation_id=%s", env.conversation_id)

            # Present result (simple client UX)
            print("\n=== FINAL ANSWER ===")
            print(draft)
            print("\nScore:", score, "\nSources:", sources)
            matched = True
            break

        if not matched:
            logger.error(
                "Did not receive a matching response after %d messages or within timeout.",
                messages_checked,
            )

    except asyncio.TimeoutError:
        logger.error(
            "Timeout waiting for response; no message received within %ds.",
            RESPONSE_TIMEOUT_SECONDS,
        )
    finally:
        # Drain ensures pending messages are processed prior to close
        logger.info("Draining NATS connection…")
        try:
            await nc.drain()
            await nc.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error while closing NATS: %s", exc)
        logger.info("NATS connection closed.")

def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the demo client."""
    parser = argparse.ArgumentParser(
        description="Demo Client: publish a task and await the final response."
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Explain the role of sports in children's development.",
        help="Task text to send to the researcher.",
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = _parse_args()
    logger.info("Starting client with task: %s", args.task)
    asyncio.run(main(args.task))