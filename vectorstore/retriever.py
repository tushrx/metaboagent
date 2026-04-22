"""
Hybrid retriever over ChromaDB.

Strategy (per CLAUDE.md):
1. Semantic query using PubMedBERT embedding.
2. Optional metadata filter (exact match on EC number, compound ID, pathway ID, ...).
3. Retrieve top-k=RETRIEVAL_TOP_K candidates.
4. Optionally rerank down to RERANK_TOP_K using Gemma 4 as a scoring model
   (lightweight — one prompt per query, no per-doc LLM calls).

Metadata filter semantics
- We stored list-valued metadata as comma-joined strings (see indexer._flatten_metadata).
  Chroma `where` does not support substring match, so for list fields we fall back to
  a post-retrieval Python filter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from chromadb.api.models.Collection import Collection

from config import (
    COLLECTION_COMPOUNDS,
    COLLECTION_LITERATURE,
    COLLECTION_REACTIONS,
    RERANK_TOP_K,
    RETRIEVAL_TOP_K,
)
from vectorstore.chroma_setup import get_client, get_or_create_collection
from vectorstore.embedder import Embedder

log = logging.getLogger(__name__)

# Metadata keys stored as comma-joined strings (need substring match, not Chroma `where`).
_LIST_KEYS = {
    "ec_numbers", "pathway_ids", "compound_ids", "reaction_ids",
    "substrates", "products", "mesh_terms", "organism_codes",
    "names", "module_ids",
}

_COLLECTIONS = {
    "reactions": COLLECTION_REACTIONS,
    "compounds": COLLECTION_COMPOUNDS,
    "literature": COLLECTION_LITERATURE,
}


@dataclass
class RetrievedDoc:
    id: str
    text: str
    metadata: dict
    score: float  # cosine similarity (higher = better)
    extras: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "metadata": self.metadata, "score": self.score}


class Retriever:
    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder or Embedder()
        self.client = get_client()
        self._collections: dict[str, Collection] = {}

    def _collection(self, name: str) -> Collection:
        if name not in self._collections:
            self._collections[name] = get_or_create_collection(self.client, _COLLECTIONS[name])
        return self._collections[name]

    # ---------- core ----------
    def search(
        self,
        collection: str,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int = RETRIEVAL_TOP_K,
    ) -> list[RetrievedDoc]:
        """
        filters: {"ec_number": "2.5.1.10", "pathway_ids": "map00900", ...}
        Keys in _LIST_KEYS are applied client-side (substring on the joined string).
        Other keys are passed through as Chroma `where` exact-match.
        """
        coll = self._collection(collection)
        vec = self.embedder.embed([query])[0].tolist()

        where: dict | None = None
        post_filters: dict = {}
        if filters:
            chroma_clauses: dict = {}
            for k, v in filters.items():
                if v is None or v == "":
                    continue
                if k in _LIST_KEYS:
                    post_filters[k] = str(v)
                else:
                    chroma_clauses[k] = v
            if len(chroma_clauses) == 1:
                where = chroma_clauses
            elif len(chroma_clauses) > 1:
                where = {"$and": [{k: v} for k, v in chroma_clauses.items()]}

        # Overfetch when post-filtering so we still have candidates after pruning.
        n = top_k * (5 if post_filters else 1)
        try:
            raw = coll.query(query_embeddings=[vec], n_results=n, where=where)
        except Exception as e:  # noqa: BLE001
            log.warning("Chroma query failed (%s); retrying without where", e)
            raw = coll.query(query_embeddings=[vec], n_results=n)

        docs = _unpack(raw)
        if post_filters:
            docs = [d for d in docs if _match_list_filters(d.metadata, post_filters)]
        return docs[:top_k]

    # ---------- convenience wrappers ----------
    def search_reactions(self, query: str, ec_number: str | None = None,
                         pathway_id: str | None = None, compound_id: str | None = None,
                         top_k: int = RETRIEVAL_TOP_K) -> list[RetrievedDoc]:
        filters = {}
        if ec_number:
            filters["ec_numbers"] = ec_number
        if pathway_id:
            filters["pathway_ids"] = pathway_id
        if compound_id:
            filters["compound_ids"] = compound_id
        return self.search("reactions", query, filters=filters, top_k=top_k)

    def search_compounds(self, query: str, compound_id: str | None = None,
                         top_k: int = RETRIEVAL_TOP_K) -> list[RetrievedDoc]:
        filters = {"kegg_id": compound_id} if compound_id else None
        return self.search("compounds", query, filters=filters, top_k=top_k)

    def search_literature(self, query: str, source: str | None = None,
                          mesh_term: str | None = None,
                          top_k: int = RETRIEVAL_TOP_K) -> list[RetrievedDoc]:
        filters: dict = {}
        if source:
            filters["source"] = source
        if mesh_term:
            filters["mesh_terms"] = mesh_term
        return self.search("literature", query, filters=filters, top_k=top_k)

    # ---------- LLM rerank ----------
    def rerank_with_llm(self, query: str, docs: list[RetrievedDoc],
                        top_k: int = RERANK_TOP_K, llm=None) -> list[RetrievedDoc]:
        """
        Ask Gemma 4 to score each candidate 0-10 for relevance to `query`.
        `llm` is any LangChain chat model (defaults to a fresh Gemma 4 client).
        Falls back to original cosine ordering on LLM error.
        """
        if not docs:
            return []
        if llm is None:
            # Route rerank (a lightweight ranking task) through the router.
            # When no utility endpoint is configured this transparently
            # returns the primary client — identical to Day-1 behavior.
            from agent.router import TASK_RERANK, build_llm_for
            llm = build_llm_for(TASK_RERANK)
        numbered = "\n".join(
            f"[{i}] {d.text[:500]}" for i, d in enumerate(docs)
        )
        prompt = (
            "You are scoring retrieved documents for relevance to a metabolic-engineering "
            "query. For each document, output a line `INDEX SCORE` where SCORE is an "
            "integer 0-10 (10=most relevant). No prose.\n\n"
            f"Query: {query}\n\nDocuments:\n{numbered}\n\nScores:"
        )
        try:
            resp = llm.invoke(prompt)
            scores = _parse_scores(resp.content if hasattr(resp, "content") else str(resp),
                                   n=len(docs))
        except Exception as e:  # noqa: BLE001
            log.warning("Rerank failed (%s); falling back to cosine order", e)
            return docs[:top_k]
        for d, s in zip(docs, scores):
            d.extras["llm_score"] = s
        docs.sort(key=lambda d: d.extras.get("llm_score", 0), reverse=True)
        return docs[:top_k]


def _unpack(raw: dict) -> list[RetrievedDoc]:
    """Convert a chroma .query() response (single query) into RetrievedDoc list."""
    ids = (raw.get("ids") or [[]])[0]
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    out = []
    for i, doc_id in enumerate(ids):
        dist = distances[i] if i < len(distances) else 1.0
        # cosine distance in Chroma is 1 - cosine_similarity
        score = max(0.0, 1.0 - float(dist))
        out.append(RetrievedDoc(
            id=doc_id,
            text=docs[i] if i < len(docs) else "",
            metadata=metas[i] if i < len(metas) else {},
            score=score,
        ))
    return out


def _match_list_filters(meta: dict, filters: dict) -> bool:
    for k, v in filters.items():
        field_val = meta.get(k, "")
        if not isinstance(field_val, str):
            field_val = str(field_val)
        tokens = {t.strip() for t in field_val.split(",") if t.strip()}
        if v not in tokens:
            return False
    return True


def _parse_scores(text: str, n: int) -> list[int]:
    scores = [0] * n
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0].strip("[]:."))
            sc = int(parts[1].strip("[]:."))
        except ValueError:
            continue
        if 0 <= idx < n:
            scores[idx] = max(0, min(10, sc))
    return scores
