#!/usr/bin/env python3
# ui_streamlit.py
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List
import streamlit as st

# Import your existing graph builder and config
from workflow import build_graph, prepare_initial_state

recursion_limit = 25

# --------------------------
# Streamlit page config
# --------------------------
st.set_page_config(
    page_title="Multi-Agent Coordinator UI",
    page_icon="🤝",
    layout="wide",
)

# --------------------------
# Logging Configuration
# --------------------------
# Initialize UI logger following industry agent standards
# - Uses standard library logging module
# - Named logger for component-specific logging
# - Configured with StreamHandler for console output
# - Formatter includes timestamp, logger name, level, and message
logger = logging.getLogger("ui")
logger.setLevel(logging.INFO)

# Create console handler with formatter
handler = logging.StreamHandler()
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
handler.setFormatter(formatter)

# Add handler to logger
logger.addHandler(handler)

# --------------------------
# Helpers
# --------------------------
def _merge_state(base: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge a LangGraph update delta into a running 'current_state'.
    Special-case 'messages' to append (because of add_messages reducer).
    """
    merged = dict(base)
    for k, v in delta.items():
        if k == "messages":
            # Ensure list exists, then extend
            merged.setdefault("messages", [])
            if isinstance(v, list):
                merged["messages"].extend(v)
        else:
            merged[k] = v
    return merged

def _render_messages(messages: List[Any]) -> None:
    """
    Render LangChain-style messages if present.
    """
    for m in messages:
        role = getattr(m, "type", "assistant")
        content = getattr(m, "content", "")
        if role == "human":
            with st.chat_message("user", avatar="👤"):
                st.write(content)
        else:
            with st.chat_message("assistant", avatar="🤖"):
                st.write(content)

def _render_node_update(node_name: str, update: Dict[str, Any]) -> None:
    """
    Pretty-print each node's delta update.
    """
    with st.container():
        st.markdown(f"### ▶️ **{node_name.title()}**")
        # Show key fields with formatting
        if "search_snippets" in update and update["search_snippets"] and len(update["search_snippets"]) > 0:
            with st.expander("Search Snippets", expanded=False):
                st.markdown(update["search_snippets"])
        
        if "draft" in update and update["draft"]:
            with st.expander("Draft", expanded=True):
                st.markdown(update["draft"])
        
        if "verification" in update and update["verification"]:
            vr = update["verification"]
            col1, col2 = st.columns([1, 3])
            with col1:
                st.metric("Rating", value=str(vr.get("rating", "N/A")))
                st.metric("Safe", value=str(vr.get("safe", "N/A")))
            with col2:
                st.markdown("**Feedback**")
                st.write(vr.get("feedback", ""))
        
        # Dump any other keys that arrived in this update
        other = {
            k: v
            for k, v in update.items()
            if k not in {"messages", "search_snippets", "draft", "verification"}
        }
        if other:
            with st.expander("Other Update Fields", expanded=False):
                st.json(other)

# --------------------------
# Main Application Logic
# --------------------------
reset = st.button("Reset Session", type="secondary")
# Reset session state if requested
if reset:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# --------------------------
# Title & Input
# --------------------------
st.title("🤝 Coordinator → Retriever → Writer → Verifier")
st.caption("Enter a task/question below. The graph will stream node-by-node outputs and stop when the draft is accepted or attempts are exhausted.")

user_query = st.text_area(
    "Task / Issue",
    placeholder="e.g., 'How can I mitigate CVE-2024-3094 on Ubuntu 22.04 servers?'",
    height=120,
)

run_button = st.button("Run Agents", type="primary", use_container_width=True)

# --------------------------
# Build graph once per session
# --------------------------
if "graph" not in st.session_state:
    try:
        st.session_state.graph = build_graph()
    except Exception as e:
        st.error(f"Failed to build graph: {e}")
        st.stop()

# --------------------------
# Main Run
# --------------------------
if run_button:
    if not user_query.strip():
        st.warning("Please enter a task or question.")
        st.stop()

    # Prepare initial state
    state = prepare_initial_state(user_query)
    logger.info(f"User initiated run with query: {user_query}")
    # Hold the current merged state to display a 'final answer' at the end
    current_state: Dict[str, Any] = copy.deepcopy(state)
    st.subheader("📡 Live Agent Flow")

    # Two columns: left (events), right (final view)
    left_col, right_col = st.columns([2, 1], gap="large")

    with left_col:
        event_area = st.container()
        debug_expander = st.expander("🔎 Raw stream events (debug)", expanded=False)

        try:
            with st.spinner("Running the multi-agent graph..."):
                stream = st.session_state.graph.stream(
                    state, config={"recursion_limit": recursion_limit}, stream_mode="updates"
                )
                logger.info("Agent graph stream initialized successfully")
                for step in stream:
                    # Be defensive: some steps may be None or non-dicts
                    if not step or not isinstance(step, dict):
                        with debug_expander:
                            st.write("Non-dict/empty step:", step)
                        continue
                    for node_name, node_update in step.items():
                        if node_name == "__end__":
                            with debug_expander:
                                st.write("__end__ received.")
                            continue
                        node_update = node_update or {}
                        current_state = _merge_state(current_state, node_update)
                        logger.debug(f"Processing update from {node_name}: {node_update}")
                        with event_area:
                            st.markdown("---")
                            _render_node_update(node_name, node_update)
                        with debug_expander:
                            st.json({node_name: node_update})
        except Exception as e:
            logger.error(f"Error during agent execution: {str(e)}", exc_info=True)
            st.error(f"❌ Error during run: {e}")
            st.stop()
        finally:
            logger.info("Agent graph execution completed")

    # Final Answer & Transcript
    with right_col:
        st.subheader("✅ Final Answer")
        final_draft = current_state.get("draft") or "_(no draft)_"
        st.markdown(final_draft)

        verification = current_state.get("verification") or {}
        if verification:
            st.markdown("**Verification**")
            col1, col2 = st.columns([1, 3])
            with col1:
                st.metric("Rating", value=str(verification.get("rating", "N/A")))
                st.metric("Safe", value=str(verification.get("safe", "N/A")))
            with col2:
                st.write(verification.get("feedback", ""))

        st.markdown("---")
        st.subheader("🗨️ Conversation Transcript")
        msgs = current_state.get("messages") or []
        if msgs:
            _render_messages(msgs)
        else:
            st.info("No chat messages recorded in state (only internal node outputs).")

        st.markdown("---")
        with st.expander("🧾 Raw Final State (debug)", expanded=False):
            st.json(current_state)