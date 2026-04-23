"""
LangChain tool: plan_retrosynthesis — backward chain from a target KEGG compound
to precursors native to a chassis organism.

Algorithm (bounded BFS, depth-limited):
    target -> reactions producing target (product match)
          -> for each, take substrates not yet native
             -> repeat until substrate is on the host's native metabolite whitelist
                or depth limit reached.

Native-metabolite whitelist is keyed off config.CHASSIS_ORGANISMS[host].native_pathways
expanded via `_NATIVE_COMPOUND_HINTS` below. This is intentionally coarse — the agent
uses this as scaffolding and refines with KEGG/literature searches.
"""
from __future__ import annotations

import json
from collections import deque
from typing import Literal, Optional

from langchain_core.tools import tool

HostOrganism = Literal["ecoli", "scerevisiae", "cglutamicum", "bsubtilis", "pputida"]

from config import CHASSIS_ORGANISMS
from agent.tools.kegg_search import _get_retriever

MAX_DEPTH = 6
MAX_BRANCHES_PER_STEP = 3

# Hand-curated native-metabolite anchors by chassis. These are "stop" compounds for
# retrosynthesis (the host produces them at usable flux via central metabolism).
_NATIVE_COMPOUND_HINTS: dict[str, set[str]] = {
    "ecoli": {
        "C00022",  # Pyruvate
        "C00024",  # Acetyl-CoA
        "C00036",  # Oxaloacetate
        "C00074",  # PEP
        "C00031",  # Glucose
        "C00118",  # GAP (glyceraldehyde-3P)
        "C00117",  # Ribose-5P
        "C00235",  # DMAPP (MEP pathway)
        "C00129",  # IPP (MEP pathway)
        "C00341",  # GPP
        "C00448",  # FPP
        "C00944",  # Shikimate
        "C00493",  # Shikimate-3-phosphate
        "C00254",  # Prephenate
    },
    "scerevisiae": {
        "C00022", "C00024", "C00036", "C00074", "C00031",
        "C00129", "C00235", "C00341", "C00448",   # MVA pathway terpenoid precursors
        "C00944",
    },
    "cglutamicum": {"C00022", "C00024", "C00036", "C00031", "C00129", "C00235", "C00448"},
    "bsubtilis":   {"C00022", "C00024", "C00036", "C00031", "C00129", "C00235", "C00341", "C00448"},
    "pputida":     {"C00022", "C00024", "C00036", "C00031", "C00129", "C00235", "C00448"},
}


def _native_set(host_key: str) -> set[str]:
    return _NATIVE_COMPOUND_HINTS.get(host_key, set())


def _resolve_host_key(host: str) -> str:
    host = host.strip().lower()
    if host in CHASSIS_ORGANISMS:
        return host
    for key, meta in CHASSIS_ORGANISMS.items():
        if host in meta["name"].lower() or host in meta["kegg_org"]:
            return key
    return host  # unknown — native set will be empty, agent handles


def _reactions_producing(compound_id: str, top_k: int = 10) -> list[dict]:
    """Return KEGG reactions where `compound_id` appears in the products list."""
    r = _get_retriever()
    # Pull candidates that reference this compound, then filter to products-side.
    hits = r.search_reactions(
        f"reaction producing {compound_id}",
        compound_id=compound_id,
        top_k=top_k,
    )
    out = []
    for d in hits:
        m = d.metadata
        products = _split_csv(m.get("products", ""))
        if compound_id not in products:
            continue
        out.append({
            "reaction_id": m.get("kegg_id", d.id),
            "equation": m.get("equation", ""),
            "ec_numbers": _split_csv(m.get("ec_numbers", "")),
            "substrates": _split_csv(m.get("substrates", "")),
            "products": products,
            "score": d.score,
        })
    return out[:MAX_BRANCHES_PER_STEP]


def _split_csv(s) -> list[str]:
    if not s:
        return []
    if isinstance(s, list):
        return s
    return [t.strip() for t in str(s).split(",") if t.strip()]


@tool(parse_docstring=True)
def plan_retrosynthesis(
    target_compound_id: str,
    host_organism: HostOrganism = "ecoli",
) -> str:
    """Backward-chain a biosynthetic pathway from a target KEGG compound to host-native precursors.

    Args:
        target_compound_id: KEGG compound ID of the target molecule (e.g., "C05432").
        host_organism: chassis key, one of ecoli, scerevisiae, cglutamicum, bsubtilis, pputida.

    Returns:
        JSON with ordered pathway steps from a native precursor to the target, each with
        reaction_id, ec_number(s), substrate(s), product(s), is_native_to_host.
    """
    host_key = _resolve_host_key(host_organism)
    native = _native_set(host_key)

    # BFS from target backwards. Track steps as (product, reaction, substrate, depth, parent_idx).
    steps: list[dict] = []
    seen_compounds: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(target_compound_id, 0)])

    while queue:
        cpd, depth = queue.popleft()
        if cpd in seen_compounds or depth >= MAX_DEPTH:
            continue
        seen_compounds.add(cpd)
        if cpd in native:
            continue  # reached a native anchor — stop this branch

        producing = _reactions_producing(cpd)
        if not producing:
            continue
        # Take the best-scoring reaction as the canonical parent step
        for rxn in producing[:1]:
            subs_non_native = [s for s in rxn["substrates"] if s not in native]
            steps.append({
                "step": len(steps) + 1,
                "reaction_id": rxn["reaction_id"],
                "ec_numbers": rxn["ec_numbers"],
                "substrates": rxn["substrates"],
                "product": cpd,
                "equation": rxn["equation"],
                "is_native_to_host": False,
                "depth": depth,
            })
            for s in subs_non_native:
                queue.append((s, depth + 1))

    # Reverse so pathway reads precursor -> ... -> target.
    steps.reverse()
    for i, s in enumerate(steps, 1):
        s["step"] = i

    return json.dumps({
        "target": target_compound_id,
        "host": host_key,
        "host_name": CHASSIS_ORGANISMS.get(host_key, {}).get("name", host_organism),
        "native_anchors": sorted(native),
        "pathway": steps,
        "reached_native": any(
            all(sub in native for sub in s["substrates"]) for s in steps
        ),
    }, ensure_ascii=False)
