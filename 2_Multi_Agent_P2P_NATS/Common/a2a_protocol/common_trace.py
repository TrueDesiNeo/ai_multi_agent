import os
import secrets
import logging

# Configure logging for this module
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def _hex(nbytes: int) -> str:
    """
    Generate a secure random hexadecimal string of given byte length.
    """
    hex_value = secrets.token_hex(nbytes)
    logger.debug(f"Generated hex ({nbytes} bytes): {hex_value}")
    return hex_value

def new_traceparent() -> str:
    """
    Create a new W3C traceparent string for distributed tracing.
    Format: version-trace_id-span_id-flags
    """
    trace_id = _hex(16)   # 16 bytes = 32 hex characters
    span_id  = _hex(8)    # 8 bytes  = 16 hex characters
    flags    = "01"       # Default flags (e.g., sampled)
    traceparent = f"00-{trace_id}-{span_id}-{flags}"
    logger.info(f"New traceparent created: {traceparent}")
    return traceparent

def child_traceparent(parent: str) -> str:
    """
    Generate a child traceparent string using the same trace_id but a new span_id.
    If the parent is malformed, generate a new traceparent.
    """
    try:
        version, trace_id, _, flags = parent.split("-")
        logger.debug(f"Extracted trace_id from parent: {trace_id}")
    except Exception as e:
        logger.warning(f"Failed to parse parent traceparent '{parent}': {e}")
        return new_traceparent()

    span_id = _hex(8)
    child = f"00-{trace_id}-{span_id}-{flags}"
    logger.info(f"Child traceparent created: {child}")
    return child