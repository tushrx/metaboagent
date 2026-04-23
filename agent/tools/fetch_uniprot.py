"""
@tool fetch_uniprot — UniProt REST search with auto-indexing.

Flow
  Issue a search query against ``https://rest.uniprot.org/uniprotkb/search``
  with a small result cap. Prefer reviewed (Swiss-Prot) entries. For each hit
  we expose: accession, protein name, gene names, organism, EC numbers,
  sequence length, signal peptide/active-site residues, and cross-references
  (KEGG, PDB). The first hit's full record is indexed into the live literature
  collection.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool

from agent.tools._http import get_json, make_session
from vectorstore.live_indexer import VectorDocument, index_documents, pick_collection

log = logging.getLogger(__name__)

_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
_session = make_session()


def _build_query(protein_name_or_ec: str, organism: Optional[str]) -> str:
    q = (protein_name_or_ec or "").strip()
    parts: list[str] = []
    # Detect EC pattern and use ec: field; otherwise free-text protein name.
    import re
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", q):
        parts.append(f"ec:{q}")
    elif q:
        parts.append(q)
    if organism:
        org = organism.strip()
        if org:
            parts.append(f'organism_name:"{org}"')
    parts.append("reviewed:true")
    return " AND ".join(parts)


def _short_entry(entry: dict) -> dict:
    accession = entry.get("primaryAccession")
    protein_name = (
        entry.get("proteinDescription", {})
             .get("recommendedName", {})
             .get("fullName", {})
             .get("value")
    )
    gene_names = [
        g.get("geneName", {}).get("value")
        for g in entry.get("genes", [])
        if g.get("geneName")
    ]
    organism = entry.get("organism", {}).get("scientificName")
    ec_numbers: list[str] = []
    rec = entry.get("proteinDescription", {}).get("recommendedName", {})
    for ec in rec.get("ecNumbers", []) or []:
        val = ec.get("value")
        if val:
            ec_numbers.append(val)
    for alt in entry.get("proteinDescription", {}).get("alternativeNames", []) or []:
        for ec in alt.get("ecNumbers", []) or []:
            val = ec.get("value")
            if val and val not in ec_numbers:
                ec_numbers.append(val)
    sequence = entry.get("sequence", {})
    # Cross-refs: keep only KEGG + PDB + BRENDA for compactness.
    xrefs_all = entry.get("uniProtKBCrossReferences", []) or []
    xrefs = [
        {"db": x.get("database"), "id": x.get("id")}
        for x in xrefs_all
        if x.get("database") in {"KEGG", "PDB", "BRENDA", "BioCyc"}
    ][:12]
    features = [
        {"type": f.get("type"),
         "location": f.get("location", {}).get("start", {}).get("value"),
         "desc": f.get("description")}
        for f in (entry.get("features") or [])
        if f.get("type") in {"Active site", "Binding site", "Signal", "Transmembrane"}
    ][:10]
    # Pull a short functional description.
    comments = entry.get("comments") or []
    function_text = ""
    for c in comments:
        if c.get("commentType") == "FUNCTION":
            texts = c.get("texts") or []
            if texts:
                function_text = texts[0].get("value", "")[:500]
                break
    return {
        "accession": accession,
        "protein_name": protein_name,
        "gene_names": [g for g in gene_names if g],
        "organism": organism,
        "ec_numbers": ec_numbers,
        "sequence_length": sequence.get("length"),
        "function": function_text,
        "features": features,
        "xrefs": xrefs,
        "url": f"https://www.uniprot.org/uniprotkb/{accession}" if accession else None,
    }


@tool(parse_docstring=True)
def fetch_uniprot(protein_name_or_ec: str, organism: str = "") -> str:
    """Search UniProt (reviewed/Swiss-Prot) for a protein by name or EC number.

    Args:
        protein_name_or_ec: Protein name (e.g., "phytoene synthase") or EC
            number like "2.5.1.32".
        organism: Optional organism scientific name filter (e.g.,
            "Escherichia coli" or "Saccharomyces cerevisiae"). Empty = any.

    Returns:
        JSON string with up to 5 top hits: accession, protein name, genes,
        organism, EC numbers, sequence length, function annotation, active/
        binding/signal features, and cross-references (KEGG, PDB, BRENDA).
        The first hit's record is auto-indexed into the literature collection.
    """
    query = _build_query(protein_name_or_ec, organism or None)
    if not query:
        return json.dumps({"error": "empty query"})

    params = {"query": query, "format": "json", "size": 5,
              "fields": "accession,protein_name,gene_names,organism_name,ec,length,cc_function,ft_act_site,ft_binding,ft_signal,ft_transmem,xref_kegg,xref_pdb,xref_brenda,sequence"}
    data = get_json(_session, _SEARCH_URL, params=params)
    if not data or not data.get("results"):
        return json.dumps({"query": protein_name_or_ec, "organism": organism,
                           "hits": [], "note": "no UniProt hits"})

    hits = [_short_entry(e) for e in data["results"][:5]]

    # Auto-index the top hit.
    top = hits[0] if hits else None
    if top and top.get("accession"):
        index_documents([VectorDocument(
            id=top["accession"],
            source="uniprot",
            collection=pick_collection("uniprot"),
            doc_text=_compose_doc_text(top),
            metadata={
                "uniprot_accession": top["accession"],
                "protein_name": top.get("protein_name") or "",
                "organism": top.get("organism") or "",
                "ec_numbers": top.get("ec_numbers") or [],
                "gene_names": top.get("gene_names") or [],
            },
        )])

    return json.dumps({"query": protein_name_or_ec, "organism": organism,
                       "hits": hits}, ensure_ascii=False)


def _compose_doc_text(e: dict) -> str:
    lines = [
        f"UniProt {e.get('accession')}: {e.get('protein_name') or '(unnamed)'}",
        f"Organism: {e.get('organism') or 'n/a'}",
        f"Gene names: {', '.join(e.get('gene_names') or []) or 'n/a'}",
        f"EC numbers: {', '.join(e.get('ec_numbers') or []) or 'n/a'}",
        f"Sequence length: {e.get('sequence_length')}",
    ]
    func = e.get("function")
    if func:
        lines.append(f"Function: {func}")
    xrefs = e.get("xrefs") or []
    if xrefs:
        lines.append("Cross-refs: " + ", ".join(
            f"{x.get('db')}:{x.get('id')}" for x in xrefs if x.get("id")))
    if e.get("url"):
        lines.append(e["url"])
    return "\n".join(lines)
