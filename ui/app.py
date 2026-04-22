"""
MetaboAgent Gradio UI — single-column chat (fast default).

Layout:
- Header
- Showcase preset chips (optional — run a published-reference scenario)
- Chat thread
- Input row (textarea + Send + New chat)

The default flow is deliberately text-first so responses feel fast:
- No left rail, no right evidence rail, no bottom workflow strip.
- Agent actions (tool calls, reasoning) are shown inline in a compact
  visible "Actions" block while the turn is generating — not hidden in a
  collapsed ``<details>``.
- Final answers are returned as plain text with chemistry/LaTeX tokens
  normalized. Heavy post-processing (pathway flowcharts, confidence
  banners, citation chips, plan cards, right-rail evidence verification)
  is intentionally not on the default path; those helpers remain in this
  module for potential future advanced-mode use.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

import gradio as gr

from agent.metabo_agent import AgentBundle, build_agent, stream
from agent.rag import (
    CitationStatus,
    CitationType,
    CitationVerifier,
    default_chroma_verifier,
)
from agent.rag.citation_verifier import (
    _EC_RE as _VERIFIER_EC_RE,
    _KEGG_CPD_RE as _VERIFIER_KEGG_CPD_RE,
    _KEGG_RXN_RE as _VERIFIER_KEGG_RXN_RE,
    _PMID_RE as _VERIFIER_PMID_RE,
)
from config import UI_HOST, UI_PORT, UI_TITLE, get_log_path
from ui.theme import CUSTOM_CSS, make_theme

log = logging.getLogger(__name__)

_AGENT: AgentBundle | None = None
_VERIFIER: CitationVerifier | None = None
_VERIFIER_INIT_FAILED = False
_RESPONSE_LOG_NAME = "agent_responses.jsonl"
_SESSION_LOG_NAME = "agent_sessions.jsonl"


def _agent() -> AgentBundle:
    global _AGENT
    if _AGENT is None:
        log.info("Initializing MetaboAgent (loads PubMedBERT on CPU)…")
        _AGENT = build_agent()
    return _AGENT


def _verifier() -> CitationVerifier | None:
    """Build the Chroma-backed citation verifier once.

    Never raises — if Chroma is unavailable (or hasn't been populated), we
    fall back to a verifier with no lookups, which renders every citation
    as ``INFERRED``. That matches the pre-Phase-9 behaviour.
    """
    global _VERIFIER, _VERIFIER_INIT_FAILED
    if _VERIFIER is not None:
        return _VERIFIER
    if _VERIFIER_INIT_FAILED:
        return None
    try:
        _VERIFIER = default_chroma_verifier()
    except Exception as exc:  # noqa: BLE001
        log.warning("Citation verifier init failed (%s); chips unstamped.", exc)
        _VERIFIER_INIT_FAILED = True
        return None
    return _VERIFIER


# ---------- showcase scenarios (expected-vs-generated reference cards) ----------
SHOWCASE_SCENARIOS: dict[str, dict] = {
    "artemisinic": {
        "label": "Artemisinic acid",
        "tagline": "antimalarial precursor · S. cerevisiae",
        "query": (
            "Design a strain to produce artemisinic acid for antimalarial "
            "drug synthesis."
        ),
        "expected": {
            "Target": "Artemisinic acid (precursor of artemisinin)",
            "Host": "Saccharomyces cerevisiae",
            "Pathway": "Acetyl-CoA → MVA → FPP → amorpha-4,11-diene → artemisinic acid",
            "Key enzymes": "ADS (amorphadiene synthase), CYP71AV1, ALDH1, tHMG1↑, ERG9 knockdown",
            "Reference": "Ro et al. 2006 (PMID 16612385); Paddon et al. 2013 (PMID 23575629)",
        },
    },
    "taxadiene": {
        "label": "Taxadiene",
        "tagline": "Taxol precursor · E. coli",
        "query": (
            "Design a strain to produce taxadiene as a precursor to the "
            "anticancer drug Taxol."
        ),
        "expected": {
            "Target": "Taxa-4(5),11(12)-diene (Taxol precursor)",
            "Host": "Escherichia coli (engineered MEP)",
            "Pathway": "Pyruvate + G3P → MEP → IPP/DMAPP → GGPP → taxadiene",
            "Key enzymes": "GGPPS EC 2.5.1.29 (Pantoea ananatis), TASY EC 4.2.3.4 (Taxus), dxs/dxr/idi↑",
            "Reference": "Ajikumar et al. 2010 Science (PMID 20929886)",
        },
    },
    "vanillin": {
        "label": "Vanillin",
        "tagline": "green chemistry · E. coli",
        "query": (
            "Design a strain to produce vanillin from glucose as a sustainable "
            "alternative to petroleum synthesis."
        ),
        "expected": {
            "Target": "Vanillin (4-hydroxy-3-methoxybenzaldehyde)",
            "Host": "Escherichia coli or S. cerevisiae",
            "Pathway": "Glucose → shikimate → 3-dehydroshikimate → protocatechuate → vanillic acid → vanillin",
            "Key enzymes": "3-dehydroshikimate dehydratase (aroZ), OMT, ACAR — or vanAB (P. putida) alternate",
            "Reference": "Hansen et al. 2009 (PMID 19201962); Evolva/IFF commercial strains",
        },
    },
}


def _render_reference_card(scenario_key: str) -> str:
    """Compact collapsible published-reference block for showcase prompts."""
    s = SHOWCASE_SCENARIOS[scenario_key]
    rows = "".join(
        f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
        for k, v in s["expected"].items()
    )
    return (
        "<details class='reference-card'>"
        "<summary class='reference-card-summary'>"
        "<span class='reference-card-tag'>reference strain</span>"
        f"<span class='reference-card-title'>{html.escape(s['label'])}</span>"
        "<span class='reference-card-toggle'>expand</span>"
        "</summary>"
        "<div class='reference-card-body'>"
        f"<table class='reference-card-table'>{rows}</table>"
        "<div class='reference-card-hint'>Published reference for comparison. "
        "Use it as context, not as the final answer format.</div>"
        "</div>"
        "</details>"
    )


# ---------- blueprint / pathway extraction (inline rendering only) ----------
# Share the verifier's regexes so inline chip rendering and Phase-9 citation
# verification can never drift out of sync on what counts as a citation.
_KEGG_RXN_RE = _VERIFIER_KEGG_RXN_RE
_KEGG_CPD_RE = _VERIFIER_KEGG_CPD_RE
_EC_RE = _VERIFIER_EC_RE
_PMID_RE = _VERIFIER_PMID_RE
_CONFIDENCE_RE = re.compile(
    r"(?im)^\s*(?:\*\*)?Confidence(?:\*\*)?\s*[:\-]\s*"
    r"(?P<score>0?\.\d{1,2}|1\.0{1,2}|1)\s*(?:—|-|–)?\s*(?P<just>.*)$"
)
_ARROW_RE = re.compile(r"\s*(?:→|->|⟶|⇒|=>)\s*")
_STEP_SPLIT_RE = re.compile(
    r"(?im)^\s*(?:step|reaction)\s+(\d+)[\.:\)]?\s*|^\s*(\d+)[\.\)]\s+"
)
_PLASMID_RE = re.compile(r"<plasmid-map>(.+?)</plasmid-map>", re.DOTALL)
_COMPARE_RE = re.compile(r"<compare-table>(.+?)</compare-table>", re.DOTALL)
_PLAN_RE = re.compile(r"<plan>\s*(\{.+?\})\s*</plan>", re.DOTALL)
_TEX_ARROW_RE = re.compile(r"\$\\rightarrow\$|\\rightarrow")
_TEX_LEFT_RIGHT_ARROW_RE = re.compile(r"\$\\leftrightarrow\$|\\leftrightarrow")
_TEX_TEXT_SUB_RE = re.compile(r"\$\\text\{([^{}]+)\}_\{?(\d+)\}?\$")
_TEX_TEXT_SUP_SUB_RE = re.compile(r"\$\^\{?(\d+)\}?\\text\{([^{}]+)\}_\{?(\d+)\}?\$")
_TEX_PLAIN_SUB_RE = re.compile(r"\$([A-Za-z0-9()+\-\[\]]+)_\{?(\d+)\}?\$")
_TEX_PLAIN_SUP_SUB_RE = re.compile(r"\$\^\{?(\d+)\}?([A-Za-z0-9()+\-\[\]]+)_\{?(\d+)\}?\$")


_SUBSCRIPT_MAP = str.maketrans("0123456789+-=()n", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₙ")
_SUPERSCRIPT_MAP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")


def _parse_plan(final_answer: str) -> dict | None:
    """Extract the <plan> JSON block if the agent emitted one (Phase 1 response)."""
    import json as _json
    m = _PLAN_RE.search(final_answer)
    if not m:
        return None
    try:
        plan = _json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(plan, dict) or not isinstance(plan.get("approaches"), list):
        return None
    return plan


_DIFFICULTY_LABELS = {"low": "easy", "med": "medium", "medium": "medium", "high": "hard"}


def _render_plan_card(plan: dict) -> str:
    target = html.escape(str(plan.get("target") or "the target"))
    cards: list[str] = []
    for a in plan.get("approaches", []):
        if not isinstance(a, dict):
            continue
        aid = html.escape(str(a.get("id") or ""))
        title = html.escape(str(a.get("title") or "Approach"))
        route = html.escape(str(a.get("route") or "")).lower()
        host = html.escape(str(a.get("host") or ""))
        summary = html.escape(str(a.get("summary") or ""))
        diff_raw = str(a.get("est_difficulty") or "").lower()
        diff = html.escape(_DIFFICULTY_LABELS.get(diff_raw, diff_raw))
        conf = a.get("est_confidence")
        conf_txt = f"{float(conf):.2f}" if isinstance(conf, (int, float)) else ""
        badges = []
        if route:
            badges.append(f"<span class='plan-badge plan-badge-{route}'>{route}</span>")
        if host:
            badges.append(f"<span class='plan-badge plan-badge-host'>{host}</span>")
        if diff:
            badges.append(f"<span class='plan-badge plan-badge-diff'>{diff}</span>")
        if conf_txt:
            badges.append(f"<span class='plan-badge plan-badge-conf'>conf {conf_txt}</span>")
        cards.append(
            f"<button class='plan-card' data-approach-id='{aid}'>"
            f"<div class='plan-card-head'><span class='plan-card-id'>{aid}</span>"
            f"<span class='plan-card-title'>{title}</span></div>"
            f"<div class='plan-card-badges'>{''.join(badges)}</div>"
            f"<div class='plan-card-summary'>{summary}</div>"
            f"<div class='plan-card-action'>Select this approach →</div>"
            f"</button>"
        )
    return (
        "<div class='plan-wrap'>"
        f"<div class='plan-header'>Proposed approaches for <strong>{target}</strong></div>"
        f"<div class='plan-grid'>{''.join(cards)}</div>"
        "<div class='plan-hint'>Click an approach below (or type \"go with A\") to run the full design.</div>"
        "</div>"
    )


def _strip_plan(text: str) -> str:
    return _PLAN_RE.sub("", text).strip()


def _to_subscript(text: str) -> str:
    return text.translate(_SUBSCRIPT_MAP)


def _to_superscript(text: str) -> str:
    return text.translate(_SUPERSCRIPT_MAP)


def _normalize_latex_chemistry(text: str) -> str:
    """Convert common model-emitted TeX chemistry tokens into readable text.

    This is intentionally narrow. It fixes the frequent UI leaks such as
    ``$\\rightarrow$``, ``$^1\\text{O}_2$``, and ``$\\text{H}_2$`` without
    trying to become a full TeX renderer.
    """
    if not text:
        return text

    out = text
    out = _TEX_LEFT_RIGHT_ARROW_RE.sub("↔", out)
    out = _TEX_ARROW_RE.sub("→", out)

    out = _TEX_TEXT_SUP_SUB_RE.sub(
        lambda m: f"{_to_superscript(m.group(1))}{m.group(2)}{_to_subscript(m.group(3))}",
        out,
    )
    out = _TEX_PLAIN_SUP_SUB_RE.sub(
        lambda m: f"{_to_superscript(m.group(1))}{m.group(2)}{_to_subscript(m.group(3))}",
        out,
    )
    out = _TEX_TEXT_SUB_RE.sub(
        lambda m: f"{m.group(1)}{_to_subscript(m.group(2))}",
        out,
    )
    out = _TEX_PLAIN_SUB_RE.sub(
        lambda m: f"{m.group(1)}{_to_subscript(m.group(2))}",
        out,
    )

    # Last pass: strip math-mode markers around already-normalized content.
    out = out.replace("$", "")
    return out


def _snapshot_history(chat_history: list[dict]) -> list[dict]:
    """Return a fresh message list so Gradio sees updates immediately."""
    return [dict(msg) for msg in chat_history]


def _new_session_id() -> str:
    return uuid4().hex


def _history_for_log(chat_history: list[dict]) -> list[dict]:
    return [
        {
            "role": str(msg.get("role", "")),
            "content": str(msg.get("content", "")),
        }
        for msg in (chat_history or [])
    ]


def _append_response_log(
    *,
    user_msg: str,
    final_answer: str,
    rendered_answer: str,
    steps: list[dict],
    duration_ms: int,
    status: str,
    error: str = "",
) -> None:
    """Append one response event to the configured JSONL audit log.

    This is best-effort only. Logging must never break the chat flow.
    """
    try:
        log_path = get_log_path(_RESPONSE_LOG_NAME)
        record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "duration_ms": duration_ms,
            "user_msg": user_msg,
            "final_answer": final_answer,
            "rendered_answer": rendered_answer,
            "error": error,
            "step_count": len(steps),
            "tool_calls": [
                {
                    "tool": s.get("tool", ""),
                    "input": s.get("input", ""),
                    "output": s.get("output", ""),
                }
                for s in steps
                if s.get("kind") == "tool"
            ],
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        log.warning("response log append failed: %s", exc)


def _append_session_log(
    *,
    session_id: str,
    turn_index: int,
    user_msg: str,
    final_answer: str,
    chat_history: list[dict],
    status: str,
) -> None:
    """Append a session-scoped transcript snapshot to JSONL."""
    try:
        log_path = get_log_path(_SESSION_LOG_NAME)
        record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "turn_index": turn_index,
            "status": status,
            "user_msg": user_msg,
            "final_answer": final_answer,
            "message_count": len(chat_history or []),
            "chat_history": _history_for_log(chat_history),
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        log.warning("session log append failed: %s", exc)


def _extract_pathway_steps(final_answer: str) -> list[dict]:
    """Heuristic parse of ordered pathway steps."""
    blocks: list[str] = []
    anchors = list(_STEP_SPLIT_RE.finditer(final_answer))
    if len(anchors) >= 2:
        for i, m in enumerate(anchors):
            start = m.end()
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(final_answer)
            blocks.append(final_answer[start:end])
    else:
        for line in final_answer.splitlines():
            if _ARROW_RE.search(line):
                blocks.append(line)

    steps: list[dict] = []
    for block in blocks:
        ec = _EC_RE.search(block)
        rxn = _KEGG_RXN_RE.search(block)
        substrate, product = "", ""
        for line in block.splitlines():
            if _ARROW_RE.search(line):
                clean = re.sub(r"^[\s\-\*`_>]+", "", line).strip()
                clean = re.sub(r"[`_*]+", "", clean)
                parts = _ARROW_RE.split(clean, maxsplit=1)
                if len(parts) == 2:
                    substrate = parts[0].strip().rstrip(":,. ")
                    product = parts[1].strip().rstrip(":,. ")
                    trim_pat = re.compile(
                        r"\s{2,}|\s[\(\[]|\s+catalyz(?:ed|ing)\b|\s+by\s+the\s+enzyme\b",
                        re.IGNORECASE,
                    )
                    substrate = trim_pat.split(substrate)[0][:60].rstrip(":,. ")
                    product = trim_pat.split(product)[0][:60].rstrip(":,. ")
                    break

        enzyme = ""
        m = re.search(r"(?im)^\s*(?:-\s*)?Enzyme\s*[:\-]\s*(.+)$", block)
        if not m:
            m = re.search(r"(?i)catalyz(?:ed|ing)\s+by\s+([^\n.,;()]+)", block)
        if not m:
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("("):
                    continue
                if re.search(
                    r"(?i)\b(synthase|reductase|dehydrogenase|transferase|isomerase|"
                    r"hydrolase|ligase|lyase|oxidase|kinase|hydratase|decarboxylase|"
                    r"desaturase|cyclase|carboxylase)\b",
                    stripped,
                ):
                    if re.match(r"(?i)^\s*EC\s+\d", stripped):
                        continue
                    m = re.match(r"(.+)", stripped)
                    break
        if m:
            enzyme = m.group(1).strip().rstrip(".,;:)")[:80]
            enzyme = re.sub(r"^[-\*•\s`_]+", "", enzyme)
            if enzyme.count("(") > enzyme.count(")"):
                enzyme = enzyme.rsplit("(", 1)[0].rstrip()

        source_org = ""
        m = re.search(
            r"(?i)(?:from|source[:\s]+organism[:\s]+|organism[:\s]+|source[:\s]+)\s*"
            r"([A-Z][a-z]+(?:\s+[a-z]+){1,3})",
            block,
        )
        if m:
            source_org = m.group(1).strip()[:60]

        if not (substrate or ec or rxn):
            continue
        steps.append({
            "substrate": substrate, "product": product,
            "ec": ec.group(1) if ec else "",
            "rxn": rxn.group(0) if rxn else "",
            "enzyme": enzyme, "source": source_org,
        })
    return steps


def _render_pathway_flowchart(steps: list[dict]) -> str:
    if not steps:
        return ""
    nodes_html = []
    for idx, s in enumerate(steps, start=1):
        ec_link = (
            f"<a href='https://www.kegg.jp/entry/ec:{html.escape(s['ec'])}' "
            f"target='_blank' class='path-ec'>EC {html.escape(s['ec'])}</a>"
            if s["ec"] else ""
        )
        rxn_link = (
            f"<a href='https://www.kegg.jp/entry/{html.escape(s['rxn'])}' "
            f"target='_blank' class='path-rxn'>{html.escape(s['rxn'])}</a>"
            if s["rxn"] else ""
        )
        meta_html = "".join(x for x in (ec_link, rxn_link) if x)
        if s["substrate"] or s["product"]:
            rxn_text = (
                f"<span class='path-substrate'>{html.escape(s['substrate'] or '…')}</span>"
                f"<span class='path-arrow'>⟶</span>"
                f"<span class='path-product'>{html.escape(s['product'] or '…')}</span>"
            )
        else:
            rxn_text = "<span class='path-substrate'>(see text)</span>"
        enzyme_line = ""
        if s["enzyme"] or s["source"]:
            enz = html.escape(s["enzyme"]) if s["enzyme"] else ""
            src = f"<em>{html.escape(s['source'])}</em>" if s["source"] else ""
            sep = " · " if enz and src else ""
            enzyme_line = f"<div class='path-enzyme'>{enz}{sep}{src}</div>"
        nodes_html.append(
            f"<div class='path-node'>"
            f"<div class='path-step-num'>Step {idx}</div>"
            f"<div class='path-reaction'>{rxn_text}</div>"
            f"{enzyme_line}"
            + (f"<div class='path-meta'>{meta_html}</div>" if meta_html else "")
            + "</div>"
        )
    separator = "<div class='path-arrow-down'>▼</div>"
    return "<div class='pathway-flowchart'>" + separator.join(nodes_html) + "</div>"


def _confidence_banner(final_answer: str) -> str:
    m = _CONFIDENCE_RE.search(final_answer)
    if not m:
        return ""
    try:
        score = float(m.group("score"))
    except ValueError:
        return ""
    just = html.escape(m.group("just").strip().rstrip(".") or "—")
    tier = "high" if score >= 0.85 else "med" if score >= 0.65 else "low"
    return (
        f"<div class='confidence-banner confidence-{tier}'>"
        f"<span class='conf-label'>Confidence</span>"
        f"<span class='conf-score'>{score:.2f}</span>"
        f"<span class='conf-just'>{just}</span>"
        f"</div>"
    )


def _strip_confidence(text: str) -> str:
    return _CONFIDENCE_RE.sub("", text).rstrip()


def _render_citations(final_answer: str) -> str:
    rxns = sorted(set(_KEGG_RXN_RE.findall(final_answer)))
    cpds = sorted(set(_KEGG_CPD_RE.findall(final_answer)))
    ecs = sorted(set(_EC_RE.findall(final_answer)))
    pmids = sorted(set(_PMID_RE.findall(final_answer)))
    rows = []
    if rxns:
        rows.append(("KEGG reactions", ", ".join(
            f"<a href='https://www.kegg.jp/entry/{r}' target='_blank'><code>{r}</code></a>" for r in rxns)))
    if cpds:
        rows.append(("KEGG compounds", ", ".join(
            f"<a href='https://www.kegg.jp/entry/{c}' target='_blank'><code>{c}</code></a>" for c in cpds)))
    if ecs:
        rows.append(("EC numbers", ", ".join(
            f"<a href='https://www.kegg.jp/entry/ec:{e}' target='_blank'><code>EC {e}</code></a>" for e in ecs)))
    if pmids:
        rows.append(("PMIDs", ", ".join(
            f"<a href='https://pubmed.ncbi.nlm.nih.gov/{p}/' target='_blank'><code>{p}</code></a>" for p in pmids)))
    if not rows:
        return ""
    body = "".join(
        f"<tr><th>{label}</th><td>{val}</td></tr>" for label, val in rows
    )
    return f"<details><summary>references</summary><table>{body}</table></details>"


# ---------- right-rail evidence panel ----------
def _empty_evidence_panel() -> str:
    """Honest placeholder shown before the first agent answer."""
    return (
        "<div class='evidence-panel'>"
        "<div class='ev-header'>Evidence</div>"
        "<div class='ev-empty'>"
        "This panel will surface the confidence score, pathway summary, "
        "and citations from the agent's next answer."
        "</div>"
        "<div class='ev-footer'>"
        "database fact · literature · rule-based inference — labels coming "
        "as the RAG layer expands."
        "</div>"
        "</div>"
    )


def _confidence_score(text: str) -> tuple[float, str] | None:
    m = _CONFIDENCE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group("score")), m.group("just").strip().rstrip(".") or "—"
    except ValueError:
        return None


_STATUS_TOKEN = {
    CitationStatus.VERIFIED: "ok",
    CitationStatus.UNRESOLVED: "miss",
    CitationStatus.INFERRED: "?",
}
_STATUS_CLASS = {
    CitationStatus.VERIFIED: "ev-chip-verified",
    CitationStatus.UNRESOLVED: "ev-chip-unresolved",
    CitationStatus.INFERRED: "ev-chip-inferred",
}


def _verify_status_map(text: str) -> dict[tuple[CitationType, str], CitationStatus]:
    """Run the citation verifier against ``text`` and return a lookup map.

    Never raises. If the verifier is unavailable, every citation falls
    back to ``INFERRED`` below.
    """
    v = _verifier()
    if v is None:
        return {}
    try:
        results = v.verify_text(text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Citation verification failed: %s", exc)
        return {}
    return {(c.cite_type, c.value): c.status for c in results}


def _render_evidence_panel(final_answer: str) -> str:
    """Right-rail panel — confidence + pathway step count + citations.

    Reuses the same extraction helpers as the inline bubble so the two
    views never disagree about what's supported. Phase 9: every citation
    chip is stamped verified / unresolved / inferred via the citation
    verifier.
    """
    conf = _confidence_score(final_answer)
    steps = _extract_pathway_steps(final_answer)
    rxns = sorted(set(_KEGG_RXN_RE.findall(final_answer)))
    cpds = sorted(set(_KEGG_CPD_RE.findall(final_answer)))
    ecs = sorted(set(_EC_RE.findall(final_answer)))
    pmids = sorted(set(_PMID_RE.findall(final_answer)))

    if not (conf or steps or rxns or cpds or ecs or pmids):
        return _empty_evidence_panel()

    status_map = _verify_status_map(final_answer)

    sections: list[str] = []

    if conf is not None:
        score, just = conf
        tier = "high" if score >= 0.85 else "med" if score >= 0.65 else "low"
        sections.append(
            "<div class='ev-section ev-conf'>"
            "<div class='ev-section-head'>Confidence</div>"
            f"<div class='ev-conf-score ev-conf-{tier}'>{score:.2f}</div>"
            f"<div class='ev-conf-just'>{html.escape(just)}</div>"
            "</div>"
        )

    if steps:
        sections.append(
            "<div class='ev-section'>"
            "<div class='ev-section-head'>Pathway</div>"
            f"<div class='ev-stat'>{len(steps)} step"
            f"{'s' if len(steps) != 1 else ''} detected</div>"
            "<div class='ev-hint'>Flowchart renders inline in the main panel.</div>"
            "</div>"
        )

    def _chip(label: str, href: str, kind: CitationType, value: str) -> str:
        status = status_map.get((kind, value), CitationStatus.INFERRED)
        css = _STATUS_CLASS[status]
        tag = _STATUS_TOKEN[status]
        title = f"{status.value}: {kind.value} {value}"
        return (
            f"<a class='ev-chip {css}' href='{html.escape(href)}' "
            f"target='_blank' title='{html.escape(title)}'>"
            f"<code>{html.escape(label)}</code>"
            f"<span class='ev-chip-status'>{tag}</span></a>"
        )

    citation_rows: list[str] = []
    if rxns:
        citation_rows.append(
            "<div class='ev-cite-row'><span class='ev-cite-label'>KEGG rxn</span>"
            + "".join(_chip(r, f"https://www.kegg.jp/entry/{r}",
                            CitationType.KEGG_REACTION, r) for r in rxns)
            + "</div>"
        )
    if cpds:
        citation_rows.append(
            "<div class='ev-cite-row'><span class='ev-cite-label'>KEGG cpd</span>"
            + "".join(_chip(c, f"https://www.kegg.jp/entry/{c}",
                            CitationType.KEGG_COMPOUND, c) for c in cpds)
            + "</div>"
        )
    if ecs:
        citation_rows.append(
            "<div class='ev-cite-row'><span class='ev-cite-label'>EC</span>"
            + "".join(_chip(f"EC {e}", f"https://www.kegg.jp/entry/ec:{e}",
                            CitationType.EC_NUMBER, e) for e in ecs)
            + "</div>"
        )
    if pmids:
        citation_rows.append(
            "<div class='ev-cite-row'><span class='ev-cite-label'>PMID</span>"
            + "".join(_chip(p, f"https://pubmed.ncbi.nlm.nih.gov/{p}/",
                            CitationType.PMID, p) for p in pmids)
            + "</div>"
        )
    if citation_rows:
        # Per-status tally over all chips we're about to render.
        totals = {s: 0 for s in CitationStatus}
        for kind, values in (
            (CitationType.KEGG_REACTION, rxns),
            (CitationType.KEGG_COMPOUND, cpds),
            (CitationType.EC_NUMBER, ecs),
            (CitationType.PMID, pmids),
        ):
            for v in values:
                totals[status_map.get((kind, v), CitationStatus.INFERRED)] += 1
        summary = (
            "<div class='ev-verify-summary'>"
            + "".join(
                f"<span><span class='ev-verify-dot ev-verify-dot-{s.value}'></span>"
                f"{totals[s]} {s.value}</span>"
                for s in CitationStatus if totals[s]
            )
            + "</div>"
        )
        sections.append(
            "<div class='ev-section'>"
            "<div class='ev-section-head'>Citations</div>"
            + summary
            + "".join(citation_rows)
            + "</div>"
        )

    return (
        "<div class='evidence-panel evidence-panel-live'>"
        "<div class='ev-header'>Evidence</div>"
        + "".join(sections) +
        "<div class='ev-footer'>Citations stamped verified · unresolved · "
        "inferred via the Phase-9 verifier.</div>"
        "</div>"
    )


def _format_assistant_message(final_answer: str) -> str:
    """Fast default: normalize chemistry markup and strip embedded command
    blocks (``<plan>`` / ``<plasmid-map>`` / ``<compare-table>`` / the
    confidence line). Returns plain text suitable for a chat bubble — no
    pathway flowchart, no citation chips, no plan card. The heavier
    renderers remain in this module for potential future advanced mode."""
    text = _normalize_latex_chemistry(final_answer)
    text = _strip_plan(text)
    text = _PLASMID_RE.sub("", text)
    text = _COMPARE_RE.sub("", text)
    text = _strip_confidence(text)
    return text.strip()


# ---------- handlers ----------
_THOUGHT_RE_STRIP = re.compile(r"(?is)Action:\s*.*?(?=\nObservation:|\Z)")


def _snippet(text: str, limit: int = 240) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


_MAX_INLINE_STEPS = 12  # cap visible action rows so the bubble doesn't balloon


def _tool_progress_label(tool_name: str) -> str:
    t = (tool_name or "").lower()
    if any(k in t for k in ("pubmed", "literature", "paper", "pmid")):
        return "Retrieving references"
    if any(k in t for k in ("pathway", "kegg", "reaction", "route", "retro")):
        return "Checking pathway"
    if any(k in t for k in ("enzyme", "uniprot", "ec_", "brenda")):
        return "Validating enzymes"
    if any(k in t for k in ("strain", "design", "host", "construct")):
        return "Drafting strain design"
    return "Working"


def _progress_status_label(
    steps: list[dict],
    *,
    status_hint: str | None = None,
    finalizing: bool = False,
) -> str:
    if finalizing:
        return "Finalizing response"
    for s in reversed(steps):
        if s.get("kind") == "tool":
            return _tool_progress_label(s.get("tool", ""))
        if s.get("kind") == "thought":
            return "Planning response"
    return status_hint or "Thinking"


def _render_stream_preview(text: str) -> str:
    if not text:
        return ""
    escaped = html.escape(_normalize_latex_chemistry(text)).replace("\n", "<br/>")
    return f"<div class='stream-preview'>{escaped}<span class='stream-caret'>▍</span></div>"


def _chunk_final_text(text: str, target_chars: int = 220) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        add_len = len(word) + (1 if current else 0)
        if current and current_len + add_len > target_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += add_len
    if current:
        chunks.append(" ".join(current))
    return chunks


def _render_progress(
    steps: list[dict], spinner: bool = True, status_hint: str | None = None
) -> str:
    """Compact visible inline status + action rows (default UI).

    Shows a pulsing dot + current status, then a small "Actions" block
    listing recent tool calls / reasoning beats. No collapsed ``<details>``
    — the user should see what the agent is doing without a click.
    """
    last_status = _progress_status_label(steps, status_hint=status_hint)

    head = ""
    if spinner:
        head = (
            "<div class='trace-head'>"
            "<span class='trace-dots'>"
            "<span class='trace-dot'></span>"
            "<span class='trace-dot'></span>"
            "<span class='trace-dot'></span>"
            "</span>"
            f"<span class='trace-status'>{html.escape(last_status)}</span>"
            "</div>"
        )

    visible_steps = steps[-_MAX_INLINE_STEPS:]
    overflow = len(steps) - len(visible_steps)

    rows: list[str] = []
    if overflow > 0:
        rows.append(
            f"<div class='act-row act-more'>"
            f"<span class='act-tag'>···</span>"
            f"<span class='act-body'>{overflow} earlier step"
            f"{'s' if overflow != 1 else ''}</span>"
            f"</div>"
        )
    for s in visible_steps:
        kind = s.get("kind")
        if kind == "tool":
            tool = html.escape(s.get("tool", "?"))
            args = html.escape(_snippet(s.get("input", ""), 90))
            rows.append(
                "<div class='act-row act-tool'>"
                "<span class='act-tag'>tool</span>"
                f"<span class='act-body'><code>{tool}</code>"
                f" <span class='act-args'>{args}</span></span>"
                "</div>"
            )
        elif kind == "thought":
            body = _snippet(s.get("text", ""), 160)
            if body:
                rows.append(
                    "<div class='act-row act-thought'>"
                    "<span class='act-tag'>think</span>"
                    f"<span class='act-body'>{html.escape(body)}</span>"
                    "</div>"
                )

    actions = ""
    if rows:
        actions = (
            "<div class='actions-inline'>"
            "<div class='actions-label'>Actions</div>"
            + "".join(rows)
            + "</div>"
        )

    return "<div class='trace'>" + head + actions + "</div>"


def _render_streaming_message(partial_text: str, steps: list[dict], *, status: str) -> str:
    return (
        "<div class='assistant-live'>"
        + _render_progress(steps, spinner=True, status_hint=status)
        + _render_stream_preview(partial_text)
        + "</div>"
    )


import time

_YIELD_THROTTLE_SECS = 0.4   # coalesce UI refreshes so streaming doesn't spam


def _run_agent(
    user_msg: str,
    chat_history: list,
    session_id: str,
    *,
    preamble: list[dict] | None = None,
):
    """Shared generator. Yields ``(chat_history, input_update, session_id)``.

    The pending assistant bubble is appended immediately and updated in
    place on every throttled event — it never disappears while generating.
    """
    preamble = preamble or []
    session_id = session_id or _new_session_id()
    prior_history = list(chat_history or [])
    turn_index = sum(1 for msg in prior_history if msg.get("role") == "user") + 1
    chat_history = prior_history + [
        {"role": "user", "content": user_msg},
        *preamble,
        {
            "role": "assistant",
            "content": _render_progress(
                [],
                spinner=True,
                status_hint=(
                    "warming up local models"
                    if _AGENT is None else
                    "starting response"
                ),
            ),
        },
    ]
    # The agent sees only turns BEFORE this one — the current user_msg is
    # passed separately to stream(). Preamble assistant blocks (reference
    # card) are UI-only, never shown to the LLM.
    agent_history = prior_history

    yield _snapshot_history(chat_history), gr.update(value=""), session_id

    steps: list[dict] = []
    final_answer = ""
    run_started = time.monotonic()
    last_yield = 0.0
    try:
        agent = _agent()
        for ev in stream(agent, user_msg, history=agent_history):
            t = ev.get("type")
            if t == "thought":
                reasoning = _THOUGHT_RE_STRIP.sub("", ev.get("content", "")).strip()
                if reasoning:
                    steps.append({"kind": "thought", "text": reasoning})
            elif t == "tool":
                steps.append({
                    "kind": "tool",
                    "tool": ev.get("tool", ""),
                    "input": ev.get("input", ""),
                    "output": ev.get("output", ""),
                })
            elif t == "final":
                final_answer = ev.get("content", "")
                break
            now = time.monotonic()
            if now - last_yield >= _YIELD_THROTTLE_SECS:
                chat_history[-1]["content"] = _render_progress(
                    steps,
                    spinner=True,
                    status_hint=_progress_status_label(steps),
                )
                last_yield = now
                yield _snapshot_history(chat_history), gr.update(), session_id
    except Exception as e:  # noqa: BLE001
        log.exception("Agent run failed")
        error_text = f"**Something went wrong:** {html.escape(str(e))}"
        chat_history[-1]["content"] = error_text
        _append_response_log(
            user_msg=user_msg,
            final_answer="",
            rendered_answer=error_text,
            steps=steps,
            duration_ms=int((time.monotonic() - run_started) * 1000),
            status="error",
            error=str(e),
        )
        _append_session_log(
            session_id=session_id,
            turn_index=turn_index,
            user_msg=user_msg,
            final_answer="",
            chat_history=_snapshot_history(chat_history),
            status="error",
        )
        yield _snapshot_history(chat_history), gr.update(), session_id
        return

    if not final_answer:
        final_answer = next(
            (s["text"] for s in reversed(steps) if s["kind"] == "thought"),
            "(no answer — check the server log)",
        )

    preview_chunks = _chunk_final_text(final_answer)
    if preview_chunks:
        partial = ""
        for chunk in preview_chunks:
            partial = (partial + " " + chunk).strip()
            chat_history[-1]["content"] = _render_streaming_message(
                partial,
                steps,
                status="Finalizing response",
            )
            yield _snapshot_history(chat_history), gr.update(), session_id
            time.sleep(0.03)

    rendered = _format_assistant_message(final_answer)
    chat_history[-1]["content"] = rendered
    _append_response_log(
        user_msg=user_msg,
        final_answer=final_answer,
        rendered_answer=chat_history[-1]["content"],
        steps=steps,
        duration_ms=int((time.monotonic() - run_started) * 1000),
        status="ok",
    )
    _append_session_log(
        session_id=session_id,
        turn_index=turn_index,
        user_msg=user_msg,
        final_answer=final_answer,
        chat_history=_snapshot_history(chat_history),
        status="ok",
    )
    yield _snapshot_history(chat_history), gr.update(), session_id


def on_submit(user_msg: str, chat_history: list, session_state: str):
    user_msg = (user_msg or "").strip()
    if not user_msg:
        yield chat_history, gr.update(), session_state or _new_session_id()
        return
    yield from _run_agent(user_msg, chat_history, session_state)


def on_showcase(scenario_key: str, chat_history: list, session_state: str):
    scenario = SHOWCASE_SCENARIOS.get(scenario_key)
    if scenario is None:
        yield chat_history, gr.update(), session_state or _new_session_id()
        return
    preamble = [{"role": "assistant", "content": _render_reference_card(scenario_key)}]
    yield from _run_agent(scenario["query"], chat_history, session_state, preamble=preamble)


def on_clear():
    return [], "", _new_session_id()


# ---------- page ----------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title=UI_TITLE) as demo:
        gr.HTML("""
            <div class='app-header'>
                <div class='app-title'><span class='dot'></span>MetaboAgent</div>
                <div class='app-subtitle'>biochemistry · metabolic engineering · synthetic biology</div>
            </div>
        """)

        with gr.Row(elem_classes=["showcase-row"]):
            gr.HTML(
                "<div class='showcase-label'>Showcase demos — "
                "click to run against a published reference strain</div>"
            )
        with gr.Row(elem_classes=["showcase-chips"]):
            showcase_buttons: dict[str, gr.Button] = {}
            for key, s in SHOWCASE_SCENARIOS.items():
                btn = gr.Button(
                    f"{s['label']}  ·  {s['tagline']}",
                    elem_classes=["showcase-chip"],
                    scale=1,
                )
                showcase_buttons[key] = btn

        chatbot = gr.Chatbot(
            height=620,
            elem_classes=["chat-thread"],
            avatar_images=(None, None),
            sanitize_html=False,
            render_markdown=True,
            show_label=False,
            group_consecutive_messages=False,
            placeholder=(
                "<div style='text-align:center;color:#8A8A93;"
                "font-family:Inter,sans-serif;padding:2.6rem 1rem'>"
                "Ask anything about microbes, pathways, enzymes, or synthesis.<br/>"
                "<span style='font-size:0.85rem'>"
                "Try: <em>how could we make aspirin cheaper using microbes?</em><br/>"
                "or <em>tell me about vanillin production</em> · "
                "<em>what enzymes make lycopene?</em>"
                "</span></div>"
            ),
        )

        session_state = gr.State(value=_new_session_id())

        with gr.Row(elem_classes=["input-row"]):
            user_input = gr.Textbox(
                placeholder="Message MetaboAgent…",
                show_label=False,
                lines=1,
                max_lines=6,
                scale=9,
                autofocus=True,
                container=False,
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)
            clear_btn = gr.Button("New chat", variant="secondary", scale=1)

        submit_outputs = [chatbot, user_input, session_state]
        clear_outputs = [chatbot, user_input, session_state]

        send_btn.click(on_submit, inputs=[user_input, chatbot, session_state], outputs=submit_outputs)
        user_input.submit(on_submit, inputs=[user_input, chatbot, session_state], outputs=submit_outputs)
        clear_btn.click(on_clear, outputs=clear_outputs)

        for key, btn in showcase_buttons.items():
            btn.click(
                lambda chat, sid, k=key: (yield from on_showcase(k, chat, sid)),
                inputs=[chatbot, session_state],
                outputs=submit_outputs,
            )

    return demo


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    demo = build_ui()
    demo.queue().launch(
        server_name=UI_HOST,
        server_port=UI_PORT,
        theme=make_theme(),
        css=CUSTOM_CSS,
        inbrowser=False,
        share=False,
    )


if __name__ == "__main__":
    main()
