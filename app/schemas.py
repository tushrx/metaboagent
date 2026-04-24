"""Pydantic models for the HTTP boundary.

Kept intentionally narrow — langchain ``BaseMessage`` is the internal
currency; we only wrap at the edge to validate client payloads and to
shape the /tools and /health responses.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["default", "deep", "max_rigor"]


class MessageIn(BaseModel):
    """One turn of conversation as received from a client."""

    role: Literal["user", "assistant"]
    content: str


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
