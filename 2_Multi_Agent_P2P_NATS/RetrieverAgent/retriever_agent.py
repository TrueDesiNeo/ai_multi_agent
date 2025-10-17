#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A2A Researcher Service

- Subscribes to 'demo.research.in' for research tasks.
- Queries Tavily, summarizes the results, and publishes to 'demo.write.in'.
- Supports NATS TLS with optional custom CA.
- Graceful shutdown and robust logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import ssl
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from nats.aio.client import Client as NATS

# Third-party (optional types)
from a2a.utils.errors import ServerError  # type: ignore[import-untyped]
from a2a.types import InvalidParamsError  # type: ignore[import-untyped]

# LangChain Tavily components
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from langchain_community.tools.tavily_search import TavilySearchResults

# -----------------------------------------------------------------------------
# Import project-local modules (Common/a2a_protocol)
# -----------------------------------------------------------------------------
sys.path.append(os.path.abspath(os.path.join("..", "Common", "a2a_protocol")))
from Common.a2a_protocol.common_envelope import A2AEnvelope  # type: ignore[attr-defined]

# -----------------------------------------------------------------------------
# Constants & Subjects
# -----------------------------------------------------------------------------
SERVICE_NAME = "researcher@v1"
WRITE_IN_SUBJECT = "demo.write.in"
RESEARCH_IN_SUBJECT = "demo.research.in"

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

def _parse_int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default

def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)

# Configure logging (UTC timestamps)
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=DATE_FORMAT)
logging.Formatter.converter = lambda *args: __import__("time").gmtime(*args)  # UTC
logger = logging.getLogger("retriever_a2a")

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
# Tavily Configuration
# -----------------------------------------------------------------------------
tavily_api_key: Optional[str] = _env("TAVILY_API_KEY")
tavily_api_url: Optional[str] = _env("TAVILY_API_URL")  # e.g., "https://api.tavily.com"
retriever_top_k: int = _parse_int(_env("RETRIEVER_TOP_K"), 5)
retriever_search_depth: str = _env("RETRIEVER_SEARCH_DEPTH", "basic")  # "basic" | "advanced"

tavily_include_answer: bool = _parse_bool(_env("TAVILY_INCLUDE_ANSWER", "false"))
tavily_include_raw: bool = _parse_bool(_env("TAVILY_INCLUDE_RAW_CONTENT", "false"))
tavily_include_images: bool = _parse_bool(_env("TAVILY_INCLUDE_IMAGES", "false"))

SNIPPET_MAX_CHARS: int = _parse_int(_env("RETRIEVER_SNIPPET_MAX_CHARS"), 600)

# If true, use verify=False with requests (INSECURE); otherwise use verified TLS.
TAVILY_INSECURE_SKIP_VERIFY: bool = _parse_bool(_env("TAVILY_INSECURE_SKIP_VERIFY", "false"))
TAVILY_TIMEOUT_SECONDS: int = _parse_int(_env("TAVILY_TIMEOUT_SECONDS"), 60)

# -----------------------------------------------------------------------------
# Custom Tavily Wrapper (optional insecure mode)
# -----------------------------------------------------------------------------
class InsecureTavilyAPIWrapper(TavilySearchAPIWrapper):
    """
    A thin subclass that calls Tavily with certificate verification disabled.
    WARNING: This is insecure and should only be used in trusted environments.
    """

    def raw_results(
        self,
        query: str,
        max_results: Optional[int] = 5,
        search_depth: Optional[str] = "basic",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        include_answer: Optional[bool] = False,
        include_raw_content: Optional[bool] = False,
        include_images: Optional[bool] = False,
    ) -> Dict[str, Any]:
        include_domains = include_domains or []
        exclude_domains = exclude_domains or []

        # LangChain may store the key as SecretStr or str-support both.
        key = (
            self.tavily_api_key.get_secret_value()  # type: ignore[attr-defined]
            if hasattr(self.tavily_api_key, "get_secret_value")
            else self.tavily_api_key
        )

        if not key:
            raise ValueError("Tavily API key is missing.")
        if not tavily_api_url:
            raise ValueError("TAVILY_API_URL is not set.")

        params = {
            "api_key": key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images,
        }

        logger.debug(
            "Tavily raw_results params: query_len=%d, max_results=%s, depth=%s, "
            "include_answer=%s, include_raw=%s, include_images=%s",
            len(query),
            max_results,
            search_depth,
            include_answer,
            include_raw_content,
            include_images,
        )

        # INTENTIONALLY insecure TLS. Log a warning so this is obvious.
        logger.warning(
            "Using insecure HTTP (verify=False) for Tavily request - NOT for production use."
        )

        t0 = time.perf_counter()
        try:
            resp = requests.post(
                f"{tavily_api_url}/search",
                json=params,
                verify=False,
                timeout=TAVILY_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            logger.exception("Tavily request failed after %.1f ms | error=%s", dt_ms, exc)
            raise
        dt_ms = (time.perf_counter() - t0) * 1000.0
        logger.info("Tavily search completed in %.1f ms", dt_ms)
        return resp.json()

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def summarize(results: List[Dict[str, Any]], char_limit: int = 700) -> Tuple[str, List[str]]:
    """
    Convert raw Tavily results into concise notes and a list of source URLs.
    """
    bullets: List[str] = []
    urls: List[str] = []
    for r in results[:5]:
        title = (r.get("title") or "").strip()
        text = (
            r.get("content")
            or r.get("snippet")
            or r.get("text")
            or ""
        )
        url = (r.get("url") or "").strip()
        if text:
            prefix = f"{title}: " if title else ""
            bullets.append(f"- {prefix}{text.strip()}")
        if url:
            urls.append(url)

    notes = "\n".join(bullets)
    if len(notes) > char_limit:
        notes = notes[:char_limit] + "…"
    return notes, urls

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
    Handler for messages on RESEARCH_IN_SUBJECT.
    - Validates env for Tavily.
    - Runs search (secure or insecure mode).
    - Summarizes and publishes to WRITE_IN_SUBJECT.
    """
    try:
        raw = msg.data.decode("utf-8")
    except Exception:
        logger.error("Received non-UTF-8 message; dropping.")
        return

    correlation = None
    try:
        data: Dict[str, Any] = json.loads(raw)
        env = A2AEnvelope(**data)  # type: ignore[call-arg]
        correlation = getattr(env, "conversation_id", None)
        payload: Dict[str, Any] = env.payload or {}
        task: str = payload.get("task", "") or ""

        logger.info(
            "[Researcher] Searching | conversation_id=%s | retry=%s | query_len=%d",
            correlation,
            getattr(env, "retries", 0),
            len(task),
        )

        # Validate required config
        if not tavily_api_key:
            raise ServerError(error=InvalidParamsError(message="TAVILY_API_KEY not set"))  # type: ignore[misc]
        if not tavily_api_url:
            raise ServerError(error=InvalidParamsError(message="TAVILY_API_URL not set"))  # type: ignore[misc]

        # Cap results for safety; ensure >= 1
        k = max(1, retriever_top_k)

        # Choose wrapper: secure by default; insecure only if explicitly allowed
        if TAVILY_INSECURE_SKIP_VERIFY:
            wrapper = InsecureTavilyAPIWrapper(tavily_api_key=tavily_api_key)
        else:
            # Standard wrapper will use Tavily's Python client semantics via LangChain
            wrapper = TavilySearchAPIWrapper(tavily_api_key=tavily_api_key)

        # Prefer calling raw_results for full control of parameters.
        # If the standard wrapper does not implement raw_results fully,
        # it will still work with defaults; otherwise we fall back to the tool.
        results_list: List[Dict[str, Any]] = []
        try:
            api_resp = wrapper.raw_results(  # type: ignore[attr-defined]
                query=task,
                max_results=k,
                search_depth=retriever_search_depth,
                include_answer=tavily_include_answer,
                include_raw_content=tavily_include_raw,
                include_images=tavily_include_images,
            )
            # Tavily returns {"results": [...], "answer": "...", ...}
            if isinstance(api_resp, dict) and "results" in api_resp:
                results_list = list(api_resp.get("results") or [])
            elif isinstance(api_resp, list):
                results_list = api_resp
        except AttributeError:
            # Fallback to LangChain tool if raw_results isn't available
            tool = TavilySearchResults(api_wrapper=wrapper, max_results=k)
            tool_results = tool.invoke(task)
            results_list = tool_results if isinstance(tool_results, list) else []

        # Fallback if empty or errors occurred
        if not isinstance(results_list, list):
            results_list = []
        if not results_list:
            logger.warning("Tavily returned no results; using stub fallback.")
            results_list = [
                {
                    "title": "P2P overview",
                    "content": "Agents collaborate via direct message passing and auctions.",
                    "url": "",
                }
            ]

        notes, sources = summarize(results_list, char_limit=SNIPPET_MAX_CHARS)

        out_payload = {
            "role": "researcher",
            "task": task,
            "research_notes": notes,
            "sources": sources,
        }
        out = env.child(sender=SERVICE_NAME, target="writer@v1", payload=out_payload)

        await nc.publish(WRITE_IN_SUBJECT, json.dumps(out.model_dump()).encode("utf-8"))
        logger.info(
            "[Researcher] Published research to writer | conversation_id=%s | sources=%d",
            correlation,
            len(sources),
        )

    except (ServerError, InvalidParamsError) as exc:  # type: ignore[misc]
        logger.exception(
            "Config error | subject=%s | conversation_id=%s | error=%s",
            getattr(msg, "subject", "?"),
            correlation,
            exc,
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

# -----------------------------------------------------------------------------
# Main Service Loop
# -----------------------------------------------------------------------------
async def run() -> None:
    """
    Connect to NATS, subscribe to RESEARCH_IN_SUBJECT with a coroutine callback,
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error connecting to NATS: %s", exc)
        raise

    # IMPORTANT: NATS requires a coroutine function for the subscription callback
    async def _subscription_cb(msg) -> None:
        await _message_handler(nc, msg)

    sid = await nc.subscribe(RESEARCH_IN_SUBJECT, cb=_subscription_cb)
    logger.info("[Researcher] Subscribed to '%s' | sid=%s", RESEARCH_IN_SUBJECT, sid)

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
