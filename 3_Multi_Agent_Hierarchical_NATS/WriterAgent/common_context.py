# =============================================================================
# File: common_context.py
# Description:
#     Utilities for generating and propagating W3C traceparent headers
#     used in distributed tracing across asynchronous agent-to-agent (A2A)
#     communication flows.
#
# Key Features:
#     - Secure generation of trace_id and span_id using Python's `secrets`
#     - Root traceparent creation with fixed version and flags
#     - Child traceparent generation preserving trace_id
#     - Graceful fallback for malformed parent headers
#
# Usage:
#     tp = new_traceparent()
#     child_tp = child_traceparent(tp)
#
# Dependencies:
#     - Python 3.10+
#     - logging_init.logger
# =============================================================================

import secrets
from logging_init import logger

def _hex(nbytes: int) -> str:
    """
    Generate a secure random hexadecimal string with length '2 * nbytes'.
    """
    val = secrets.token_hex(nbytes)
    logger.debug(f"Generated hex value={val} for nbytes={nbytes}")
    return val

def new_traceparent() -> str:
    """
    Create a new W3C traceparent header string:
        version-trace_id-span_id-flags

    - version: '00'
    - trace_id: 16 bytes (32 hex chars)
    - span_id:  8 bytes (16 hex chars)
    - flags:    '01' (sampled)
    """
    trace_id = _hex(16)
    span_id = _hex(8)
    flags = "01"
    tp = f"00-{trace_id}-{span_id}-{flags}"
    logger.info(f"New traceparent generated: {tp}")
    return tp

def child_traceparent(parent: str) -> str:
    """
    Generate a child traceparent using the same trace_id but a new span_id.
    If the parent is malformed, returns a brand new root traceparent.

    Input example:
        00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
    """
    try:
        version, trace_id, _span_id, flags = parent.split("-")
        assert version == "00"
        assert len(trace_id) == 32
        assert len(flags) == 2
    except Exception as exc:
        logger.warning(f"Malformed parent traceparent; generating a new root. parent={parent}, error={exc}")
        return new_traceparent()

    new_span_id = _hex(8)
    child = f"00-{trace_id}-{new_span_id}-{flags}"
    logger.info(f"Child traceparent generated: {child} (parent={parent})")
    return child
