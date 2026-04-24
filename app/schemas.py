"""Pydantic models for the HTTP boundary.

Kept intentionally narrow — langchain ``BaseMessage`` is the internal
currency; we only wrap at the edge to validate client payloads and to
shape the /tools and /health responses.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["default", "deep", "max_rigor"]

AttachmentMime = Literal["image/png", "image/jpeg", "image/webp"]

# ~6 MB raw → ~8 MB base64 (4/3 expansion). Matches the client-side 5 MB
# raw cap with a little slack for the base64 overhead.
_MAX_ATTACHMENT_B64_BYTES = 8 * 1024 * 1024
_MAX_ATTACHMENTS_PER_MESSAGE = 3


class Attachment(BaseModel):
    """One image attachment on a user message.

    The client validates dimensions/type; the server only enforces the
    mime allowlist, attachment count, and a hard ceiling on base64 size
    so a malicious or buggy client can't post a 500 MB blob.
    """

    kind: Literal["image"] = "image"
    mime_type: AttachmentMime
    filename: str = Field(..., min_length=1, max_length=256)
    data_base64: str = Field(..., min_length=1, max_length=_MAX_ATTACHMENT_B64_BYTES)
    thumbnail_base64: str = Field(..., min_length=1, max_length=_MAX_ATTACHMENT_B64_BYTES)


class MessageIn(BaseModel):
    """One turn of conversation as received from a client."""

    role: Literal["user", "assistant"]
    content: str
    attachments: list[Attachment] = Field(
        default_factory=list,
        max_length=_MAX_ATTACHMENTS_PER_MESSAGE,
    )


class ChatRequest(BaseModel):
    """Payload for POST /chat."""

    messages: list[MessageIn] = Field(..., min_length=1)
    tier: Tier = "default"
    max_iterations: int = Field(8, ge=1, le=50)
    temperature: float = Field(0.2, ge=0.0, le=2.0)


class HealthResponse(BaseModel):
    """Per-tier reachability probe result."""

    default: Literal["ok", "down"]
    deep: Literal["ok", "down"]
    max_rigor: Literal["ok", "down"]
    overall: Literal["ok", "degraded", "down"]


class ToolDescriptor(BaseModel):
    """One entry in the GET /tools response.

    ``parameters_schema`` is the OpenAI-style JSON Schema dict emitted by
    ``tool.args_schema.model_json_schema()`` — same shape the LLM sees at
    bind time.
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
