"""
PubMed abstract fetcher (NCBI E-utilities).

Pipeline
1. For each MeSH term in config.PUBMED_ALL_TERMS, esearch PMIDs (up to
   PUBMED_MAX_ABSTRACTS total across terms, deduped and cached).
2. efetch abstracts in batches of PUBMED_BATCH_SIZE, parse with Biopython.
3. Cache raw XML under data/raw/pubmed/ (one file per batch).
4. Emit unified JSONL to data/processed/literature.jsonl:
       {id, doc_text, metadata: {pmid, title, journal, year, mesh_terms, source}}

Respect NCBI guidance: ≤3 req/s without API key, polite delay between calls.
"""
from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config import (
    PROCESSED_DATA_DIR,
    PUBMED_ALL_TERMS,
    PUBMED_BASE_URL,
    PUBMED_BATCH_SIZE,
    PUBMED_MAX_ABSTRACTS,
    RAW_DATA_DIR,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PUBMED_RAW = RAW_DATA_DIR / "pubmed"
PMID_LIST_PATH = PUBMED_RAW / "pmids.txt"
XML_DIR = PUBMED_RAW / "xml"
XML_DIR.mkdir(parents=True, exist_ok=True)

REQ_DELAY = 0.35  # seconds between requests (NCBI allows 3/s anon)


class PubMedFetcher:
    def __init__(self, session: requests.Session | None = None, api_key: str | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "MetaboAgent/1.0 (research; +hbsubiochemistry@gmail.com)"})
        self.api_key = api_key

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _get(self, url: str, params: dict) -> requests.Response:
        if self.api_key:
            params = {**params, "api_key": self.api_key}
        resp = self.session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        time.sleep(REQ_DELAY)
        return resp

    # ---------- esearch ----------
    def search_pmids(self, term: str, retmax: int) -> list[str]:
        url = f"{PUBMED_BASE_URL}/esearch.fcgi"
        params = {
            "db": "pubmed",
            "term": f"{term}[MeSH Terms] OR {term}[Title/Abstract]",
            "retmax": retmax,
            "retmode": "json",
            "sort": "relevance",
        }
        data = self._get(url, params).json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        log.info("  %s -> %d PMIDs", term, len(ids))
        return ids

    def collect_pmids(self, *, incremental: bool = True) -> list[str]:
        """Collect unique PMIDs across all search terms.

        When ``incremental=True`` (default), prior PMIDs cached in
        ``pmids.txt`` are preserved and new PMIDs from newly-added terms are
        appended, so expanding ``PUBMED_ALL_TERMS`` does not re-search the
        original space. The file is rewritten with the deduped union.

        Set ``incremental=False`` to re-run esearch for every term from
        scratch.
        """
        seen: set[str] = set()
        ordered: list[str] = []

        if incremental and PMID_LIST_PATH.exists():
            for line in PMID_LIST_PATH.read_text().splitlines():
                pmid = line.strip()
                if pmid and pmid not in seen:
                    seen.add(pmid)
                    ordered.append(pmid)
            log.info("Loaded %d cached PMIDs (incremental)", len(ordered))
            if len(ordered) >= PUBMED_MAX_ABSTRACTS:
                return ordered

        per_term = max(1, PUBMED_MAX_ABSTRACTS // max(1, len(PUBMED_ALL_TERMS)))
        for term in PUBMED_ALL_TERMS:
            try:
                fresh = self.search_pmids(term, per_term)
            except Exception as e:  # noqa: BLE001
                log.warning("esearch failed for %r: %s", term, e)
                continue
            new_for_term = 0
            for pmid in fresh:
                if pmid not in seen:
                    seen.add(pmid)
                    ordered.append(pmid)
                    new_for_term += 1
                if len(ordered) >= PUBMED_MAX_ABSTRACTS:
                    break
            log.info("  +%d new PMIDs from %r (total %d)", new_for_term, term, len(ordered))
            if len(ordered) >= PUBMED_MAX_ABSTRACTS:
                break
        PMID_LIST_PATH.write_text("\n".join(ordered))
        log.info("Collected %d unique PMIDs across %d terms",
                 len(ordered), len(PUBMED_ALL_TERMS))
        return ordered

    # ---------- efetch ----------
    def fetch_abstracts(self, pmids: list[str]) -> None:
        url = f"{PUBMED_BASE_URL}/efetch.fcgi"
        for i in range(0, len(pmids), PUBMED_BATCH_SIZE):
            batch = pmids[i : i + PUBMED_BATCH_SIZE]
            out = XML_DIR / f"batch_{i:07d}.xml"
            if out.exists():
                continue
            params = {
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
                "rettype": "abstract",
            }
            try:
                resp = self._get(url, params)
            except requests.HTTPError as e:
                log.warning("efetch batch %d failed: %s", i, e)
                continue
            out.write_bytes(resp.content)
            if (i // PUBMED_BATCH_SIZE) % 20 == 0:
                log.info("  efetch progress: %d / %d", i + len(batch), len(pmids))

    # ---------- parse & export ----------
    def export_jsonl(self, out_path: Path | None = None) -> int:
        out_path = out_path or (PROCESSED_DATA_DIR / "literature.jsonl")
        PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        count = 0
        with out_path.open("w") as f:
            for xml_file in sorted(XML_DIR.glob("batch_*.xml")):
                for rec in _parse_pubmed_xml(xml_file):
                    f.write(json.dumps(rec) + "\n")
                    count += 1
        log.info("Wrote %d abstracts to %s", count, out_path.name)
        return count

    def fetch_all(self) -> None:
        pmids = self.collect_pmids()
        self.fetch_abstracts(pmids)
        self.export_jsonl()


# ---------- XML parsing ----------
def _parse_pubmed_xml(path: Path):
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        log.warning("Bad XML in %s: %s", path.name, e)
        return
    root = tree.getroot()
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
        if not abstract and not title:
            continue
        doc_text = f"{title}\n\n{abstract}".strip()
        yield {
            "id": pmid,
            "doc_text": doc_text,
            "metadata": {
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "year": year,
                "mesh_terms": mesh_terms,
                "source": "pubmed",
            },
        }


def _text(el) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


if __name__ == "__main__":
    PubMedFetcher().fetch_all()
