"""
Live (online) indexer — self-learning RAG enrichment.

Every live-fetch tool (PubChem, UniProt, SABIO-RK, live-PubMed, live-KEGG,
ZINC, etc.) funnels its structured responses through :func:`index_documents`
so the knowledge base grows with every agent turn. The embedding model is
the single process-wide PubMedBERT owned by the :class:`Retriever` singleton
(see ``vectorstore.retriever.get_retriever``) — the live indexer never
creates a second embedder.

Design constraints
- **Non-blocking failure**: if embedding or upsert fails for any reason, the
  tool's response to the agent is unaffected. We log and move on — data loss
  is cheaper than breaking the ReAct loop.
- **Idempotency**: all upserts use a stable ID of the form
  ``{source}:{entity_id}``, so repeat fetches overwrite rather than duplicate.
- **Dedup by source**: IDs are namespaced by the fetch source (``pubchem``,
  ``uniprot``, etc.) to avoid collisions with offline-ingested KEGG IDs.
- **Thread safety**: Gradio may call tools from worker threads; the Chroma
  persistent client and Embedder are both thread-safe for our usage pattern
  (read + upsert), so we share a single instance.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

from config import (
    COLLECTION_COMPOUNDS,
    COLLECTION_LITERATURE,
    COLLECTION_REACTIONS,
)
from vectorstore.chroma_setup import COLLECTIONS, get_client, get_or_create_collection

log = logging.getLogger(__name__)

_lock = threading.Lock()
_client = None
_collections: dict[str, object] = {}

# Per-process counters of live-added docs (for knowledge_stats delta display).
_live_added: dict[str, int] = {c: 0 for c in COLLECTIONS}


@dataclass
class VectorDocument:
    """Structured payload destined for ChromaDB."""
    id: str                    # entity id, e.g. "CID_2244" or "P12345"
    source: str                # fetcher source: "pubchem", "uniprot", etc.
    collection: str            # target Chroma collection name
    doc_text: str              # embedding input (title + description + key fields)
    metadata: dict = field(default_factory=dict)

    def namespaced_id(self) -> str:
        return f"{self.source}:{self.id}"


def _get_embedder():
    """Return the process-wide Embedder owned by the Retriever singleton.

    This does not load a new model — it forwards to
    :func:`vectorstore.retriever.get_embedder`. If this is the first call
    anywhere in the process, the Retriever singleton boots (which logs
    "Retriever singleton: initializing ..."); otherwise it's a no-op.
    """
    from vectorstore.retriever import get_embedder
    return get_embedder()


def _get_collection(name: str):
    global _client
    if name not in _collections:
        if _client is None:
            _client = get_client()
        _collections[name] = get_or_create_collection(_client, name)
    return _collections[name]


def _flatten_metadata(meta: dict) -> dict:
    """Chroma only allows primitive metadata values. Join lists, coerce others."""
    flat: dict = {}
    for k, v in meta.items():
        if v is None or v == "":
            continue
        if isinstance(v, (list, tuple)):
            flat[k] = ",".join(str(x) for x in v if x not in (None, ""))
        elif isinstance(v, (str, int, float, bool)):
            flat[k] = v
        elif isinstance(v, dict):
            # Collapse small nested dicts to "k1=v1;k2=v2" strings.
            flat[k] = ";".join(f"{kk}={vv}" for kk, vv in v.items())
        else:
            flat[k] = str(v)
    return flat


def index_documents(docs: list[VectorDocument]) -> int:
    """Embed and upsert a batch of documents. Returns number successfully added.

    Safe to call from any thread. Never raises — failures are logged and
    swallowed so tool calls stay on the happy path.
    """
    if not docs:
        return 0
    try:
        by_collection: dict[str, list[VectorDocument]] = {}
        for d in docs:
            by_collection.setdefault(d.collection, []).append(d)

        total_added = 0
        with _lock:
            embedder = _get_embedder()
            for coll_name, items in by_collection.items():
                coll = _get_collection(coll_name)
                texts = [x.doc_text or " " for x in items]
                vectors = embedder.embed(texts)
                ids = [x.namespaced_id() for x in items]
                metadatas = []
                for x in items:
                    meta = {"source": x.source, **x.metadata}
                    metadatas.append(_flatten_metadata(meta))
                coll.upsert(
                    ids=ids,
                    documents=texts,
                    metadatas=metadatas,
                    embeddings=vectors.tolist(),
                )
                total_added += len(items)
                _live_added[coll_name] = _live_added.get(coll_name, 0) + len(items)
        return total_added
    except Exception as e:  # noqa: BLE001
        log.warning("live indexer: upsert failed for %d docs: %s", len(docs), e)
        return 0


def index_one(
    *,
    id: str,
    source: str,
    doc_text: str,
    collection: str = COLLECTION_LITERATURE,
    metadata: Optional[dict] = None,
) -> bool:
    """Convenience for single-doc indexing. Returns True on success."""
    if not doc_text or not doc_text.strip():
        return False
    doc = VectorDocument(
        id=id,
        source=source,
        collection=collection,
        doc_text=doc_text,
        metadata=metadata or {},
    )
    return index_documents([doc]) > 0


def collection_counts() -> dict[str, int]:
    """Current live counts for each collection (baseline + live-added)."""
    counts: dict[str, int] = {}
    for name in COLLECTIONS:
        try:
            counts[name] = _get_collection(name).count()
        except Exception as e:  # noqa: BLE001
            log.debug("count failed for %s: %s", name, e)
            counts[name] = 0
    return counts


def live_added_counts() -> dict[str, int]:
    """Docs added this process lifetime (resets on UI restart)."""
    return dict(_live_added)


# ---------- convenience target-picking ----------
TARGET_FOR_SOURCE = {
    "pubchem":      COLLECTION_COMPOUNDS,   # compound documents
    "zinc":         COLLECTION_COMPOUNDS,
    "uniprot":      COLLECTION_LITERATURE,  # protein descriptions are prose-like
    "sabio_rk":     COLLECTION_LITERATURE,  # enzyme kinetics docs
    "pubmed_live":  COLLECTION_LITERATURE,
    "kegg_live":    COLLECTION_REACTIONS,   # overridden if cpd/enzyme/pathway
}


def pick_collection(source: str, default: str = COLLECTION_LITERATURE) -> str:
    return TARGET_FOR_SOURCE.get(source, default)
