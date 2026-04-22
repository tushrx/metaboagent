"""
ChromaDB client + collection bootstrap.

Three collections (per CLAUDE.md):
- kegg_reactions
- kegg_compounds
- literature          (PubMed abstracts + KEGG pathway text + BRENDA notes)

ChromaDB is persistent on-disk at config.CHROMADB_DIR. We disable its
built-in embedding function and pass our own PubMedBERT vectors from
vectorstore/embedder.py.
"""
from __future__ import annotations

import logging

import chromadb
from chromadb.config import Settings

from config import (
    CHROMADB_DIR,
    COLLECTION_COMPOUNDS,
    COLLECTION_LITERATURE,
    COLLECTION_REACTIONS,
)

log = logging.getLogger(__name__)

COLLECTIONS = (COLLECTION_REACTIONS, COLLECTION_COMPOUNDS, COLLECTION_LITERATURE)


def get_client() -> chromadb.api.ClientAPI:
    return chromadb.PersistentClient(
        path=str(CHROMADB_DIR),
        settings=Settings(anonymized_telemetry=False, allow_reset=False),
    )


def get_or_create_collection(client, name: str):
    # embedding_function=None -> we will provide embeddings explicitly on add().
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


def setup_all() -> dict:
    client = get_client()
    created = {}
    for name in COLLECTIONS:
        coll = get_or_create_collection(client, name)
        created[name] = coll.count()
        log.info("Collection %s ready (current count=%d)", name, created[name])
    return created


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(setup_all())
