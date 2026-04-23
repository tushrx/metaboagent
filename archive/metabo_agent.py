"""
MetaboAgent — manual ReAct loop against Gemma 4 31B-IT via vLLM.

The vLLM server is running without --enable-auto-tool-choice, so we can't use
native OpenAI tool calling. Instead we prompt Gemma 4 with a ReAct scaffold
and parse "Action:" / "Action Input:" text blocks ourselves.

Tools available: search_kegg, search_literature, plan_retrosynthesis, rank_enzymes.

Usage
    from agent.metabo_agent import build_agent, run
    agent = build_agent()
    result = run(agent, "What enzymes catalyze GGPP -> lycopene?")
    print(result["answer"])
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.prompts.system_prompt import SYSTEM_PROMPT
from agent.router import TASK_REACT_LOOP, build_llm_for
from agent.tools import (
    compare_synthesis_routes as compare_routes,
    design_expression_vector as design_vector,
    design_primers as design_primers_mod,
    enzyme_ranker,
    fetch_gene_sequence as fetch_gene_seq,
    fetch_kegg_live,
    fetch_pubchem,
    fetch_pubmed_live,
    fetch_sabio_rk,
    fetch_uniprot,
    fetch_zinc,
    kegg_search,
    literature_search,
    retrosynthesis,
    web_search as web_search_mod,
)
from config import (
    AGENT_MAX_ITERATIONS,
    AGENT_VERBOSE,
)
from vectorstore.retriever import Retriever

log = logging.getLogger(__name__)


_REACT_INSTRUCTIONS = """
## Tools
You have ten tools. Call them by name and pass a JSON object as Action Input.

### Indexed (fast, local knowledge base)
- search_kegg(query, filter_type, filter_value, top_k)
    filter_type ∈ {"ec_number", "compound_id", "pathway_id", "none"}.
    Use for KEGG reaction/compound lookup.

- search_literature(query, max_results, mesh_term)
    Semantic search over PubMed abstracts and KEGG pathway text.

- plan_retrosynthesis(target_compound_id, host_organism)
    Backward-chain a pathway. target_compound_id is a KEGG compound id like "C05432".
    host_organism ∈ {"ecoli", "scerevisiae", "cglutamicum", "bsubtilis", "pputida"}.

- rank_enzymes(ec_number, host_organism, top_k)
    Rank candidate enzymes for an EC number (no "EC " prefix).

### Live (online REST; slower — use when local search returns empty or needs enrichment)
- fetch_pubchem(compound_name_or_cid)
    PubChem compound data (SMILES, MW, logP, synonyms). Good for non-KEGG
    compounds or when the molecule is a drug / drug-like target.

- fetch_zinc(compound_name_or_zinc_id)
    ZINC15 substance lookup with commercial-availability info (vendors,
    purchasability). Use after choosing a target to check if it is
    purchasable off-the-shelf as a reference standard.

- fetch_uniprot(protein_name_or_ec, organism)
    UniProt (reviewed) protein entries: accession, sequence length, function,
    active-site features, KEGG/PDB/BRENDA cross-refs. Use when you need the
    *protein* behind an EC number or a curated ortholog for a host.

- fetch_pubmed_live(query, max_results)
    Real-time PubMed search (E-utilities). Use only when search_literature
    came back empty or you need the *latest* papers on a topic.

- fetch_kegg_live(entity_id)
    Direct KEGG REST lookup for any entity (reaction, compound, enzyme,
    pathway). Use when an ID isn't in the indexed snapshot or for
    organism-specific pathways (e.g. "eco00010").

- fetch_sabio_rk(ec_number, organism, max_results)
    SABIO-RK enzyme-kinetics records (Km, kcat, Ki with source PMIDs). Use to
    refine rank_enzymes when catalytic-efficiency numbers matter.

- web_search(query, max_results)
    Open-web search via DuckDuckGo (no API key). Use when the indexed corpus
    and PubMed are thin — e.g. for recent industrial/commercial-strain news,
    patent summaries, green-chemistry case studies, or general chemistry
    references outside the biomedical literature. Returns title/url/snippet
    JSON; cite the URL in your Final Answer.

All live-fetch results are automatically indexed — follow-up semantic
searches in the same session will find them.

### Reasoning scaffolds
- compare_synthesis_routes(target, top_k)
    Build a side-by-side microbial-vs-chemical synthesis comparison scaffold.
    Returns literature evidence for both routes and a comparison template with
    canonical columns (feedstock, yield, waste, scalability, cost, ...). You
    must populate each cell using only the supplied evidence — never invent
    yields or costs. When you emit the Final Answer, wrap the comparison as
    an HTML table inside `<compare-table>...</compare-table>` so the UI can
    render it as a styled side-by-side comparison.

### Cloning / vector design (molecular biology automation)
- fetch_gene_sequence(gene_or_accession, organism)
    Retrieve a CDS / nucleotide sequence from NCBI nuccore — accepts an
    accession or gene symbol + organism. Use this before design_primers.

- design_expression_vector(target_gene, host, promoter_strength)
    Recommend a plasmid backbone + promoter + RBS + tag + selection +
    terminator for a host (ecoli, scerevisiae, cglutamicum, bsubtilis,
    pputida). promoter_strength ∈ {"low", "med", "high"}. Returns a
    plasmid-map SVG — include the raw SVG inside `<plasmid-map>...</plasmid-map>`
    in your Final Answer so the UI can render it.

- design_primers(gene_sequence, tm_target, cloning_strategy, re_enzyme,
                 vector_upstream_flank, vector_downstream_flank)
    Design forward/reverse cloning primers with Tm-targeted bodies and either
    Gibson homology arms (default) or restriction-site overhangs. Requires a
    DNA sequence — call fetch_gene_sequence first if you don't already have
    one.

## ReAct Format — follow EXACTLY
Thought: <your reasoning>
Action: <one of: search_kegg | search_literature | plan_retrosynthesis | rank_enzymes | fetch_pubchem | fetch_zinc | fetch_uniprot | fetch_pubmed_live | fetch_kegg_live | fetch_sabio_rk | web_search | compare_synthesis_routes | fetch_gene_sequence | design_expression_vector | design_primers>
Action Input: <JSON object, one line>

After each Action, the system will append:
Observation: <tool result>

When you have enough evidence, output exactly:
Thought: I now have enough information.
Final Answer: <your answer with KEGG IDs and PMIDs as citations>

Never invent tool outputs. Only call tools listed above.

## Do NOT repeat yourself
Before issuing any Action, read the "Prior tool calls this turn" list that the
system maintains for you. These rules are strict:
1. NEVER call the same tool with arguments equivalent to a prior call that
   already returned non-empty results — use those results.
2. If a previous call returned empty or error results, your next call MUST
   differ meaningfully: change the filter_type, rewrite the query with
   different keywords (not synonyms of the same phrase), or switch tools.
3. After 2 failed attempts at the same lookup, stop retrying and state in your
   Thought what evidence is missing, then proceed with the best available data.
4. If you notice yourself about to repeat, emit Final Answer instead with the
   evidence you have and an honest confidence score.
"""

# Rendering-side config for the "prior tool calls" memo.
PRIOR_CALLS_MAX = 6  # cap injected recap to last-N entries
PRIOR_CALL_INPUT_CHARS = 160
PRIOR_CALL_OUTPUT_CHARS = 220


def _summarize_prior_call(step: dict) -> str:
    """One-line recap of a tool call for the LLM's short-term memory."""
    tool = step.get("tool", "?")
    args = str(step.get("input", ""))[:PRIOR_CALL_INPUT_CHARS]
    out = str(step.get("output", ""))
    # Compress whitespace so the recap stays on one line.
    out = " ".join(out.split())
    # Flag empty/error results so the LLM knows not to retry identically.
    if not out.strip():
        tag = "EMPTY"
    elif out.lstrip().startswith("ERROR"):
        tag = "ERROR"
    else:
        tag = "OK"
    out = out[:PRIOR_CALL_OUTPUT_CHARS]
    return f"- [{tag}] {tool}({args}) → {out}"


def _prior_calls_memo(steps: list[dict]) -> str:
    if not steps:
        return ""
    recent = steps[-PRIOR_CALLS_MAX:]
    lines = [_summarize_prior_call(s) for s in recent]
    header = (
        f"Prior tool calls this turn ({len(recent)} of {len(steps)} shown). "
        "Do NOT repeat any OK call with equivalent arguments; for EMPTY/ERROR "
        "calls change approach rather than retrying."
    )
    return header + "\n" + "\n".join(lines)

_ACTION_NAME_RE = re.compile(r"Action:\s*(?P<tool>[a-zA-Z_][a-zA-Z0-9_]*)")
_ACTION_INPUT_RE = re.compile(r"Action Input:\s*(?P<args>.+)", re.DOTALL)
_FINAL_RE = re.compile(r"Final Answer:\s*(.+)", re.DOTALL)


def _parse_action(text: str):
    name_m = _ACTION_NAME_RE.search(text)
    if not name_m:
        return None
    # Take everything after "Action Input:" up to the next blank line or end.
    remainder = text[name_m.end():]
    input_m = _ACTION_INPUT_RE.search(remainder)
    if not input_m:
        return None
    args = input_m.group("args")
    # Trim at first "Observation:" or "Thought:" or double newline if any leaked through.
    for stop in ("\nObservation:", "\nThought:", "\nFinal Answer:"):
        idx = args.find(stop)
        if idx != -1:
            args = args[:idx]
    return name_m.group("tool"), args.strip()


@dataclass
class AgentBundle:
    llm: ChatOpenAI
    tools: dict
    max_iters: int = AGENT_MAX_ITERATIONS
    verbose: bool = AGENT_VERBOSE
    system_prompt: str = field(default=SYSTEM_PROMPT + _REACT_INSTRUCTIONS)


def build_llm() -> ChatOpenAI:
    """Return the LLM used for the orchestrator ReAct loop.

    Routed through ``agent.router`` so a utility model (if configured) can
    later be used for sub-tasks. The ReAct loop itself always runs on the
    primary model — see ``agent/router.py`` for the policy.
    """
    return build_llm_for(TASK_REACT_LOOP)


def build_tools(retriever: Retriever | None = None) -> dict:
    if retriever is not None:
        kegg_search.set_retriever(retriever)
    return {
        # indexed (local RAG)
        "search_kegg": kegg_search.search_kegg,
        "search_literature": literature_search.search_literature,
        "plan_retrosynthesis": retrosynthesis.plan_retrosynthesis,
        "rank_enzymes": enzyme_ranker.rank_enzymes,
        # live (online REST — results auto-indexed)
        "fetch_pubchem": fetch_pubchem.fetch_pubchem,
        "fetch_zinc": fetch_zinc.fetch_zinc,
        "fetch_uniprot": fetch_uniprot.fetch_uniprot,
        "fetch_pubmed_live": fetch_pubmed_live.fetch_pubmed_live,
        "fetch_kegg_live": fetch_kegg_live.fetch_kegg_live,
        "fetch_sabio_rk": fetch_sabio_rk.fetch_sabio_rk,
        # open-web retrieval (DuckDuckGo, no key)
        "web_search": web_search_mod.web_search,
        # comparison / synthesis reasoning scaffolds
        "compare_synthesis_routes": compare_routes.compare_synthesis_routes,
        # vector / primer design (molecular biology automation)
        "fetch_gene_sequence": fetch_gene_seq.fetch_gene_sequence,
        "design_expression_vector": design_vector.design_expression_vector,
        "design_primers": design_primers_mod.design_primers,
    }


def build_agent(retriever: Retriever | None = None, llm: ChatOpenAI | None = None) -> AgentBundle:
    retriever = retriever or Retriever()
    return AgentBundle(llm=llm or build_llm(), tools=build_tools(retriever))


# ---------- ReAct loop ----------
def _invoke_tool(tools: dict, name: str, args_text: str) -> str:
    if name not in tools:
        return f"ERROR: unknown tool '{name}'. Valid: {list(tools)}"
    args = _coerce_args(args_text)
    try:
        # @tool-decorated callables expose .invoke(dict) in langchain 1.x
        return tools[name].invoke(args)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: tool '{name}' failed: {e}"


def _coerce_args(text: str):
    text = text.strip().strip("`")
    # Strip a leading language tag like "json\n{...}"
    if text.lower().startswith("json"):
        text = text.split("\n", 1)[1] if "\n" in text else text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract the first {...} block
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"query": text}  # last-ditch: pass whole string as query


def _call_signature(tool: str, args_text: str) -> str:
    """Canonical key for detecting equivalent repeat calls."""
    try:
        args = _coerce_args(args_text)
        canon = json.dumps(args, sort_keys=True, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        canon = " ".join(args_text.split()).lower()
    return f"{tool}::{canon}"


def _coerce_chat_content(content) -> str:
    """Normalize a Gradio Chatbot `content` field into a flat string.

    Gradio 6's messages format may deliver content as:
      * a plain string,
      * a list of multimodal parts ([{"type": "text", "content": "..."}, ...]),
      * a dict with a "text" or "content" key,
      * None.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                t = p.get("text") or p.get("content")
                if t:
                    parts.append(str(t))
            elif isinstance(p, str):
                parts.append(p)
        return " ".join(parts)
    if isinstance(content, dict):
        t = content.get("text") or content.get("content")
        return str(t) if t else ""
    return str(content)


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PLAN_BLOCK_RE = re.compile(r"<plan>.*?</plan>", re.DOTALL | re.IGNORECASE)
_DROP_BLOCK_RE = re.compile(
    r"<(?:plasmid-map|compare-table|details|div|details)[^>]*>.*?"
    r"</(?:plasmid-map|compare-table|details|div)>",
    re.DOTALL | re.IGNORECASE,
)
_WS_RE = re.compile(r"[ \t]+")


def _clean_assistant_for_history(text: str) -> str:
    """Strip UI-only HTML blocks (trace, plan, plasmid SVG, compare-table, details)
    so the LLM sees a compact prose version of its prior answer. Otherwise the
    model sees its own HTML scaffold and gets confused ("I already answered")."""
    text = _PLAN_BLOCK_RE.sub("", text)
    text = _DROP_BLOCK_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    # Collapse consecutive blank lines.
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _build_history_messages(history: list[dict] | None) -> list:
    """Convert a chat history (list of {role: user|assistant, content}) into
    LangChain messages prefixed before the current query.

    Assistant turns are collapsed to only the final answer (we don't replay
    chains-of-thought / tool calls — those would confuse the ReAct parser).
    """
    msgs = []
    if not history:
        return msgs
    for turn in history:
        role = turn.get("role")
        content = _coerce_chat_content(turn.get("content")).strip()
        if not content:
            continue
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            cleaned = _clean_assistant_for_history(content)
            if cleaned:
                msgs.append(AIMessage(content=cleaned))
    return msgs


def run(agent: AgentBundle, query: str, history: list[dict] | None = None) -> dict:
    messages = [SystemMessage(content=agent.system_prompt)]
    messages.extend(_build_history_messages(history))
    messages.append(HumanMessage(content=query))
    steps: list[dict] = []
    successful_sigs: set[str] = set()
    final = ""
    transcript = ""
    text = ""

    for i in range(agent.max_iters):
        stop = ["\nObservation:"]
        resp = agent.llm.invoke(messages, stop=stop)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        transcript += text
        if agent.verbose:
            log.info("--- iter %d LLM ---\n%s", i, text)

        final_m = _FINAL_RE.search(text)
        if final_m:
            final = final_m.group(1).strip()
            break

        parsed = _parse_action(text)
        if not parsed:
            messages.append(AIMessage(content=text))
            messages.append(HumanMessage(
                content="You must either call a tool (Action: / Action Input:) or emit a Final Answer."))
            continue
        tool_name, args_text = parsed

        sig = _call_signature(tool_name, args_text)
        if sig in successful_sigs:
            messages.append(AIMessage(content=text))
            messages.append(HumanMessage(content=(
                f"You already made this exact call earlier and it returned useful "
                f"results — do not repeat it. Either refine the query with different "
                f"keywords, switch filter_type, try a different tool, or emit Final "
                f"Answer using the evidence you already have."
            )))
            continue

        observation = _invoke_tool(agent.tools, tool_name, args_text)
        obs_short = observation if len(observation) < 4000 else observation[:4000] + "…(truncated)"
        steps.append({"tool": tool_name, "input": args_text, "output": obs_short})
        transcript += f"\nObservation: {obs_short}\n"
        if obs_short.strip() and not obs_short.lstrip().startswith("ERROR"):
            successful_sigs.add(sig)

        messages.append(AIMessage(content=text))
        memo = _prior_calls_memo(steps)
        followup = f"Observation: {obs_short}"
        if memo:
            followup += f"\n\n{memo}"
        messages.append(HumanMessage(content=followup))

    return {"answer": final or text, "steps": steps, "transcript": transcript}


def stream(agent: AgentBundle, query: str, history: list[dict] | None = None) -> Iterable[dict]:
    """Yield {type, content} events for the UI.

    ``history`` is an optional list of prior chat turns
    ({"role": "user"|"assistant", "content": str}). They are prepended so the
    agent can reason over follow-up questions that reference earlier context.
    """
    messages = [SystemMessage(content=agent.system_prompt)]
    messages.extend(_build_history_messages(history))
    messages.append(HumanMessage(content=query))
    steps: list[dict] = []
    successful_sigs: set[str] = set()
    for i in range(agent.max_iters):
        resp = agent.llm.invoke(messages, stop=["\nObservation:"])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        yield {"type": "thought", "content": text}

        final_m = _FINAL_RE.search(text)
        if final_m:
            yield {"type": "final", "content": final_m.group(1).strip()}
            return

        parsed = _parse_action(text)
        if not parsed:
            messages.append(AIMessage(content=text))
            messages.append(HumanMessage(content="Call a tool or emit Final Answer."))
            continue
        tool_name, args_text = parsed

        sig = _call_signature(tool_name, args_text)
        if sig in successful_sigs:
            yield {
                "type": "tool",
                "tool": tool_name,
                "input": args_text,
                "output": "(skipped — identical call already returned results this turn)",
            }
            messages.append(AIMessage(content=text))
            messages.append(HumanMessage(content=(
                "You already made this exact call earlier with useful results. "
                "Do not repeat it — refine the query, switch filter_type or tool, "
                "or emit Final Answer with the evidence you already have."
            )))
            continue

        observation = _invoke_tool(agent.tools, tool_name, args_text)
        obs_short = observation if len(observation) < 4000 else observation[:4000] + "…(truncated)"
        steps.append({"tool": tool_name, "input": args_text, "output": obs_short})
        if obs_short.strip() and not obs_short.lstrip().startswith("ERROR"):
            successful_sigs.add(sig)
        yield {"type": "tool", "tool": tool_name, "input": args_text, "output": obs_short}

        messages.append(AIMessage(content=text))
        memo = _prior_calls_memo(steps)
        followup = f"Observation: {obs_short}"
        if memo:
            followup += f"\n\n{memo}"
        messages.append(HumanMessage(content=followup))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    a = build_agent()
    out = run(a, "What enzymes catalyze the conversion of GGPP to lycopene? Cite KEGG reaction IDs and EC numbers.")
    print("\n=== ANSWER ===\n", out["answer"])
    print("\n=== STEPS ===")
    for s in out["steps"]:
        print(" -", s.get("tool"), s.get("input")[:120])
