"""
Full ingestion orchestrator.

Waits for the KEGG fetcher (if running), parses each data type as it becomes
available, runs the PubMed fetcher in-process, and indexes every JSONL into
ChromaDB. Idempotent: safe to re-run.
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from config import (
    COLLECTION_COMPOUNDS,
    COLLECTION_LITERATURE,
    COLLECTION_REACTIONS,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
)
from data.ingestion.kegg_parser import (
    _parse_dir, load_links, parse_compound, parse_enzyme, parse_pathway, parse_reaction,
)
from data.ingestion.pubmed_fetcher import PubMedFetcher
from vectorstore.embedder import Embedder
from vectorstore.indexer import index_jsonl

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

KEGG = RAW_DATA_DIR / "kegg"


def _fetcher_running() -> bool:
    out = subprocess.run(["pgrep", "-f", "data.ingestion.kegg_fetcher"],
                         capture_output=True, text=True)
    return out.returncode == 0


def _wait_for_fetcher():
    while _fetcher_running():
        log.info("KEGG fetcher still running — sleeping 60s")
        time.sleep(60)
    log.info("KEGG fetcher finished.")


def main():
    # 1) PubMed in parallel (independent of KEGG).
    log.info("=== PubMed fetch ===")
    try:
        PubMedFetcher().fetch_all()
    except Exception as e:  # noqa: BLE001
        log.exception("PubMed fetch failed: %s", e)

    # 2) Compounds already done — parse + index now.
    _wait_for_dir(KEGG / "compounds", min_files=19000)
    _parse_dir(KEGG / "compounds", PROCESSED_DATA_DIR / "kegg_compounds.jsonl", parse_compound)

    # 3) Wait for full fetcher completion before enzymes + pathways.
    _wait_for_fetcher()
    links = load_links()
    _parse_dir(KEGG / "reactions", PROCESSED_DATA_DIR / "kegg_reactions.jsonl", parse_reaction, links)
    _parse_dir(KEGG / "enzymes",   PROCESSED_DATA_DIR / "kegg_enzymes.jsonl",   parse_enzyme)
    _parse_dir(KEGG / "pathways",  PROCESSED_DATA_DIR / "kegg_pathways.jsonl",  parse_pathway)

    # 4) Index everything.
    embedder = Embedder()
    plan = [
        (PROCESSED_DATA_DIR / "kegg_reactions.jsonl", COLLECTION_REACTIONS, "kegg_rxn"),
        (PROCESSED_DATA_DIR / "kegg_compounds.jsonl", COLLECTION_COMPOUNDS, "kegg_cpd"),
        (PROCESSED_DATA_DIR / "kegg_pathways.jsonl",  COLLECTION_LITERATURE, "kegg_pathway"),
        (PROCESSED_DATA_DIR / "kegg_enzymes.jsonl",   COLLECTION_LITERATURE, "kegg_enzyme"),
        (PROCESSED_DATA_DIR / "literature.jsonl",     COLLECTION_LITERATURE, "pubmed"),
    ]
    for path, coll, source in plan:
        index_jsonl(path, coll, embedder, extra_source=source)
    log.info("=== Ingestion complete ===")


def _wait_for_dir(d: Path, min_files: int, interval: int = 30):
    while True:
        n = len(list(d.glob("*.txt"))) if d.exists() else 0
        if n >= min_files or not _fetcher_running():
            return
        log.info("Waiting for %s (%d/%d)", d.name, n, min_files)
        time.sleep(interval)


if __name__ == "__main__":
    main()
