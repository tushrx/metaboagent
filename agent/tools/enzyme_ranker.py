"""
LangChain tool: rank_enzymes — find and score enzyme candidates for a given EC number.

Scoring (coarse; literature-grounded refinement happens in the agent):
    overall = 0.45 * literature_evidence
            + 0.25 * host_compatibility
            + 0.20 * characterization_depth
            + 0.10 * kegg_organism_breadth
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from config import CHASSIS_ORGANISMS
from agent.tools.kegg_search import _get_retriever


def _kegg_org_code(host: str) -> str:
    host = host.strip().lower()
    if host in CHASSIS_ORGANISMS:
        return CHASSIS_ORGANISMS[host]["kegg_org"]
    for key, meta in CHASSIS_ORGANISMS.items():
        if host in meta["name"].lower() or host == meta["kegg_org"]:
            return meta["kegg_org"]
    return host


@tool
def rank_enzymes(ec_number: str, host_organism: str = "ecoli", top_k: int = 5) -> str:
    """Rank enzyme candidates for a given EC number with respect to a target host.

    Args:
        ec_number: EC number such as "1.3.99.31" (no "EC " prefix).
        host_organism: chassis key or name (ecoli, scerevisiae, ...).
        top_k: number of candidates to return.

    Returns:
        JSON list of enzyme candidates with names, organism evidence, literature
        snippets, and composite scores.
    """
    r = _get_retriever()
    host_code = _kegg_org_code(host_organism)

    # 1) Find the enzyme record(s) in the literature collection (kegg_enzyme source).
    enzyme_hits = r.search_literature(
        f"EC {ec_number} enzyme", source="kegg_enzyme", top_k=10
    )
    enzyme_records = []
    for d in enzyme_hits:
        m = d.metadata
        if m.get("ec_number") and ec_number not in str(m.get("ec_number", "")):
            continue
        enzyme_records.append(m)

    # 2) Literature signal: any PubMed abstracts mentioning this EC / reaction?
    lit_hits = r.search_literature(f"EC {ec_number} heterologous expression {host_organism}",
                                   top_k=5)

    # 3) Build candidates — one per distinct (name, organism_code) tuple we can see.
    candidates: list[dict] = []
    for rec in enzyme_records[:top_k]:
        names = _as_list(rec.get("names", ""))
        sysname = rec.get("sysname", "")
        reaction_ids = _as_list(rec.get("reaction_ids", ""))
        org_codes = _as_list(rec.get("organism_codes", ""))
        host_compat = 1.0 if host_code in org_codes else (0.5 if org_codes else 0.3)
        org_breadth = min(1.0, len(org_codes) / 50.0) if org_codes else 0.0
        char_depth = min(1.0, len(sysname) / 80.0 + 0.2 * min(1.0, len(reaction_ids) / 3))
        lit_score = _literature_score(ec_number, lit_hits)
        overall = 0.45 * lit_score + 0.25 * host_compat + 0.20 * char_depth + 0.10 * org_breadth
        candidates.append({
            "ec_number": ec_number,
            "enzyme_name": names[0] if names else sysname or f"EC {ec_number}",
            "synonyms": names[:5],
            "systematic_name": sysname,
            "reaction_ids": reaction_ids,
            "known_in_host": host_code in org_codes,
            "host_kegg_code": host_code,
            "sample_organisms": org_codes[:10],
            "scores": {
                "literature_evidence": round(lit_score, 3),
                "host_compatibility": round(host_compat, 3),
                "characterization_depth": round(char_depth, 3),
                "organism_breadth": round(org_breadth, 3),
                "overall": round(overall, 3),
            },
        })

    candidates.sort(key=lambda c: c["scores"]["overall"], reverse=True)

    return json.dumps({
        "ec_number": ec_number,
        "host": host_organism,
        "candidates": candidates[:top_k],
        "literature_evidence": [
            {"pmid": h.metadata.get("pmid", h.id),
             "title": h.metadata.get("title", ""),
             "year": h.metadata.get("year", "")}
            for h in lit_hits
        ],
    }, ensure_ascii=False)


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return v
    if not v:
        return []
    return [t.strip() for t in str(v).split(",") if t.strip()]


def _literature_score(ec_number: str, hits) -> float:
    if not hits:
        return 0.0
    matched = sum(1 for h in hits if ec_number in h.text)
    top_score = max((h.score for h in hits), default=0.0)
    return min(1.0, 0.6 * top_score + 0.4 * min(1.0, matched / 3))
