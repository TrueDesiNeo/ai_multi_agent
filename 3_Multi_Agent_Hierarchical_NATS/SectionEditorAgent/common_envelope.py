# =============================================================================
# File: common_envelope.py
# Description:
#     Envelope model for asynchronous agent-to-agent (A2A) communication.
#     Provides standardized metadata for tracing, retries/TTL, and payload
#     handling, including helpers to create root and child envelopes that
#     preserve conversation/trace correlation.
#
# Key Features:
#     - W3C trace context propagation via `traceparent`
#     - TTL and retry bookkeeping for quality gates and revision loops
#     - Pydantic-based validation (compatible helpers for v1/v2)
#     - Utilities to create root and child envelopes safely
#
# Usage:
#     env = new_root_envelope("Write about Edge AI", to_role="chief", max_retries=2)
#     if env.is_expired():
#         # handle expiration
#     child = env.child(target="verifier@v1", payload={"draft_id": "abc123"})
#
# Dependencies:
#     - Python 3.10+
#     - pydantic
#     - common_trace.new_traceparent / child_traceparent
#     - logging_init.logger
#
# Notes:
#     - `traceparent` follows W3C Trace Context (00-<trace_id>-<span_id>-<flags>)
#     - Time is stored in UTC
#     - `as_dict()` offers compatibility across pydantic v1/v2
#
# =============================================================================

from typing import Any, Dict, Optional
from uuid import uuid4
from common_trace import new_traceparent, child_traceparent
from logging_init import logger
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field, field_validator

class A2AEnvelope(BaseModel):
    """
    Envelope for asynchronous agent-to-agent (A2A) communication.
    Includes tracing metadata, retries/TTL, and message payload.

    Fields:
        envelope_version: protocol version string
        message_id: unique per message
        conversation_id: correlates all messages in a flow
        traceparent: W3C Trace Context header (00-<trace_id>-<span_id>-<flags>)
        sender/target: service identifiers like "writer@v1"
        ttl_ms: time-to-live for this message in milliseconds
        retries/max_retries: revision loop bookkeeping for quality gates
        created_at: message creation timestamp (UTC)
        payload: message body (agent-specific)
    """
    envelope_version: str = "1.1"
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str = Field(default_factory=lambda: str(uuid4()))
    traceparent: str = Field(default_factory=new_traceparent)
    sender: str
    target: str
    ttl_ms: int = 15_000
    retries: int = 0
    max_retries: int = 2
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("ttl_ms")
    @classmethod
    def _validate_ttl_ms(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("ttl_ms must be > 0")
        return v

    @field_validator("retries", "max_retries")
    @classmethod
    def _validate_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("retries/max_retries must be >= 0")
        return v

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """
        Returns True if 'now' is beyond created_at + ttl_ms.
        """
        now = now or datetime.now(timezone.utc)
        expires = self.created_at + timedelta(milliseconds=self.ttl_ms)
        expired = now > expires
        if expired:
            logger.debug(
                "Envelope expired",
                extra={"message_id": self.message_id, "conversation_id": self.conversation_id}
            )
        return expired

    def child(
        self,
        *,
        sender: Optional[str] = None,
        target: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        retries: Optional[int] = None,
        max_retries: Optional[int] = None,
        ttl_ms: Optional[int] = None,
        keep_span: bool = False,
    ) -> "A2AEnvelope":
        """
        Creates a child envelope within the same conversation.

        Args:
            sender/target: override sender or target for the next hop.
            payload: new payload; defaults to {} if not provided.
            retries: override retry counter (e.g., verifier -> writer revision).
            max_retries: override max retries (if business logic changes).
            ttl_ms: override TTL for the next hop (optional).
            keep_span: if True, reuse same traceparent; otherwise generate a child span.

        Returns:
            A2AEnvelope ready to publish to the next subject.
        """
        new_tp = self.traceparent if keep_span else child_traceparent(self.traceparent)
        child_env = A2AEnvelope(
            sender=sender or self.sender,
            target=target or self.target,
            conversation_id=self.conversation_id,
            traceparent=new_tp,
            ttl_ms=ttl_ms if ttl_ms is not None else self.ttl_ms,
            retries=self.retries if retries is None else retries,
            max_retries=self.max_retries if max_retries is None else max_retries,
            payload=payload or {},
        )
        logger.info(
            "Child envelope created",
            extra={"parent_id": self.message_id, "child_id": child_env.message_id, "conversation_id": self.conversation_id}
        )
        return child_env

    # Compatibility helper (works across pydantic v1/v2 call sites)
    def as_dict(self) -> Dict[str, Any]:
        try:
            return self.model_dump()  # pydantic v2
        except Exception:
            return self.dict()        # pydantic v1

def new_root_envelope(
    task: str,
    *,
    from_role: str = "client",
    to_role: str = "researcher",
    conversation_id: Optional[str] = None,
    max_retries: int = 2,
    ttl_ms: int = 15_000,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> A2AEnvelope:
    """
    Creates a root envelope to initiate a conversation.
    - Auto-generates conversation_id and traceparent if not supplied.
    - Seeds the payload with {"role": from_role, "task": task} and any extra_payload.

    Example:
        env = new_root_envelope("Write about Edge AI", to_role="chief", max_retries=2)
    """
    cid = conversation_id or str(uuid4())
    base_payload = {"role": from_role, "task": task}
    if extra_payload:
        base_payload.update(extra_payload)

    root_env = A2AEnvelope(
        conversation_id=cid,
        traceparent=new_traceparent(),
        sender=f"{from_role}@v1",
        target=f"{to_role}@v1",
        max_retries=max_retries,
        ttl_ms=ttl_ms,
        payload=base_payload,
    )
    logger.info("Root envelope created", extra={"message_id": root_env.message_id, "conversation_id": cid})
    return root_env
