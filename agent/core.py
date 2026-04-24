"""Agent core — native Gemma 4 tool calling with event-stream output.

Loop: inject PRIMARY_SYSTEM_PROMPT, bounded_messages from History,
select_llm(tier, tools), then iterate up to max_iterations — astream
the LLM yielding token events, sum AIMessageChunks via ``+`` to
resolve tool_call_chunks into tool_calls (vLLM streams them as deltas;
verified against :8001 in /tmp/phase35_stream_probe.py), execute tools
with dedup, loop. No tool_calls → final_answer; overflow → graceful
final_answer. See CLAUDE.md §4 for the full event schema.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from agent.history import History
from agent.prompts import PRIMARY_SYSTEM_PROMPT
from agent.router import ModelTier, select_llm

# --- tool registry -----------------------------------------------------------
# Single import point for the 15 tools. The core doesn't know implementations.
from agent.tools.compare_synthesis_routes import compare_synthesis_routes
from agent.tools.design_expression_vector import design_expression_vector
from agent.tools.design_primers import design_primers
from agent.tools.enzyme_ranker import rank_enzymes
from agent.tools.fetch_gene_sequence import fetch_gene_sequence
from agent.tools.fetch_kegg_live import fetch_kegg_live
from agent.tools.fetch_pubchem import fetch_pubchem
from agent.tools.fetch_pubmed_live import fetch_pubmed_live
from agent.tools.fetch_sabio_rk import fetch_sabio_rk
from agent.tools.fetch_uniprot import fetch_uniprot
from agent.tools.fetch_zinc import fetch_zinc
from agent.tools.kegg_search import search_kegg
from agent.tools.literature_search import search_literature
from agent.tools.parse_structure_image import parse_structure_image
from agent.tools.retrosynthesis import plan_retrosynthesis
from agent.tools.web_search import web_search

_DEFAULT_MAX_ITERATIONS = 8

logger = logging.getLogger(__name__)


def build_tool_registry() -> dict[str, BaseTool]:
    """Return a {name → BaseTool} mapping of the agent's tools (16 as of
    Phase 6.2: the original 15 plus parse_structure_image for vision)."""
    tools: list[BaseTool] = [
        compare_synthesis_routes, design_expression_vector, design_primers,
        rank_enzymes, fetch_gene_sequence, fetch_kegg_live, fetch_pubchem,
        fetch_pubmed_live, fetch_sabio_rk, fetch_uniprot, fetch_zinc,
        search_kegg, search_literature, parse_structure_image,
        plan_retrosynthesis, web_search,
    ]
    return {t.name: t for t in tools}


# --- event builder (plain dicts) ---------------------------------------------

def _ev(type: str, **payload) -> dict:
    return {"type": type, **payload}


# --- main entry point --------------------------------------------------------

async def run_agent(
    messages: list[BaseMessage],
    tier: ModelTier = "default",
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    temperature: float = 0.2,
) -> AsyncIterator[dict]:
    """Run the agent loop, yielding events per CLAUDE.md §4.

    Callers must drain the generator; the last event is always ``done``
    or ``error``+``done``.
    """
    t0 = time.perf_counter()
    usage = {"tokens_in": 0, "tokens_out": 0, "iterations": 0, "tool_calls": 0, "ms": 0}

    history = _history_from_messages(messages)
    tools = build_tool_registry()

    # Phase 6.3 — run-scoped buffer of attachments on the last user turn.
    # The LLM sees a hint telling it to call parse_structure_image but
    # has no way to encode the real base64 bytes; the tool-dispatch path
    # below splices in the real image from this queue per call.
    pending_images: list[dict] = _extract_last_turn_attachments(messages)

    try:
        llm = select_llm(tier, list(tools.values()), temperature=temperature)
    except Exception as e:
        yield _ev("error", where="router", message=f"{type(e).__name__}: {e}")
        yield _ev("done", usage=_finalize(usage, t0))
        return

    working: list[BaseMessage] = list(history.bounded_messages(PRIMARY_SYSTEM_PROMPT))
    if pending_images:
        working.append(HumanMessage(content=_attachment_hint(len(pending_images))))

    for iteration in range(max_iterations):
        usage["iterations"] = iteration + 1
        accumulated_text = ""
        final_ai = None
        try:
            async for kind, payload in _stream_llm(llm, working):
                if kind == "token":
                    accumulated_text += payload
                    yield _ev("token", content=payload)
                elif kind == "final":
                    final_ai = payload
        except Exception as e:
            yield _ev("error", where=f"llm:iter{iteration}",
                      message=f"{type(e).__name__}: {e}")
            yield _ev("done", usage=_finalize(usage, t0))
            return

        if final_ai is None:
            yield _ev("error", where=f"llm:iter{iteration}",
                      message="stream produced no chunks")
            yield _ev("done", usage=_finalize(usage, t0))
            return

        _accumulate_usage(usage, final_ai)

        tool_calls = list(getattr(final_ai, "tool_calls", []) or [])
        if not tool_calls:
            yield _ev("final_answer",
                      content=accumulated_text or str(final_ai.content))
            yield _ev("done", usage=_finalize(usage, t0))
            return

        # Keep AI message (with tool_calls) paired with the ToolMessage responses.
        working.append(final_ai)

        for tc in tool_calls:
            usage["tool_calls"] += 1
            name = tc.get("name", "")
            args = tc.get("args", {}) or {}
            call_id = tc.get("id") or f"tc_{iteration}_{usage['tool_calls']}"

            # Phase 6.3 — splice in a real image for parse_structure_image
            # calls. The LLM prompt doesn't give it raw base64, so whatever
            # it provides for image_data_base64 is placeholder/hallucinated;
            # we overwrite with the next queued attachment. The override
            # happens BEFORE dedup so two successive calls against two
            # different attachments don't collide on a shared placeholder.
            if name == "parse_structure_image" and pending_images:
                img = pending_images.pop(0)
                args = {
                    **args,
                    "image_data_base64": img.get("data_base64") or "",
                    "mime_type": img.get("mime_type") or "image/png",
                }

            yield _ev("tool_call", name=name, args=_redact_tool_args(name, args), id=call_id)

            if not history.check_and_record_call(name, args):
                synthetic = (
                    f"[dedup] {name}({json.dumps(args, sort_keys=True)}) was "
                    "already called earlier this turn — reuse the prior "
                    "result rather than calling again."
                )
                working.append(ToolMessage(content=synthetic, tool_call_id=call_id))
                yield _ev("tool_result", id=call_id, content=synthetic)
                continue

            tool = tools.get(name)
            if tool is None:
                msg = f"unknown tool: {name!r}"
                working.append(ToolMessage(
                    content=msg, tool_call_id=call_id, status="error",
                ))
                yield _ev("tool_error", id=call_id, name=name, message=msg)
                continue

            try:
                result = await _invoke_tool(tool, args)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                working.append(ToolMessage(
                    content=err, tool_call_id=call_id, status="error",
                ))
                yield _ev("tool_error", id=call_id, name=name, message=err)
                continue

            result_str = result if isinstance(result, str) else json.dumps(result)
            working.append(ToolMessage(content=result_str, tool_call_id=call_id))
            yield _ev("tool_result", id=call_id, content=result)

    yield _ev("final_answer", content=_overflow_message(usage))
    yield _ev("done", usage=_finalize(usage, t0))


# --- internals ---------------------------------------------------------------

def _history_from_messages(messages: list[BaseMessage]) -> History:
    """Drop any incoming SystemMessage (we inject our own) and replay into History."""
    h = History()
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            h.add_user_turn(m.content)
        elif isinstance(m, AIMessage):
            h.add_assistant_turn(
                m.content, tool_calls=getattr(m, "tool_calls", None),
            )
        elif isinstance(m, ToolMessage):
            h.add_tool_result(
                tool_call_id=m.tool_call_id,
                content=m.content,
                is_error=getattr(m, "status", "success") == "error",
            )
        elif isinstance(m, SystemMessage):
            logger.warning(
                "run_agent received SystemMessage at position %d; "
                "dropped in favor of PRIMARY_SYSTEM_PROMPT",
                i,
            )
            continue
    return h


async def _stream_llm(llm, messages):
    """Yield ('token', str) per non-empty content chunk, then ('final', AIMessageChunk).

    Accumulates chunks via ``+`` so tool_call_chunks resolve into tool_calls
    on the final message (verified against :8001 in the preflight probe).
    """
    chunks: list[AIMessageChunk] = []
    async for chunk in llm.astream(messages):
        content = getattr(chunk, "content", "") or ""
        if content:
            yield ("token", content)
        chunks.append(chunk)
    if not chunks:
        return
    final = chunks[0]
    for c in chunks[1:]:
        final = final + c
    yield ("final", final)


async def _invoke_tool(tool: BaseTool, args: dict[str, Any]) -> Any:
    if hasattr(tool, "ainvoke"):
        return await tool.ainvoke(args)
    return tool.invoke(args)


def _extract_last_turn_attachments(messages: list[BaseMessage]) -> list[dict]:
    """Pull attachments off the most recent HumanMessage.

    Attachments ride inside ``HumanMessage.additional_kwargs['attachments']``
    — see ``app.server._to_langchain_messages``. We only surface them for
    the *last* user turn; older attachments are historical context, the
    analysis for those turns has already happened.
    """
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            atts = (m.additional_kwargs or {}).get("attachments") or []
            return [dict(a) for a in atts]
    return []


def _attachment_hint(n: int) -> str:
    """Directive hint for the LLM that image(s) are available.

    Gemma 4 E4B reads a polite "attached images" instruction as "ask the
    user for base64" and stalls. Telling the model it can pass a sentinel
    and the runtime will splice in the real bytes unblocks the tool call.
    """
    s = "s" if n != 1 else ""
    plural = "each" if n != 1 else "it"
    return (
        f"[{n} image{s} already attached to this turn. Call "
        f"parse_structure_image on {plural} NOW. Pass "
        f"image_data_base64=\"ATTACHED\" — the runtime substitutes the "
        f"real bytes at call time. Do NOT ask the user for base64 data.]"
    )


def _redact_tool_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Strip the inline image payload from the tool_call event.

    parse_structure_image's image_data_base64 is typically tens-to-hundreds
    of KB; piping it through the SSE stream bloats the UI crumb strip and
    the persisted activity log. Replace with a short marker for display.
    """
    if name != "parse_structure_image":
        return args
    b64 = args.get("image_data_base64") or ""
    if not b64:
        return args
    redacted = {**args, "image_data_base64": f"<{len(b64)} chars redacted>"}
    return redacted


def _accumulate_usage(usage: dict, final_ai) -> None:
    meta = getattr(final_ai, "usage_metadata", None) or {}
    usage["tokens_in"] += int(meta.get("input_tokens", 0) or 0)
    usage["tokens_out"] += int(meta.get("output_tokens", 0) or 0)


def _finalize(usage: dict, t0: float) -> dict:
    usage["ms"] = int((time.perf_counter() - t0) * 1000)
    return usage


def _overflow_message(usage: dict) -> str:
    return (
        "I stopped after reaching the maximum tool-call iteration limit "
        f"({usage['iterations']} steps, {usage['tool_calls']} tool calls). "
        "Based on what I gathered so far, I don't yet have enough evidence "
        "to give you a confident answer. If you'd like, please narrow the "
        "question or point me at a specific angle to focus on."
    )
