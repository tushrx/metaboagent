"""
@tool fetch_gene_sequence — fetch a CDS / nucleotide sequence from NCBI.

Two call paths:
  1. Accession lookup — given an NCBI accession (NM_..., XM_..., CP_..., NC_..., a
     bare GenBank ID, or an UniProt cross-reference like "U00096.3"), we efetch
     the FASTA record directly.
  2. Gene-symbol + organism search — esearch ``nuccore`` with
     ``<gene>[Gene] AND <organism>[Organism]`` and pick the top hit.

We trim the returned sequence to what the caller needs:
  - For short CDSes (< 5 kb) we return the full sequence.
  - For genomic scaffolds we return the first 5 kb and warn the agent that
    trimming happened (so it can rerun with a specific accession if needed).

Endpoints:
  esearch: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=nuccore
  efetch:  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore
"""
from __future__ import annotations

import json
import logging
import re

from langchain_core.tools import tool

from agent.tools._demo import is_demo_mode, stub as demo_stub
from agent.tools._http import get_json, get_text, make_session
from config import PUBMED_BASE_URL  # same E-utilities host
from vectorstore.live_indexer import VectorDocument, index_documents, pick_collection

log = logging.getLogger(__name__)

_session = make_session()

# Anything with at least one digit and at least one letter, allowing dots/underscores.
_ACCESSION_RE = re.compile(r"^[A-Z]{1,4}[_]?\d+(?:\.\d+)?$", re.IGNORECASE)

_MAX_SEQ_RETURN = 5000  # trim very long scaffolds


def _looks_like_accession(s: str) -> bool:
    s = s.strip()
    return bool(_ACCESSION_RE.match(s)) and any(ch.isdigit() for ch in s)


def _esearch_accession(gene: str, organism: str) -> str | None:
    term = f"{gene}[Gene]"
    if organism:
        term += f' AND "{organism}"[Organism]'
    data = get_json(_session, f"{PUBMED_BASE_URL}/esearch.fcgi", params={
        "db": "nuccore", "term": term, "retmode": "json", "retmax": 1,
        "sort": "relevance",
    })
    if not data:
        return None
    ids = data.get("esearchresult", {}).get("idlist", [])
    return ids[0] if ids else None


def _fetch_fasta(accession_or_id: str) -> tuple[str, str]:
    """Return (header_line, sequence) — FASTA minus the '>' prefix."""
    text = get_text(_session, f"{PUBMED_BASE_URL}/efetch.fcgi", params={
        "db": "nuccore", "id": accession_or_id,
        "rettype": "fasta", "retmode": "text",
    })
    if not text or not text.startswith(">"):
        return "", ""
    lines = text.strip().splitlines()
    header = lines[0][1:].strip() if lines else ""
    seq = "".join(lines[1:]).replace(" ", "").upper()
    return header, seq


@tool(parse_docstring=True)
def fetch_gene_sequence(gene_or_accession: str, organism: str = "") -> str:
    """Fetch a gene CDS / nucleotide sequence from NCBI.

    Args:
        gene_or_accession: Either an NCBI accession ("U00096.3", "NC_000913.3",
            "JX123456") or a gene symbol ("crtE", "ADS1", "dxs") to search for.
        organism: Optional organism restriction when searching by gene symbol
            ("Escherichia coli", "Saccharomyces cerevisiae").

    Returns:
        JSON string with {accession, description, length, sequence, truncated,
        url}. If ``truncated`` is True the sequence was trimmed to 5 kb for
        token safety — call again with a specific accession when a full
        genome scaffold is actually needed.
    """
    q = (gene_or_accession or "").strip()
    if not q:
        return json.dumps({"error": "empty query"})
    if is_demo_mode():
        return demo_stub("fetch_gene_sequence",
                         gene_or_accession=q, organism=organism)

    # Step 1 — resolve to an accession if the caller gave a gene symbol.
    if _looks_like_accession(q):
        accession = q
    else:
        accession = _esearch_accession(q, organism)
        if not accession:
            return json.dumps({"query": q, "organism": organism,
                               "note": "no NCBI nuccore match"})

    header, seq = _fetch_fasta(accession)
    if not seq:
        return json.dumps({"query": q, "accession": accession,
                           "note": "efetch returned no sequence"})

    truncated = len(seq) > _MAX_SEQ_RETURN
    sequence_out = seq[:_MAX_SEQ_RETURN] if truncated else seq

    result = {
        "query": q,
        "organism": organism,
        "accession": accession,
        "description": header,
        "length": len(seq),
        "sequence": sequence_out,
        "truncated": truncated,
        "url": f"https://www.ncbi.nlm.nih.gov/nuccore/{accession}",
    }

    # Auto-index (header + first 400 nt as a lightweight summary).
    doc_text = (
        f"NCBI gene sequence {accession}: {header}\n"
        f"Organism: {organism or 'n/a'}\n"
        f"Length: {len(seq)} bp\n"
        f"First 400 nt: {seq[:400]}"
    )
    index_documents([VectorDocument(
        id=accession,
        source="ncbi_nuccore",
        collection=pick_collection("uniprot"),  # protein-like text → literature
        doc_text=doc_text,
        metadata={
            "accession": accession,
            "gene_symbol": q if not _looks_like_accession(q) else "",
            "organism": organism or "",
            "length": len(seq),
        },
    )])

    return json.dumps(result, ensure_ascii=False)
