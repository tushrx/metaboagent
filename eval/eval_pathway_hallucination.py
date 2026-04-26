"""Phase 6.5-pre baseline: how often does the agent fabricate KEGG
R-IDs and EC numbers when it reaches the deep-dive step of a pathway
design conversation?

The agent's system prompt splits pathway questions into Phase 1
(propose <plan>...</plan> with 3-4 approaches, no IDs yet) and
Phase 2 (deep-dive after the user picks, numbered pathway steps with
R-IDs + EC numbers). Hallucinated IDs live in Phase 2 output, so a
single-turn eval measures nothing — we drive both turns.

Flow per prompt:
  1. Turn 1: run_agent on the original user message.
     Collect final_answer + usage.
  2. Parse <plan>...</plan> from turn 1; extract plan IDs (A/B/C or
     1/2/3). If missing, mark plan_parse_failed and skip.
  3. Turn 2: run_agent on
        [Human(original), AI(phase1_final_answer), Human(first_plan_id)]
     Collect final_answer + usage.
  4. Extract R-IDs (``R\\d{5}``) and EC numbers
     (``EC\\s?\\d+\\.\\d+\\.\\d+\\.\\d+``) from Phase 2 answer.
  5. Verify each against KEGG REST with 400 ms sleep (KEGG allows
     ~3 rps anonymous).
  6. Aggregate.

We call run_agent in-process rather than POST /chat — it's the same
code path and avoids needing a live uvicorn.

Output: eval/results/pathway_hallucination_baseline_<ts>.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from eval._kegg_verify import (
    KEGG_SLEEP_S,
    verify_ec_number as _kv_verify_ec,
    verify_kegg_reaction_id as _kv_verify_rid,
    verify_reaction_substrate,
)
from eval._runner import drain_agent_turn, timestamp_utc, write_result

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = REPO_ROOT / "eval/scenarios/pathway_design/prompts.json"

RID_RE = re.compile(r"\bR\d{5}\b")
EC_RE = re.compile(r"\bEC\s?(\d+\.\d+\.\d+\.\d+)\b")
PLAN_BLOCK_RE = re.compile(r"<plan>\s*(.*?)\s*</plan>", re.DOTALL | re.IGNORECASE)
# A pathway step opener. Accepts the canonical "Step 1:" shape plus the
# markdown numbered-list styles the model sometimes drifts into:
#   Step 1:          (canonical from the system prompt)
#   **Step 1:**      (bold-wrapped canonical)
#   1.               (markdown ordered list)
#   1)               (paren-style list)
#   **1.**           (bold-wrapped numbered)
# Anchored to line start with optional leading whitespace. The closing
# punctuation ([.):]) guards against false positives like "1 gram" or
# "Figure 1." (the latter doesn't start with a digit at line anchor).
STEP_LINE_RE = re.compile(
    r"(?im)^\s*(?:\*\*)?\s*(?:Step\s+)?(\d+)[.):]"
)
# Marker for Phase 6.5.c's nudge thinking event.
_NUDGE_MARKER = "Empty completion detected"

# Hedge phrases that indicate the agent is declaring insufficient
# evidence rather than silently giving up. Matched case-insensitively.
_INSUFFICIENT_EVIDENCE_MARKERS = (
    "evidence needed",
    "omit",
    "insufficient",
    "confirmed via",
    "database lookup",
    "not available",
    "unable to confirm",
    "pending verification",
)
# Silent-giveup threshold: any meaningful design explanation will be
# well above this in non-whitespace characters.
_SILENT_GIVEUP_MAX_CHARS = 50


# Phase 8.3.B — step-block parsing for substrate-relevance checks.
# A "step block" is a Step N: line plus everything until the next Step
# line. The head of the step ("Step N: A + B → C") gives us the
# substrate names (lhs of arrow) and product names (rhs); the body
# carries any cited R-IDs / EC numbers we want to substrate-check.
_STEP_HEAD_RE = re.compile(
    # Optional leading bullet-list marker (* / - / •) so we catch
    # "*   **Step 1: ...**" along with the bare and bolded forms.
    r"^\s*[\*\-•]?\s*(?:\*\*)?\s*(?:Step\s+)?(\d+)[.):]\s*(.*?)\s*(?:\*\*)?\s*$",
    re.IGNORECASE,
)
# Arrow forms we accept on a step line or Reaction: bullet:
#   ASCII / Unicode:  ->, =>, →, ⇒, ⟶
#   LaTeX (delimited or bare):  $\rightarrow$, $\to$, \rightarrow, \to
# Word-boundary on the bare LaTeX forms keeps "rightarrow" inside a
# longer identifier from accidentally triggering.
_ARROW_RE = re.compile(
    r"\s*(?:->|=>|→|⇒|⟶|\$\\(?:rightarrow|to)\$|\\(?:rightarrow|to)\b)\s*"
)
_PLUS_SPLIT_RE = re.compile(r"\s+\+\s+")
# A "Reaction:" sub-bullet inside a step block. The agent often puts
# the actual A → B chemistry on this line rather than on the step head
# (which is typically a prose label like "**Step 1: Activation**").
_REACTION_LINE_RE = re.compile(
    r"^\s*[\*\-•]?\s*\**\s*(?:Reaction|Conversion)\s*:?\s*\**\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _clean_compound_token(s: str) -> str:
    s = s.strip()
    # Strip LaTeX math delimiters: $...$  →  inner content.
    s = re.sub(r"\$([^$]*?)\$", r"\1", s)
    # Strip \text{...}  →  inner content.
    s = re.sub(r"\\text\{([^}]*?)\}", r"\1", s)
    # Strip generic \something{...} wrappers (e.g. \mathrm{...}).
    s = re.sub(r"\\[a-zA-Z]+\{([^}]*?)\}", r"\1", s)
    s = re.sub(r"\([^)]*\)$", "", s).strip()
    s = s.rstrip(":,;.")
    s = s.strip().strip("*").strip("`").strip("_").strip()
    return s


def _parse_arrow_chemistry(head: str) -> tuple[list[str], list[str]]:
    """From 'A + B → C' return (['A', 'B'], ['C']).

    Empty lists when no arrow is present — caller should treat the step
    as ineligible for substrate-relevance checking and fall back to
    existence-only verification (or to the body-Reaction-line fallback
    in ``_extract_chemistry``).
    """
    m = _ARROW_RE.search(head)
    if not m:
        return [], []
    lhs = head[: m.start()]
    rhs = head[m.end():]
    lhs = re.sub(r"\([^)]*\)$", "", lhs).strip()
    rhs = re.sub(r"\([^)]*\)$", "", rhs).strip()
    sub_names = [_clean_compound_token(p) for p in _PLUS_SPLIT_RE.split(lhs) if p.strip()]
    prod_names = [_clean_compound_token(p) for p in _PLUS_SPLIT_RE.split(rhs) if p.strip()]
    return [s for s in sub_names if s], [p for p in prod_names if p]


def _extract_chemistry(step_head: str, body: str) -> tuple[list[str], list[str]]:
    """Step-head chemistry first, then body-Reaction-line fallback.

    The agent often writes a prose-only step head ("**Step 1:
    Activation**") with the A → B chemistry on a sub-bullet
    ``*   **Reaction:** A + B → C``. Without this fallback the parser
    misses every R-ID emitted in that style.
    """
    sub, prod = _parse_arrow_chemistry(step_head)
    if sub or prod:
        return sub, prod
    for m in _REACTION_LINE_RE.finditer(body):
        sub, prod = _parse_arrow_chemistry(m.group(1))
        if sub or prod:
            return sub, prod
    return [], []


def _parse_step_blocks(text: str) -> list[dict[str, Any]]:
    """Split a phase-2 answer into step blocks.

    Each block is::

        {
          step_num: int,
          step_head: str,            # text after the "Step N:" marker
          substrate_names: list[str],
          product_names: list[str],
          rids: list[str],           # R-IDs found in the block body
          ecs: list[str],            # EC numbers found in the block body
          body: str,                 # the block as raw text
        }

    Blocks are returned in source order. A non-arrow step head yields
    empty substrate / product lists; downstream verification handles
    the missing-context case explicitly.
    """
    if not text:
        return []
    lines = text.splitlines()
    starts: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _STEP_HEAD_RE.match(line)
        if not m:
            continue
        # Reuse STEP_LINE_RE-style guard: anchor must be a digit at line
        # start. _STEP_HEAD_RE already enforces this.
        starts.append((i, int(m.group(1)), m.group(2).strip()))
    blocks: list[dict[str, Any]] = []
    for k, (start_i, step_num, head) in enumerate(starts):
        end_i = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start_i:end_i])
        sub_names, prod_names = _extract_chemistry(head, body)
        rids: list[str] = []
        for r in RID_RE.findall(body):
            if r not in rids:
                rids.append(r)
        ecs: list[str] = []
        for e in EC_RE.findall(body):
            if e not in ecs:
                ecs.append(e)
        blocks.append({
            "step_num": step_num,
            "step_head": head,
            "substrate_names": sub_names,
            "product_names": prod_names,
            "rids": rids,
            "ecs": ecs,
            "body": body,
        })
    return blocks


def _block_for_rid(rid: str, blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the best step block whose body contains the given R-ID.

    Prefers blocks that have parsed substrate/product chemistry — when
    an R-ID appears in two blocks (e.g. once in a prose-only step
    header section, once in a diagram-rendering section with explicit
    arrow chemistry), the chemistry-bearing block is the right anchor
    for substrate-relevance. Falls back to any matching block when no
    candidate has parsed chemistry.
    """
    candidates = [b for b in blocks if rid in b["body"]]
    if not candidates:
        return None
    for b in candidates:
        if b["substrate_names"] and b["product_names"]:
            return b
    return candidates[0]


def _classify_no_ids_reason(text: str) -> str:
    """Refine a no_ids_emitted verdict into one of:

      silent_giveup                — short, no step markers, no hedge language
      declared_insufficient_evidence — long enough + contains hedge language
      unclassified                  — neither clearly applies (default)
    """
    body = text or ""
    nws = sum(1 for c in body if not c.isspace())
    has_step = bool(STEP_LINE_RE.search(body))
    lower = body.lower()
    has_hedge = any(m in lower for m in _INSUFFICIENT_EVIDENCE_MARKERS)

    if nws <= _SILENT_GIVEUP_MAX_CHARS and not has_step and not has_hedge:
        return "silent_giveup"
    if nws >= _SILENT_GIVEUP_MAX_CHARS and has_hedge:
        return "declared_insufficient_evidence"
    return "unclassified"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval_pathway")


def _extract_ids(text: str) -> tuple[list[str], list[str]]:
    rids: list[str] = []
    ecs: list[str] = []
    seen_r: set[str] = set()
    seen_e: set[str] = set()
    for m in RID_RE.finditer(text):
        rid = m.group(0)
        if rid not in seen_r:
            seen_r.add(rid)
            rids.append(rid)
    for m in EC_RE.finditer(text):
        ec = m.group(1)
        if ec not in seen_e:
            seen_e.add(ec)
            ecs.append(ec)
    return rids, ecs


def _extract_plan_ids(text: str) -> list[str] | None:
    """Return list of plan IDs from a <plan>...</plan> block, or None
    if no parseable plan block is present.

    Empty list (plan block present but no IDs) also returns None so
    the caller treats it as plan_parse_failed.
    """
    m = PLAN_BLOCK_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    # Tolerate stray prose before/after the JSON array inside the block.
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        arr = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list):
        return None
    ids: list[str] = []
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("id")
        if isinstance(pid, (str, int)) and str(pid).strip():
            ids.append(str(pid).strip())
    return ids or None


def _context_snippet(text: str, needle: str, window: int = 80) -> str:
    i = text.find(needle)
    if i < 0:
        return ""
    lo = max(0, i - window)
    hi = min(len(text), i + len(needle) + window)
    return text[lo:hi].replace("\n", " ").strip()


def _verify_kegg_id(client: httpx.Client, kind: str, raw: str) -> bool:
    """Thin adapter — eval rows want a bool, the shared module returns a dict.

    The dict carries equation/name/ec_numbers we don't store today; 8.3's
    substrate-relevance work will read those fields directly via the
    shared module rather than going through this adapter.
    """
    if kind == "rid":
        return bool(_kv_verify_rid(raw, client=client, sleep_after=False)["exists"])
    if kind == "ec":
        return bool(_kv_verify_ec(raw, client=client, sleep_after=False)["exists"])
    raise ValueError(f"unknown kind: {kind}")


async def _drain_turn(messages_payload: list[Any], max_iterations: int) -> dict[str, Any]:
    """Run one agent turn and add the Phase-6.5.c nudge counter.

    The shared ``drain_agent_turn`` does the heavy lifting; we only
    need the additional nudge tally for instrumentation here.
    """
    events, final_answer, usage = await drain_agent_turn(
        messages_payload,
        max_iterations=max_iterations,
    )
    nudge_count = sum(
        1 for ev in events
        if ev.get("type") == "thinking"
        and _NUDGE_MARKER in (ev.get("content") or "")
    )
    return {
        "events": events,
        "final_answer": final_answer,
        "tokens_in": usage["tokens_in"],
        "tokens_out": usage["tokens_out"],
        "duration_ms": usage["duration_ms"],
        "iterations": usage["iterations"],
        "nudge_count": nudge_count,
    }


async def _run_one(prompt_spec: dict, max_iterations: int) -> dict[str, Any]:
    """Two-turn eval for a single prompt."""
    from langchain_core.messages import AIMessage, HumanMessage

    pid = prompt_spec["id"]
    user_prompt = prompt_spec["prompt"]

    log.info("[%s] turn 1: sending original prompt…", pid)
    phase1 = await _drain_turn([HumanMessage(content=user_prompt)], max_iterations)
    log.info(
        "[%s]   phase1 done: iters=%d tokens=%d/%d ms=%d",
        pid, phase1["iterations"],
        phase1["tokens_in"], phase1["tokens_out"], phase1["duration_ms"],
    )

    plan_ids = _extract_plan_ids(phase1["final_answer"])
    row: dict[str, Any] = {
        "id": pid,
        "prompt": user_prompt,
        "phase1_final_answer": phase1["final_answer"],
        "phase1_tokens_in": phase1["tokens_in"],
        "phase1_tokens_out": phase1["tokens_out"],
        "phase1_duration_ms": phase1["duration_ms"],
        "phase1_iterations": phase1["iterations"],
        "phase1_plan_ids": plan_ids or [],
        "followup_sent": None,
        "phase2_final_answer": None,
        "phase2_tokens_in": 0,
        "phase2_tokens_out": 0,
        "phase2_duration_ms": 0,
        "phase2_iterations": 0,
        "phase1_nudge_count": phase1.get("nudge_count", 0),
        "phase2_nudge_count": 0,
        "step_convention_ok": False,
        "rids": [],
        "ecs": [],
        "status": "ok",  # ok | plan_parse_failed | no_ids_emitted
        "no_ids_reason": None,  # silent_giveup | declared_insufficient_evidence | unclassified | None
    }

    if not plan_ids:
        log.warning("[%s]   no parseable <plan> block — skipping phase 2", pid)
        row["status"] = "plan_parse_failed"
        return row

    followup = plan_ids[0]
    row["followup_sent"] = followup
    log.info("[%s] turn 2: sending follow-up %r…", pid, followup)

    phase2_messages = [
        HumanMessage(content=user_prompt),
        AIMessage(content=phase1["final_answer"]),
        HumanMessage(content=followup),
    ]
    phase2 = await _drain_turn(phase2_messages, max_iterations)
    log.info(
        "[%s]   phase2 done: iters=%d tokens=%d/%d ms=%d",
        pid, phase2["iterations"],
        phase2["tokens_in"], phase2["tokens_out"], phase2["duration_ms"],
    )

    row["phase2_final_answer"] = phase2["final_answer"]
    row["phase2_tokens_in"] = phase2["tokens_in"]
    row["phase2_tokens_out"] = phase2["tokens_out"]
    row["phase2_duration_ms"] = phase2["duration_ms"]
    row["phase2_iterations"] = phase2["iterations"]
    row["phase2_nudge_count"] = phase2.get("nudge_count", 0)
    row["step_convention_ok"] = bool(
        STEP_LINE_RE.search(phase2["final_answer"] or "")
    )

    rids, ecs = _extract_ids(phase2["final_answer"])
    log.info("[%s]   phase2 extracted: %d R-IDs, %d ECs", pid, len(rids), len(ecs))

    if not rids and not ecs:
        row["status"] = "no_ids_emitted"
        row["no_ids_reason"] = _classify_no_ids_reason(phase2["final_answer"])
        log.warning(
            "[%s]   phase2 emitted zero R-IDs/ECs — %s",
            pid, row["no_ids_reason"],
        )
        return row

    final = phase2["final_answer"]
    step_blocks = _parse_step_blocks(final)
    rid_rows: list[dict] = []
    ec_rows: list[dict] = []
    with httpx.Client(headers={"User-Agent": "MetaboAgent-eval/1.0"}) as client:
        for rid in rids:
            block = _block_for_rid(rid, step_blocks)
            if block and block["substrate_names"] and block["product_names"]:
                result = verify_reaction_substrate(
                    rid,
                    block["substrate_names"],
                    block["product_names"],
                    client=client,
                    sleep_after=False,
                )
                rid_rows.append({
                    "id": rid,
                    "verified": result["rid_exists"],
                    "step_num": block["step_num"],
                    "claimed_substrates": block["substrate_names"],
                    "claimed_products": block["product_names"],
                    "substrate_matches": result["substrate_matches"],
                    "product_matches": result["product_matches"],
                    "substrate_resolved": result["substrate_resolved"],
                    "product_resolved": result["product_resolved"],
                    "kegg_substrates": result["kegg_substrates"],
                    "kegg_products": result["kegg_products"],
                    "verdict": result["verdict"],
                    "context": _context_snippet(final, rid),
                })
            else:
                # No usable step context — keep existence-only check
                # and tag verdict so aggregates can exclude this row
                # from substrate-relevance rates.
                exists = _verify_kegg_id(client, "rid", rid)
                rid_rows.append({
                    "id": rid,
                    "verified": exists,
                    "step_num": block["step_num"] if block else None,
                    "claimed_substrates": [],
                    "claimed_products": [],
                    "substrate_matches": False,
                    "product_matches": False,
                    "substrate_resolved": False,
                    "product_resolved": False,
                    "kegg_substrates": [],
                    "kegg_products": [],
                    "verdict": "no_step_context",
                    "context": _context_snippet(final, rid),
                })
            time.sleep(KEGG_SLEEP_S)
        for ec in ecs:
            exists = _verify_kegg_id(client, "ec", ec)
            ec_rows.append({
                "id": ec,
                "verified": exists,
                "context": _context_snippet(final, f"EC {ec}")
                           or _context_snippet(final, f"EC{ec}")
                           or _context_snippet(final, ec),
            })
            time.sleep(KEGG_SLEEP_S)
    row["rids"] = rid_rows
    row["ecs"] = ec_rows
    r_bad = sum(1 for r in rid_rows if not r["verified"])
    e_bad = sum(1 for e in ec_rows if not e["verified"])
    fully = sum(1 for r in rid_rows if r.get("verdict") == "fully_matches")
    sub_only = sum(1 for r in rid_rows if r.get("verdict") == "substrate_only")
    prod_only = sum(1 for r in rid_rows if r.get("verdict") == "product_only")
    neither_v = sum(1 for r in rid_rows if r.get("verdict") == "neither")
    no_ctx = sum(1 for r in rid_rows if r.get("verdict") == "no_step_context")
    log.info(
        "[%s]   verified: rids %d hallucinated of %d; ecs %d hallucinated of %d",
        pid, r_bad, len(rid_rows), e_bad, len(ec_rows),
    )
    log.info(
        "[%s]   substrate-relevance: full=%d sub_only=%d prod_only=%d neither=%d no_ctx=%d",
        pid, fully, sub_only, prod_only, neither_v, no_ctx,
    )
    return row


def _aggregate(per_prompt: list[dict]) -> dict[str, Any]:
    p1_tokens_in = sum(r["phase1_tokens_in"] for r in per_prompt)
    p1_tokens_out = sum(r["phase1_tokens_out"] for r in per_prompt)
    p1_durs = [r["phase1_duration_ms"] for r in per_prompt if r["phase1_duration_ms"]]
    p1_avg_ms = int(round(sum(p1_durs) / len(p1_durs))) if p1_durs else 0
    plans_emitted = sum(1 for r in per_prompt if r["phase1_plan_ids"])
    plans_parse_failed = sum(1 for r in per_prompt if r["status"] == "plan_parse_failed")

    p2_eligible = [r for r in per_prompt if r["phase2_final_answer"] is not None]
    p2_tokens_in = sum(r["phase2_tokens_in"] for r in p2_eligible)
    p2_tokens_out = sum(r["phase2_tokens_out"] for r in p2_eligible)
    p2_durs = [r["phase2_duration_ms"] for r in p2_eligible if r["phase2_duration_ms"]]
    p2_avg_ms = int(round(sum(p2_durs) / len(p2_durs))) if p2_durs else 0
    no_ids_rows = [r for r in per_prompt if r["status"] == "no_ids_emitted"]
    no_ids_total = len(no_ids_rows)
    no_ids_silent = sum(1 for r in no_ids_rows if r.get("no_ids_reason") == "silent_giveup")
    no_ids_declared = sum(
        1 for r in no_ids_rows
        if r.get("no_ids_reason") == "declared_insufficient_evidence"
    )
    no_ids_unclassified = sum(
        1 for r in no_ids_rows if r.get("no_ids_reason") == "unclassified"
    )

    total_r = sum(len(r["rids"]) for r in per_prompt)
    total_r_bad = sum(1 for r in per_prompt for x in r["rids"] if not x["verified"])
    total_e = sum(len(r["ecs"]) for r in per_prompt)
    total_e_bad = sum(1 for r in per_prompt for x in r["ecs"] if not x["verified"])

    # Substrate-relevance rollup (Phase 8.3.B). Only RIDs with a parsed
    # step block (verdict in the {fully, substrate_only, product_only,
    # neither} set) count toward the rates — RIDs cited outside any
    # step block are tagged "no_step_context" and excluded.
    eligible_rids = [
        x for r in per_prompt for x in r["rids"]
        if x.get("verdict") in {
            "fully_matches", "substrate_only", "product_only", "neither", "rid_invalid",
        }
    ]
    no_step_ctx = sum(
        1 for r in per_prompt for x in r["rids"]
        if x.get("verdict") == "no_step_context"
    )
    fully_matching = sum(1 for x in eligible_rids if x["verdict"] == "fully_matches")
    substrate_only = sum(1 for x in eligible_rids if x["verdict"] == "substrate_only")
    product_only = sum(1 for x in eligible_rids if x["verdict"] == "product_only")
    neither_v = sum(1 for x in eligible_rids if x["verdict"] == "neither")
    rid_invalid = sum(1 for x in eligible_rids if x["verdict"] == "rid_invalid")
    substrate_relevant = fully_matching + substrate_only
    existence_verified_eligible = sum(1 for x in eligible_rids if x["verified"])
    real_but_wrong = existence_verified_eligible - fully_matching

    def _pct(n, d):
        return round(100.0 * n / d, 1) if d else 0.0

    rid_substrate_relevance = {
        "rids_extracted_total": total_r,
        "rids_eligible_for_substrate_check": len(eligible_rids),
        "rids_no_step_context": no_step_ctx,
        "rids_existence_verified_eligible": existence_verified_eligible,
        "rids_fully_matching": fully_matching,
        "rids_substrate_only": substrate_only,
        "rids_product_only": product_only,
        "rids_neither": neither_v,
        "rids_rid_invalid": rid_invalid,
        "rids_substrate_relevant": substrate_relevant,
        "rids_real_but_wrong": real_but_wrong,
        "rids_fully_matching_pct": _pct(fully_matching, len(eligible_rids)),
        "rids_substrate_relevant_pct": _pct(substrate_relevant, len(eligible_rids)),
        "rids_real_but_wrong_pct": _pct(real_but_wrong, existence_verified_eligible),
    }

    total_nudges = sum(
        r.get("phase1_nudge_count", 0) + r.get("phase2_nudge_count", 0)
        for r in per_prompt
    )
    prompts_with_nudge = sum(
        1 for r in per_prompt
        if (r.get("phase1_nudge_count", 0) + r.get("phase2_nudge_count", 0)) > 0
    )
    step_convention_ok = sum(1 for r in per_prompt if r.get("step_convention_ok"))

    return {
        "phase1_stats": {
            "total_tokens_in": p1_tokens_in,
            "total_tokens_out": p1_tokens_out,
            "avg_duration_ms": p1_avg_ms,
            "plans_emitted": plans_emitted,
            "plans_parse_failed": plans_parse_failed,
        },
        "phase2_stats": {
            "total_tokens_in": p2_tokens_in,
            "total_tokens_out": p2_tokens_out,
            "avg_duration_ms": p2_avg_ms,
            "phase2_runs": len(p2_eligible),
            "no_ids_emitted": {
                "total": no_ids_total,
                "silent_giveup": no_ids_silent,
                "declared_insufficient_evidence": no_ids_declared,
                "unclassified": no_ids_unclassified,
            },
            "step_convention_ok": step_convention_ok,
        },
        "pathway_accuracy": {
            "total_rids_extracted": total_r,
            "total_rids_hallucinated": total_r_bad,
            "rid_hallucination_rate_pct": round(100.0 * total_r_bad / total_r, 1) if total_r else 0.0,
            "total_ecs_extracted": total_e,
            "total_ecs_hallucinated": total_e_bad,
            "ec_hallucination_rate_pct": round(100.0 * total_e_bad / total_e, 1) if total_e else 0.0,
        },
        "rid_substrate_relevance": rid_substrate_relevance,
        "nudge_stats": {
            "total_nudges_fired": total_nudges,
            "prompts_with_nudge": prompts_with_nudge,
        },
    }


def _threshold_band(rate: float) -> str:
    if rate < 10.0:
        return "<10%  (Phase 6.5 may be unnecessary — re-evaluate)"
    if rate <= 40.0:
        return "10-40%  (Phase 6.5 as planned: verify tools + prompt tighten + validator)"
    return ">40%  (Phase 6.5 plus aggressive validator — strip unverified IDs from final_answer)"


def _print_summary(agg: dict, per_prompt: list[dict]) -> None:
    pa = agg["pathway_accuracy"]
    p1 = agg["phase1_stats"]
    p2 = agg["phase2_stats"]

    print()
    print("=" * 72)
    print("Pathway hallucination — two-turn baseline")
    print("=" * 72)
    print(
        f"Phase 1: tokens in/out={p1['total_tokens_in']}/{p1['total_tokens_out']}  "
        f"avg_ms={p1['avg_duration_ms']}  plans_emitted={p1['plans_emitted']}  "
        f"plans_parse_failed={p1['plans_parse_failed']}"
    )
    nie = p2.get("no_ids_emitted") or {}
    print(
        f"Phase 2: tokens in/out={p2['total_tokens_in']}/{p2['total_tokens_out']}  "
        f"avg_ms={p2['avg_duration_ms']}  runs={p2['phase2_runs']}  "
        f"no_ids_emitted={nie.get('total', 0)} "
        f"(silent={nie.get('silent_giveup', 0)} "
        f"declared={nie.get('declared_insufficient_evidence', 0)} "
        f"unclassified={nie.get('unclassified', 0)})"
    )
    print()
    print(
        f"R-IDs:  {pa['total_rids_hallucinated']}/{pa['total_rids_extracted']} "
        f"hallucinated ({pa['rid_hallucination_rate_pct']}%)"
    )
    print(
        f"ECs:    {pa['total_ecs_hallucinated']}/{pa['total_ecs_extracted']} "
        f"hallucinated ({pa['ec_hallucination_rate_pct']}%)"
    )
    overall_rate = 0.0
    total = pa["total_rids_extracted"] + pa["total_ecs_extracted"]
    if total:
        overall_rate = round(
            100.0 * (pa["total_rids_hallucinated"] + pa["total_ecs_hallucinated"]) / total,
            1,
        )
    print(f"Overall: {overall_rate}%   →  band: {_threshold_band(overall_rate)}")
    sr = agg.get("rid_substrate_relevance", {})
    if sr:
        print()
        print("Substrate-relevance (Phase 8.3.B):")
        print(
            f"  RIDs extracted: {sr['rids_extracted_total']}  "
            f"eligible (had step context): {sr['rids_eligible_for_substrate_check']}  "
            f"no-step-context: {sr['rids_no_step_context']}"
        )
        print(
            f"  Verdicts: full={sr['rids_fully_matching']}  "
            f"sub_only={sr['rids_substrate_only']}  "
            f"prod_only={sr['rids_product_only']}  "
            f"neither={sr['rids_neither']}  "
            f"rid_invalid={sr['rids_rid_invalid']}"
        )
        print(
            f"  Fully matching: {sr['rids_fully_matching_pct']}%  "
            f"Substrate-relevant: {sr['rids_substrate_relevant_pct']}%  "
            f"Real-but-wrong: {sr['rids_real_but_wrong_pct']}% "
            f"({sr['rids_real_but_wrong']}/{sr['rids_existence_verified_eligible']} verified eligible)"
        )
    ns = agg.get("nudge_stats", {})
    print(
        f"Nudges fired: {ns.get('total_nudges_fired', 0)}"
        f"  (across {ns.get('prompts_with_nudge', 0)} prompt(s))"
    )
    print(
        f"Step convention adherence: {agg['phase2_stats'].get('step_convention_ok', 0)}"
        f" / {agg['phase2_stats'].get('phase2_runs', 0)} phase-2 runs"
    )
    print()
    print("Per prompt:")
    for row in per_prompt:
        r_bad = sum(1 for r in row["rids"] if not r["verified"])
        e_bad = sum(1 for e in row["ecs"] if not e["verified"])
        nudge_tot = row.get("phase1_nudge_count", 0) + row.get("phase2_nudge_count", 0)
        step_ok = "Y" if row.get("step_convention_ok") else "N"
        status = row["status"]
        if row.get("no_ids_reason"):
            status = f"{status}:{row['no_ids_reason']}"
        print(
            f"  {row['id']:<22} status={status:<42}"
            f" step={step_ok}"
            f" nudges={nudge_tot}"
            f" rids={r_bad}/{len(row['rids'])}"
            f" ecs={e_bad}/{len(row['ecs'])}"
        )

    bad_rids: list[dict] = []
    bad_ecs: list[dict] = []
    for row in per_prompt:
        for r in row["rids"]:
            if not r["verified"] and len(bad_rids) < 3:
                bad_rids.append({"prompt": row["id"], **r})
        for e in row["ecs"]:
            if not e["verified"] and len(bad_ecs) < 3:
                bad_ecs.append({"prompt": row["id"], **e})
    if bad_rids:
        print()
        print("Example hallucinated R-IDs:")
        for r in bad_rids:
            print(f"  {r['id']}  ({r['prompt']}): {r['context'][:140]!r}")
    if bad_ecs:
        print()
        print("Example hallucinated ECs:")
        for e in bad_ecs:
            print(f"  EC {e['id']}  ({e['prompt']}): {e['context'][:140]!r}")


async def _run_all(prompts: list[dict], max_iterations: int) -> list[dict]:
    per_prompt: list[dict] = []
    for i, spec in enumerate(prompts, 1):
        log.info("=== [%d/%d] %s ===", i, len(prompts), spec["id"])
        per_prompt.append(await _run_one(spec, max_iterations))
    return per_prompt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids", type=str, default=None,
        help="comma-separated prompt IDs to run (default: all)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=8,
        help="agent loop cap per turn (default 8)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="explicit output path; default eval/results/pathway_hallucination_baseline_<ts>.json",
    )
    args = parser.parse_args()

    if not PROMPTS_PATH.is_file():
        log.error("prompts.json not found at %s", PROMPTS_PATH)
        return 1
    prompts = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        prompts = [p for p in prompts if p["id"] in wanted]
        if not prompts:
            log.error("no prompts match --ids=%s", args.ids)
            return 1

    per_prompt = asyncio.run(_run_all(prompts, args.max_iterations))
    agg = _aggregate(per_prompt)

    ts = timestamp_utc()
    payload = {
        "timestamp_utc": ts,
        "kind": "pathway_hallucination_baseline",
        "flow": "two_turn",
        "tier": "default",
        "phase1_stats": agg["phase1_stats"],
        "phase2_stats": agg["phase2_stats"],
        "pathway_accuracy": agg["pathway_accuracy"],
        "rid_substrate_relevance": agg.get("rid_substrate_relevance", {}),
        "per_prompt": per_prompt,
    }
    out_path = write_result(
        "pathway_hallucination_baseline",
        payload,
        output_path=Path(args.output) if args.output else None,
        ts=ts,
    )

    log.info("wrote %s", out_path)
    _print_summary(agg, per_prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
