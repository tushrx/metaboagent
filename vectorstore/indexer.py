"""
Batch indexing pipeline.

Reads processed JSONL files and upserts (id, embedding, metadata, doc_text)
into the appropriate ChromaDB collection. Idempotent via Chroma's upsert.

Inputs (whichever exist — safe to run incrementally):
- data/processed/kegg_reactions.jsonl  -> kegg_reactions
- data/processed/kegg_compounds.jsonl  -> kegg_compounds
- data/processed/kegg_pathways.jsonl   -> literature (pathway descriptions as docs)
- data/processed/literature.jsonl      -> literature (PubMed)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator

from config import (
    COLLECTION_COMPOUNDS,
    COLLECTION_LITERATURE,
    COLLECTION_REACTIONS,
    EMBEDDING_BATCH_SIZE,
    PROCESSED_DATA_DIR,
)
from vectorstore.chroma_setup import get_client, get_or_create_collection
from vectorstore.embedder import Embedder

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Upsert chunk size for Chroma. Separate from embedding batch size to bound
# per-call payload independently of model throughput.
UPSERT_CHUNK = 256


def _iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _flatten_metadata(meta: dict) -> dict:
    """Chroma only allows primitive metadata. Join list fields to comma strings."""
    flat: dict = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            flat[k] = ",".join(str(x) for x in v)
        elif isinstance(v, (str, int, float, bool)):
            flat[k] = v
        else:
            flat[k] = str(v)
    return flat


def index_jsonl(jsonl_path: Path, collection_name: str, embedder: Embedder,
                extra_source: str | None = None) -> int:
    if not jsonl_path.exists():
        log.warning("Skip %s: file missing", jsonl_path.name)
        return 0

    client = get_client()
    coll = get_or_create_collection(client, collection_name)

    total = 0
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []

    def flush():
        nonlocal ids, docs, metas, total
        if not ids:
            return
        vectors = embedder.embed(docs)
        coll.upsert(
            ids=ids,
            documents=docs,
            metadatas=metas,
            embeddings=vectors.tolist(),
        )
        total += len(ids)
        if total % (UPSERT_CHUNK * 4) == 0:
            log.info("  %s: upserted %d", collection_name, total)
        ids, docs, metas = [], [], []

    for rec in _iter_jsonl(jsonl_path):
        rec_id = rec["id"]
        doc_text = rec["doc_text"]
        meta = _flatten_metadata(rec.get("metadata", {}))
        if extra_source and "source" not in meta:
            meta["source"] = extra_source
        # Namespace IDs to avoid collisions across JSONL sources sharing a collection.
        ns_id = f"{extra_source or collection_name}:{rec_id}"
        ids.append(ns_id)
        docs.append(doc_text)
        metas.append(meta)
        if len(ids) >= UPSERT_CHUNK:
            flush()
    flush()
    log.info("Finished %s -> %s: %d records", jsonl_path.name, collection_name, total)
    return total


def index_all() -> dict[str, int]:
    embedder = Embedder()
    counts: dict[str, int] = {}
    plan = [
        (PROCESSED_DATA_DIR / "kegg_reactions.jsonl", COLLECTION_REACTIONS, "kegg_rxn"),
        (PROCESSED_DATA_DIR / "kegg_compounds.jsonl", COLLECTION_COMPOUNDS, "kegg_cpd"),
        (PROCESSED_DATA_DIR / "kegg_pathways.jsonl", COLLECTION_LITERATURE, "kegg_pathway"),
        (PROCESSED_DATA_DIR / "kegg_enzymes.jsonl",  COLLECTION_LITERATURE, "kegg_enzyme"),
        (PROCESSED_DATA_DIR / "literature.jsonl",    COLLECTION_LITERATURE, "pubmed"),
    ]
    for path, coll, source in plan:
        counts[source] = index_jsonl(path, coll, embedder, extra_source=source)
    log.info("Index summary: %s", counts)
    return counts


if __name__ == "__main__":
    index_all()
