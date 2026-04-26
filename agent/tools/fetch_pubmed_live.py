"""
@tool fetch_pubmed_live — on-demand PubMed search via NCBI E-utilities.

Differs from ``search_literature``: this hits NCBI in real time and indexes
the new abstracts so follow-up semantic searches can find them. Useful when
the indexed corpus is thin on a specific topic.

Endpoints:
  esearch: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
  efetch:  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET

from langchain_core.tools import tool

from agent.tools._demo import cached_or_stub, is_demo_mode
from agent.tools._http import get_json, get_text, make_session
from config import PUBMED_BASE_URL
from vectorstore.live_indexer import VectorDocument, index_documents, pick_collection

log = logging.getLogger(__name__)

_session = make_session()


def _text(el) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning("pubmed_live xml parse failed: %s", e)
        return []
    records: list[dict] = []
    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else None
        if not pmid:
            continue
        title = _text(article.find(".//ArticleTitle"))
        abstract = " ".join(
            _text(a) for a in article.findall(".//Abstract/AbstractText")
        ).strip()
        journal = _text(article.find(".//Journal/Title"))
        year = _text(article.find(".//JournalIssue/PubDate/Year"))
        if not year:
            medline_date = _text(article.find(".//JournalIssue/PubDate/MedlineDate"))
            year = medline_date[:4] if medline_date else ""
        mesh_terms = [
            _text(m.find("DescriptorName"))
            for m in article.findall(".//MeshHeading")
            if m.find("DescriptorName") is not None
        ]
        if not (title or abstract):
            continue
        records.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "year": year,
            "mesh_terms": mesh_terms,
        })
    return records


@tool(parse_docstring=True)
def fetch_pubmed_live(query: str, max_results: int = 10) -> str:
    """Search PubMed in real time via NCBI E-utilities.

    Call this tool whenever the user references a PMID, asks for
    "recent", "latest", or "new" papers on a topic, or explicitly says
    "PubMed", "NCBI", "search the literature", "find papers", or
    similar. Prefer this over answering from memory when the user wants
    actual citations. Also use it when ``search_literature`` returned
    empty. The returned abstracts are auto-indexed into the literature
    collection so follow-up semantic searches can find them.

    Args:
        query: Free-text search (supports MeSH syntax, e.g.,
            "lycopene biosynthesis[MeSH Terms]").
        max_results: Cap on abstracts returned (default 10, max 50).

    Returns:
        JSON string with a list of hits: PMID, title, abstract (truncated),
        journal, year, and MeSH terms.
    """
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "empty query"})
    if is_demo_mode():
        return cached_or_stub("fetch_pubmed_live", fallback="search_literature",
                              query=q, max_results=int(max_results))
    cap = min(50, max(1, int(max_results)))

    # esearch → PMIDs
    esearch = get_json(_session, f"{PUBMED_BASE_URL}/esearch.fcgi", params={
        "db": "pubmed", "term": q, "retmax": cap, "retmode": "json", "sort": "relevance",
    })
    if not esearch:
        return json.dumps({"query": q, "hits": [], "note": "esearch failed"})
    pmids = esearch.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return json.dumps({"query": q, "hits": [], "note": "no PubMed matches"})

    # efetch → XML → records
    xml_text = get_text(_session, f"{PUBMED_BASE_URL}/efetch.fcgi", params={
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "rettype": "abstract",
    })
    records = _parse_pubmed_xml(xml_text or "")

    # Auto-index each abstract.
    docs: list[VectorDocument] = []
    for r in records:
        doc_text = f"{r['title']}\n\n{r['abstract']}".strip()
        if not doc_text:
            continue
        docs.append(VectorDocument(
            id=r["pmid"],
            source="pubmed_live",
            collection=pick_collection("pubmed_live"),
            doc_text=doc_text,
            metadata={
                "pmid": r["pmid"],
                "title": r["title"][:300],
                "journal": r["journal"],
                "year": r["year"],
                "mesh_terms": r.get("mesh_terms") or [],
            },
        ))
    if docs:
        index_documents(docs)

    # Truncate abstracts in the agent-facing payload (keep tokens bounded).
    out_hits = []
    for r in records:
        out_hits.append({
            "pmid": r["pmid"],
            "title": r["title"],
            "abstract_snippet": r["abstract"][:500],
            "journal": r["journal"],
            "year": r["year"],
            "mesh_terms": r.get("mesh_terms", [])[:8],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/",
        })
    return json.dumps({"query": q, "count": len(out_hits), "hits": out_hits},
                      ensure_ascii=False)
