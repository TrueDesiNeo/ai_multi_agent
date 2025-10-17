# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import uuid4
from pydantic import BaseModel, Field
from .common_trace import new_traceparent, child_traceparent

# Configure logging for this module
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class A2AEnvelope(BaseModel):
    """
    Represents an envelope for asynchronous agent-to-agent (A2A) communication.
    Includes metadata for tracing, retries, and payload delivery.
    """
    envelope_version: str = "1.0"
    message_id: str = Field(default_factory=lambda: str(uuid4()))  # Unique message ID
    conversation_id: str  # Shared ID across related messages
    traceparent: str  # Trace context for distributed tracing
    sender: str  # Sender identifier
    target: str  # Target recipient identifier
    ttl_ms: int = 15000  # Time-to-live in milliseconds
    retries: int = 0  # Current retry count
    max_retries: int = 2  # Maximum allowed retries
    payload: Dict[str, Any]  # Actual message content

    def child(self, *, sender: str, target: str, payload: Dict[str, Any],
              retries: Optional[int] = None) -> "A2AEnvelope":
        """
        Creates a child envelope for a follow-up message in the same conversation.
        Inherits trace context and conversation ID.
        """
        logger.debug(f"Creating child envelope from sender={sender} to target={target}")
        child_env = A2AEnvelope(
            conversation_id=self.conversation_id,
            traceparent=child_traceparent(self.traceparent),
            sender=sender,
            target=target,
            ttl_ms=self.ttl_ms,
            retries=self.retries if retries is None else retries,
            max_retries=self.max_retries,
            payload=payload
        )
        logger.info(f"Child envelope created with message_id={child_env.message_id}")
        return child_env

def new_root_envelope(task: str, *, from_role="client", to_role="researcher",
                      conversation_id: Optional[str] = None,
                      max_retries: int = 2) -> A2AEnvelope:
    """
    Creates a new root envelope to initiate a conversation.
    Generates a new trace context and conversation ID if not provided.
    """
    cid = conversation_id or str(uuid4())
    logger.debug(f"Creating new root envelope for task='{task}' from={from_role} to={to_role}")
    root_env = A2AEnvelope(
        conversation_id=cid,
        traceparent=new_traceparent(),
        sender=f"{from_role}@v1",
        target=f"{to_role}@v1",
        max_retries=max_retries,
        payload={"role": from_role, "task": task}
    )
    logger.info(f"Root envelope created with message_id={root_env.message_id}, conversation_id={cid}")
    return root_env