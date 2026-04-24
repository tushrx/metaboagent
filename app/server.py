"""FastAPI backend for MetaboAgent.

Three endpoints per CLAUDE.md §4:

  POST /chat     → text/event-stream of agent.core.run_agent events
  GET  /health   → per-tier vLLM reachability probe (3-way asyncio.gather)
  GET  /tools    → catalog of all 15 tool schemas for UI introspection

Cancellation: FastAPI/uvicorn propagate client disconnect into the async
generator as CancelledError; re-raising it cleanly cancels the upstream
run_agent task without leaks.

Serving: ``scripts/run_server.sh`` invokes
``uvicorn app.server:app --host APP_HOST --port APP_PORT`` (defaults
127.0.0.1:8080). No auth — local demo. Revisit if publicly deployed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent.core import build_tool_registry, run_agent
from app.schemas import ChatRequest, MessageIn, ToolDescriptor
from config import (
    DEEP_LLM_BASE_URL,
    MAX_RIGOR_LLM_BASE_URL,
    PRIMARY_LLM_BASE_URL,
)

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_S = 2.0
_DEFAULT_CORS_REGEX = r"https?://(127\.0\.0\.1|localhost)(:\d+)?"


def _attachments_stubbed() -> bool:
    """Phase 5.6 gate. When true, any /chat request that includes
    attachments short-circuits to a canned SSE sequence instead of
    running the agent. Phase 6 flips this to 0 and wires vision.
    """
    return os.environ.get("ATTACHMENTS_STUBBED", "1") == "1"


def _any_attachments(body: "ChatRequest") -> int:
    return sum(len(m.attachments) for m in body.messages)


async def _stubbed_attachment_stream(n: int) -> AsyncIterator[dict]:
    """Canned event sequence for Phase 5.6. Keeps the event shape
    identical to the live agent so the UI needs no special-casing."""
    yield {
        "type": "thinking",
        "content": "Got the image(s). Vision wiring lands in Phase 6.",
    }
    text = (
        f"I can see you attached {n} image{'s' if n != 1 else ''}. "
        "Image understanding arrives in Phase 6 — for now I can only read text."
    )
    yield {"type": "token", "content": text}
    yield {"type": "final_answer", "content": text}
    yield {
        "type": "done",
        "usage": {
            "tokens_in": 0,
            "tokens_out": 0,
            "iterations": 0,
            "tool_calls": 0,
            "ms": 0,
        },
    }


def _extra_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="MetaboAgent", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_DEFAULT_CORS_REGEX,
        allow_origins=_extra_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/chat")
    async def chat(body: ChatRequest) -> StreamingResponse:
        messages = _to_langchain_messages(body.messages)

        attachment_count = _any_attachments(body)
        stub_mode = attachment_count > 0 and _attachments_stubbed()

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                if stub_mode:
                    async for ev in _stubbed_attachment_stream(attachment_count):
                        yield _sse(ev)
                    return
                async for ev in run_agent(
                    messages,
                    tier=body.tier,
                    max_iterations=body.max_iterations,
                    temperature=body.temperature,
                ):
                    yield _sse(ev)
            except asyncio.CancelledError:
                logger.info("chat stream cancelled by client")
                raise
            except Exception as e:
                logger.exception("chat stream error")
                yield _sse({
                    "type": "error",
                    "where": "server",
                    "message": f"{type(e).__name__}: {e}",
                })
                yield _sse({"type": "done", "usage": {}})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/health")
    async def health() -> JSONResponse:
        endpoints = {
            "default": PRIMARY_LLM_BASE_URL,
            "deep": DEEP_LLM_BASE_URL,
            "max_rigor": MAX_RIGOR_LLM_BASE_URL,
        }
        results = await asyncio.gather(
            *(_probe(url) for url in endpoints.values()),
            return_exceptions=False,
        )
        statuses = dict(zip(endpoints.keys(), results))
        ok_count = sum(1 for s in statuses.values() if s == "ok")
        if ok_count == 3:
            overall, status_code = "ok", 200
        elif ok_count == 0:
            overall, status_code = "down", 503
        else:
            overall, status_code = "degraded", 200
        return JSONResponse(
            {**statuses, "overall": overall}, status_code=status_code,
        )

    @app.get("/tools", response_model=list[ToolDescriptor])
    async def tools() -> list[ToolDescriptor]:
        registry = build_tool_registry()
        out: list[ToolDescriptor] = []
        for name in sorted(registry):
            t = registry[name]
            if t.args_schema is not None:
                params = t.args_schema.model_json_schema()
            else:
                params = {"type": "object", "properties": {}}
            out.append(ToolDescriptor(
                name=name,
                description=t.description or "",
                parameters_schema=params,
            ))
        return out

    return app


app = create_app()


# --- helpers -----------------------------------------------------------------

async def _probe(base_url: str) -> str:
    url = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            r = await client.get(url)
            return "ok" if r.status_code == 200 else "down"
    except Exception:
        return "down"


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def _to_langchain_messages(msgs: list[MessageIn]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in msgs:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
    return out
