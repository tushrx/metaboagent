"""
@tool fetch_pubchem — PubChem PUG REST lookup with auto-indexing.

Flow
  name or CID → /compound/name/{name}/cids/JSON  → pick first CID
             → /compound/cid/{cid}/property/<set>/JSON
             → /compound/cid/{cid}/synonyms/JSON (best-effort)
  Result is JSON with canonical name, formula, MW, SMILES, synonyms, PubChem URL.
  The same document is auto-indexed into kegg_compounds (live).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool

from agent.tools._demo import cached_or_stub, is_demo_mode
from agent.tools._http import get_json, make_session
from vectorstore.live_indexer import VectorDocument, index_documents, pick_collection

log = logging.getLogger(__name__)

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PROPS = "MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount"

_session = make_session()


def _resolve_cid(query: str) -> Optional[int]:
    q = query.strip()
    if not q:
        return None
    # Numeric -> treat as CID directly.
    if q.isdigit():
        return int(q)
    data = get_json(_session, f"{_BASE}/compound/name/{q}/cids/JSON")
    if not data:
        return None
    cids = data.get("IdentifierList", {}).get("CID", [])
    return int(cids[0]) if cids else None


def _fetch_props(cid: int) -> dict:
    data = get_json(_session, f"{_BASE}/compound/cid/{cid}/property/{_PROPS}/JSON")
    if not data:
        return {}
    props = data.get("PropertyTable", {}).get("Properties", [])
    return props[0] if props else {}


def _fetch_synonyms(cid: int, max_syn: int = 6) -> list[str]:
    data = get_json(_session, f"{_BASE}/compound/cid/{cid}/synonyms/JSON")
    if not data:
        return []
    info = data.get("InformationList", {}).get("Information", [])
    syn = info[0].get("Synonym", []) if info else []
    return syn[:max_syn]


@tool(parse_docstring=True)
def fetch_pubchem(compound_name_or_cid: str) -> str:
    """Fetch compound data from PubChem (PUG REST) in real time.

    Call this tool when the user references a PubChem CID ("CID 2244"),
    a ChEBI identifier ("CHEBI:15365"), an InChIKey, or explicitly asks
    to "look up", "fetch", or "pull" a compound from PubChem/ChEBI.
    PubChem entries carry ChEBI and KEGG cross-references, so this is
    also the right entry point for ChEBI:\\d+ queries until a dedicated
    ChEBI tool lands. Do NOT call this for plain factual questions
    about a well-known compound ("what is the formula of aspirin?") —
    answer those from knowledge. Only ground in PubChem when the user
    signals they want the database record.

    Args:
        compound_name_or_cid: Compound name (e.g., "lycopene") or numeric
            PubChem CID (e.g., "446925").

    Returns:
        JSON string with CID, IUPAC name, formula, molecular weight,
        canonical SMILES, physicochemical properties, top synonyms, and the
        PubChem entry URL. The document is also auto-indexed into the live
        knowledge base so future queries can find it via semantic search.
    """
    q = (compound_name_or_cid or "").strip()
    if not q:
        return json.dumps({"error": "empty query"})
    if is_demo_mode():
        return cached_or_stub("fetch_pubchem", compound_name_or_cid=q)

    cid = _resolve_cid(q)
    if cid is None:
        return json.dumps({"query": q, "error": "no PubChem match"})

    props = _fetch_props(cid)
    synonyms = _fetch_synonyms(cid)
    result = {
        "cid": cid,
        "query": q,
        "iupac_name": props.get("IUPACName"),
        "molecular_formula": props.get("MolecularFormula"),
        "molecular_weight": props.get("MolecularWeight"),
        "canonical_smiles": props.get("CanonicalSMILES"),
        "xlogp": props.get("XLogP"),
        "h_bond_donors": props.get("HBondDonorCount"),
        "h_bond_acceptors": props.get("HBondAcceptorCount"),
        "rotatable_bonds": props.get("RotatableBondCount"),
        "synonyms": synonyms,
        "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
    }

    # Auto-index into the live knowledge base.
    doc_text = _compose_doc_text(result)
    if doc_text:
        index_documents([VectorDocument(
            id=f"CID_{cid}",
            source="pubchem",
            collection=pick_collection("pubchem"),
            doc_text=doc_text,
            metadata={
                "pubchem_cid": cid,
                "name": result.get("iupac_name") or q,
                "formula": result.get("molecular_formula") or "",
                "molecular_weight": result.get("molecular_weight") or "",
                "synonyms": synonyms,
            },
        )])

    return json.dumps(result, ensure_ascii=False)


def _compose_doc_text(result: dict) -> str:
    name = result.get("iupac_name") or result.get("query") or f"CID {result.get('cid')}"
    synonyms = ", ".join(result.get("synonyms") or [])
    lines = [
        f"PubChem compound: {name} (CID {result.get('cid')})",
        f"Formula: {result.get('molecular_formula') or 'n/a'}",
        f"Molecular weight: {result.get('molecular_weight') or 'n/a'} g/mol",
        f"SMILES: {result.get('canonical_smiles') or 'n/a'}",
        f"XLogP: {result.get('xlogp')}, H-bond donors/acceptors: "
        f"{result.get('h_bond_donors')}/{result.get('h_bond_acceptors')}, "
        f"rotatable bonds: {result.get('rotatable_bonds')}",
    ]
    if synonyms:
        lines.append(f"Synonyms: {synonyms}")
    lines.append(result.get("url", ""))
    return "\n".join(x for x in lines if x)
