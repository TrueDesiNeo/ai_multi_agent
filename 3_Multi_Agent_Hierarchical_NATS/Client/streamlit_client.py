# =============================================================================
# File: streamlit_client.py
# Description:
#     Streamlit-based A2A client for hierarchical content generation pipeline.
#     Publishes a seed envelope to the ChiefEditor agent and listens for
#     finalized responses on the "demo.done" subject, filtered by conversation_id.
#
# Key Features:
#     - Configurable NATS connection with optional TLS
#     - Publishes root envelope to ChiefEditor via NATS
#     - Subscribes to "done" subject and streams matching results
#     - Displays drafts, scores, and metadata in Streamlit UI
#     - Supports downloading individual or all drafts as markdown/zip
#
# Usage:
#     streamlit run streamlit_client.py
#
# Environment Variables:
#     - NATS_HOST, NATS_PORT, NATS_USER, NATS_PASS
#     - NATS_TLS, NATS_TLS_CAFILE
#     - SUBJ_CHIEF_IN, SUBJ_DONE
#     - CLIENT_IDLE_TIMEOUT_SEC, CLIENT_OVERALL_TIMEOUT_SEC
#     - SERVICE_NAME
#
# Dependencies:
#     - Python 3.10+
#     - streamlit
#     - nats-py
#     - pydantic
#     - python-dotenv
#
# =============================================================================

from __future__ import annotations
import ssl
import json
import time
import uuid
import asyncio
import zipfile
from io import BytesIO
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import streamlit as st
from nats.aio.client import Client as NATS

# Your logging/env utilities
from logging_init import _env, _parse_bool, logger, _parse_float

# ---------------- Utilities & Config -----------------

@dataclass
class Config:
    # NATS connection params (env defaults)
    NATS_HOST: str = _env("NATS_HOST", "127.0.0.1")
    NATS_PORT: str = _env("NATS_PORT", "4222")
    NATS_USER: str = _env("NATS_USER", "")
    NATS_PASS: str = _env("NATS_PASS", "")
    NATS_TLS_ENABLED: bool = _parse_bool(_env("NATS_TLS", "false"))  # default false here
    NATS_TLS_CAFILE: str = _env("NATS_TLS_CAFILE", "")  # optional PEM CA bundle

    # Subjects
    SUBJ_CHIEF_IN: str = _env("SUBJ_CHIEF_IN", "demo.chief.in")
    SUBJ_DONE: str = _env("SUBJ_DONE", "demo.done")

    # Timeouts
    idle_timeout_sec: float = _parse_float(_env("CLIENT_IDLE_TIMEOUT_SEC", "120"), 120.0)
    overall_timeout_sec: float = _parse_float(_env("CLIENT_OVERALL_TIMEOUT_SEC", "120"), 120.0)

    SERVICE_NAME: str = _env("SERVICE_NAME", "client@v1")

    def nats_url(self) -> str:
        return f"nats://{self.NATS_HOST}:{self.NATS_PORT}"

def _build_tls_context(cfg: Config) -> Optional[ssl.SSLContext]:
    """Create and return an SSLContext if TLS is enabled; otherwise None."""
    if not cfg.NATS_TLS_ENABLED:
        return None
    try:
        if cfg.NATS_TLS_CAFILE:
            logger.info(f"Using custom CA file for TLS verification: {cfg.NATS_TLS_CAFILE}")
            ctx = ssl.create_default_context(cafile=cfg.NATS_TLS_CAFILE)
        else:
            ctx = ssl.create_default_context()
        return ctx
    except Exception as exc:
        logger.warning(f"Failed to build TLS context; proceeding without TLS. error={exc}")
        return None

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
    """Minimal A2A-compatible envelope."""
    return {
        "message_id": new_id(),
        "conversation_id": conversation_id or new_id(),
        "sender": sender,
        "target": target,
        "payload": payload,
        "retries": retries,
        "max_retries": max_retries,
    }

def _pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

# ---------------- Async client core (adapted for Streamlit) -----------------

async def run_client_once(
    cfg: Config,
    *,
    area: str,
    max_topics: int = 3,
    max_sections: int = 5,
    max_retries: int = 2,
    style: str = "neutral, SEO-optimized, concise but informative",
    sources: Optional[List[str]] = None,
    research_notes: str = "",
    expected_results: Optional[int] = None,
    # UI callbacks
    on_connected=None,
    on_published=None,
    on_progress=None,
    on_message=None,
    on_done=None,
) -> Dict[str, Any]:
    """
    One-shot async run:
      - Connect to NATS
      - Subscribe to SUBJ_DONE
      - Publish seed envelope to SUBJ_CHIEF_IN
      - Receive until idle/overall timeout or expected_results count
    Calls UI callbacks to stream intermediate updates back to Streamlit.
    Returns a dict with summary stats and last payload.
    """
    nats_url = cfg.nats_url()
    tls_ctx = _build_tls_context(cfg)
    nc = NATS()

    logger.info(f"NATS server {nats_url}")

    # Connect
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
    if on_connected:
        on_connected(nats_url)

    # Prepare envelope
    envelope = make_envelope(
        sender=cfg.SERVICE_NAME,
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

    # Subscribe BEFORE publishing (avoid race)
    done_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    async def _done_cb(msg):
        try:
            raw = msg.data.decode("utf-8")
            data = json.loads(raw)
            # Only enqueue messages for this conversation_id
            if data.get("conversation_id") == conversation_id:
                await done_queue.put(data)
        except Exception as exc:
            logger.error(f"Failed to process done message: {exc}")

    sid = await nc.subscribe(cfg.SUBJ_DONE, cb=_done_cb)

    # Publish seed
    await nc.publish(cfg.SUBJ_CHIEF_IN, json.dumps(envelope).encode("utf-8"))
    if on_published:
        on_published(cfg.SUBJ_CHIEF_IN, conversation_id)

    # Receive
    received = 0
    first_msg_ts: Optional[float] = None
    idle_start = time.monotonic()
    start_ts = time.monotonic()
    last_payload: Dict[str, Any] | None = None

    try:
        while True:
            # Overall timeout
            if (time.monotonic() - start_ts) > cfg.overall_timeout_sec:
                logger.warning(f"Overall timeout reached; stopping conversation_id={conversation_id}")
                break

            # Poll for next message
            try:
                item = await asyncio.wait_for(done_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                elapsed_idle = time.monotonic() - idle_start
                if on_progress:
                    on_progress(
                        received=received,
                        idle_secs=int(elapsed_idle),
                        remaining=int(max(0.0, cfg.idle_timeout_sec - elapsed_idle)),
                    )
                if elapsed_idle > cfg.idle_timeout_sec:
                    logger.info(f"Idle timeout reached; stopping conversation_id={conversation_id}")
                    break
                continue

            # Reset idle timer
            idle_start = time.monotonic()
            received += 1
            if first_msg_ts is None:
                first_msg_ts = time.time()

            payload = item.get("payload", {}) or {}
            last_payload = payload

            # Stream to UI
            if on_message:
                on_message(item)

            # Stop if enough
            if expected_results and received >= expected_results:
                break
    finally:
        try:
            await nc.drain()
        except Exception:
            pass
        try:
            await nc.close()
        except Exception:
            pass

    # Final callback
    if on_done:
        on_done(received)

    return {
        "conversation_id": conversation_id,
        "received": received,
        "first_latency_ms": (
            None if first_msg_ts is None else int((first_msg_ts - start_ts) * 1000)
        ),
        "last_payload": last_payload or {},
    }

# ---------------- Streamlit UI -----------------

st.set_page_config(
    page_title="A2A NATS Client - Streamlit",
    page_icon="🛰️",
    layout="wide",
)

# Optional: mildly tighten secondary buttons (looks nicer for icon buttons)
st.markdown(
    """
    <style>
      .stButton > button[kind="secondary"] {
        padding: 0.25rem 0.5rem;
        line-height: 1.0;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛰️ A2A NATS Client - Streamlit Edition")
st.caption(
    "Publishes a seed envelope to the Chief Editor agent and streams `demo.done` "
    "responses for the matching conversation."
)

# --- Durable state across reruns ---
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None

if "drafts" not in st.session_state:
    # Each item: { "idx": int, "conversation_id": str, "message_id": str, "score": float|None, "draft": str, "payload": dict }
    st.session_state.drafts = []

if "seen_msg_ids" not in st.session_state:
    st.session_state.seen_msg_ids = set()

if "download_btn_counter" not in st.session_state:
    st.session_state.download_btn_counter = 0

# ---- Sidebar: Connection / Subjects / Timeouts ----
with st.sidebar:
    st.header("Connection")

    # Env-driven defaults
    cfg = Config()

    # NATS overrides
    cfg.NATS_HOST = st.text_input("NATS Host", value=cfg.NATS_HOST)
    cfg.NATS_PORT = st.text_input("NATS Port", value=cfg.NATS_PORT)
    cfg.NATS_USER = st.text_input("NATS User (optional)", value=cfg.NATS_USER)
    cfg.NATS_PASS = st.text_input("NATS Password (optional)", value=cfg.NATS_PASS, type="password")

    st.markdown("---")
    st.subheader("TLS")
    cfg.NATS_TLS_ENABLED = st.toggle("Enable TLS", value=cfg.NATS_TLS_ENABLED)
    if cfg.NATS_TLS_ENABLED:
        cfg.NATS_TLS_CAFILE = st.text_input(
            "CA Bundle (PEM) path (optional)", value=cfg.NATS_TLS_CAFILE
        )

    st.markdown("---")
    st.subheader("Subjects")
    cfg.SUBJ_CHIEF_IN = st.text_input("Chief Editor Subject", value=cfg.SUBJ_CHIEF_IN)
    cfg.SUBJ_DONE = st.text_input("Done Subject", value=cfg.SUBJ_DONE)

    st.markdown("---")
    st.subheader("Timeouts")
    cfg.idle_timeout_sec = st.number_input("Idle Timeout (sec)", min_value=5, value=int(cfg.idle_timeout_sec), step=5)
    cfg.overall_timeout_sec = st.number_input("Overall Timeout (sec)", min_value=10, value=int(cfg.overall_timeout_sec), step=10)

    st.markdown("---")
    cfg.SERVICE_NAME = st.text_input("Service Name", value=cfg.SERVICE_NAME)

# ---- Request panel ----
st.header("Request")
col1, col2 = st.columns([2, 1])

with col1:
    area = st.text_input("Area (e.g., 'Edge AI for Robotics')", value="Edge AI for Robotics")
    style = st.text_input(
        "Style",
        value="neutral, SEO-optimized, concise but informative",
        help="High-level style guidance sent to the Chief Editor agent",
    )
    research_notes = st.text_area(
        "Research Notes (optional)",
        height=100,
        help="Free-form hints or constraints",
    )

with col2:
    max_topics = st.number_input("Max Topics", min_value=1, max_value=20, value=3)
    max_sections = st.number_input("Max Sections", min_value=1, max_value=20, value=5)
    max_retries = st.number_input("Max Retries", min_value=0, max_value=10, value=2)
    expected_results = st.number_input(
        "Stop After N Results (0=ignore)", min_value=0, max_value=999, value=0
    )

sources_raw = st.text_area(
    "Sources (one per line, optional)",
    height=100,
    help="Each line is passed as one source string",
)
sources = [s.strip() for s in sources_raw.splitlines() if s.strip()]

# ---- Action row ----
run_col, info_col = st.columns([1, 3])
clear_before = run_col.checkbox("Clear drafts before run", value=False)
start = run_col.button("🚀 Publish & Listen", type="primary")

# ---- Output zones ----
status = st.empty()
meta = st.empty()
log = st.container(border=True)

# -- Callbacks --

def on_connected(nats_url: str):
    status.markdown(f"✅ **Connected** to `{nats_url}`")

def on_published(subject: str, conversation_id: str):
    st.session_state.conversation_id = conversation_id
    meta.info(
        f"Published seed to **{subject}** • Conversation ID: `{conversation_id}`"
    )

def on_progress(received: int, idle_secs: int, remaining: int):
    status.markdown(
        f"📡 Listening… Received: **{received}** • Idle: **{idle_secs}s** "
        f"• Idle timeout in: **{remaining}s**"
    )

def on_message(item: Dict[str, Any]):
    # Log raw message (optional)
    with log:
        st.markdown("**New message:**")
        st.code(_pretty(item), language="json")

    payload = item.get("payload", {}) or {}
    draft = payload.get("draft", "")
    score = payload.get("score", None)
    msg_id = item.get("message_id") or item.get("id") or str(uuid.uuid4())
    conv_id = item.get("conversation_id") or st.session_state.conversation_id

    # De-duplicate (in case broker retries)
    if msg_id in st.session_state.seen_msg_ids:
        return
    st.session_state.seen_msg_ids.add(msg_id)

    # Persist the draft in session_state - this survives reruns
    st.session_state.drafts.append({
        "idx": len(st.session_state.drafts) + 1,  # 1-based numbering
        "conversation_id": conv_id,
        "message_id": msg_id,
        "score": score,
        "draft": draft,
        "payload": payload,
    })

def on_done(received: int):
    status.markdown(f"🏁 Done. Total messages received: **{received}**")

# ---- Start run ----
if start:
    if clear_before:
        st.session_state.drafts = []
        st.session_state.seen_msg_ids = set()

    with st.spinner("Connecting to NATS and publishing seed request…"):
        summary = asyncio.run(
            run_client_once(
                cfg,
                area=area,
                max_topics=int(max_topics),
                max_sections=int(max_sections),
                max_retries=int(max_retries),
                style=style,
                sources=sources,
                research_notes=research_notes,
                expected_results=(int(expected_results) if expected_results > 0 else None),
                on_connected=on_connected,
                on_published=on_published,
                on_progress=on_progress,
                on_message=on_message,
                on_done=on_done,
            )
        )

        # Final meta info
        with meta:
            st.markdown(
                f"""
**Conversation ID:** `{summary['conversation_id']}`  
**Messages Received:** **{summary['received']}**  
**First Message Latency:** **{summary['first_latency_ms']} ms**  
                """
            )

# ---- Drafts Timeline (persists across reruns) ----
hdr_col, zip_col = st.columns([1.0, 0.25])
with hdr_col:
    st.header("Drafts")

with zip_col:
    if st.session_state.drafts:
        # Build zip bytes for all drafts (numbered filenames)
        def _build_drafts_zip_bytes(drafts: List[Dict[str, Any]]) -> bytes:
            bio = BytesIO()
            with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for item in drafts:
                    idx = item["idx"]
                    text = item["draft"]
                    if not text:
                        # If draft text missing, store the raw payload JSON instead
                        text = _pretty(item["payload"])
                    # Use .md so formatting is preserved if content is markdown
                    zf.writestr(f"draft_{idx}.md", text)
            bio.seek(0)
            return bio.getvalue()

        all_zip_bytes = _build_drafts_zip_bytes(st.session_state.drafts)
        # Key includes count so Streamlit rebinds when drafts list changes
        zip_key = f"download_all_zip_{len(st.session_state.drafts)}"

        st.download_button(
            label="⬇️ Download All Drafts (zip)",
            data=all_zip_bytes,
            file_name="drafts.zip",
            mime="application/zip",
            use_container_width=True,
            key=zip_key,
            type="secondary",
        )

if not st.session_state.drafts:
    st.caption("No drafts yet. Click **Publish & Listen** to start streaming.")
else:
    for item in st.session_state.drafts:
        idx = item["idx"]
        draft_text = item["draft"]
        score = item["score"]
        conv_id = item["conversation_id"] or ""
        msg_id = item["message_id"]

        # Row layout: Draft title + small download button on the same row
        title_col, btn_col = st.columns([1.0, 0.12])  # small right column for the button

        with title_col:
            st.subheader(f"Draft #{idx}")
            if score is not None:
                st.caption(f"Score: **{score}**")

        with btn_col:
            if draft_text:
                # Stable key for this specific draft's button
                dl_key = f"dl_{conv_id}_{msg_id}"
                st.download_button(
                    label="💾",                    # compact icon label
                    help="Download this draft",
                    data=draft_text.encode("utf-8"),
                    file_name=f"draft_{idx}.md",
                    mime="text/markdown",
                    use_container_width=False,
                    key=dl_key,
                    type="secondary",
                )

        # The actual draft content (full width below the title row)
        if draft_text:
            st.markdown(draft_text)
        else:
            st.caption("No `draft` field in payload; showing raw payload below.")
            st.code(_pretty(item["payload"]), language="json")

        st.divider()