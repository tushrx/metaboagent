"""
KEGG REST API fetcher.

Responsibilities
- Enumerate all reaction, compound, enzyme, pathway IDs from KEGG.
- Batch-fetch flat-file entries (up to KEGG_BATCH_SIZE per call).
- Fetch link tables (reaction<->enzyme, reaction<->pathway, reaction<->compound).
- Cache every raw response under data/raw/kegg/ so we never re-fetch.
- Respect KEGG's ~10 req/s limit via KEGG_RATE_LIMIT_DELAY.

Usage
    from data.ingestion.kegg_fetcher import KEGGFetcher
    f = KEGGFetcher()
    f.fetch_all()          # full pipeline
    f.fetch_reactions()    # just reactions
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterable

import requests
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from config import (
    KEGG_BASE_URL,
    KEGG_BATCH_SIZE,
    KEGG_ENDPOINTS,
    KEGG_RATE_LIMIT_DELAY,
    RAW_DATA_DIR,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

KEGG_RAW = RAW_DATA_DIR / "kegg"
REACTIONS_DIR = KEGG_RAW / "reactions"
COMPOUNDS_DIR = KEGG_RAW / "compounds"
ENZYMES_DIR = KEGG_RAW / "enzymes"
PATHWAYS_DIR = KEGG_RAW / "pathways"
LINKS_DIR = KEGG_RAW / "links"
LISTS_DIR = KEGG_RAW / "lists"
for d in (LINKS_DIR, LISTS_DIR):
    d.mkdir(parents=True, exist_ok=True)


class KEGGFetcher:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "MetaboAgent/1.0 (research)"})

    # ---------- low-level ----------
    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=30))
    def _get(self, url: str) -> str:
        resp = self.session.get(url, timeout=30)
        if resp.status_code == 404:
            return ""  # KEGG uses 404 for "no data" on some endpoints
        resp.raise_for_status()
        time.sleep(KEGG_RATE_LIMIT_DELAY)
        return resp.text

    # ---------- list endpoints ----------
    def _list_ids(self, endpoint_url: str, prefix: str, cache_name: str) -> list[str]:
        cache = LISTS_DIR / f"{cache_name}.txt"
        if cache.exists():
            text = cache.read_text()
        else:
            log.info("Listing %s from %s", cache_name, endpoint_url)
            text = self._get(endpoint_url)
            cache.write_text(text)
        ids = []
        for line in text.splitlines():
            if not line.strip():
                continue
            raw_id = line.split("\t", 1)[0].strip()
            # KEGG returns "rn:R00001", "cpd:C00001", etc.
            ids.append(raw_id if ":" in raw_id else f"{prefix}:{raw_id}")
        log.info("Got %d %s IDs", len(ids), cache_name)
        return ids

    def list_reaction_ids(self) -> list[str]:
        return self._list_ids(KEGG_ENDPOINTS["list_reactions"], "rn", "reactions")

    def list_compound_ids(self) -> list[str]:
        return self._list_ids(KEGG_ENDPOINTS["list_compounds"], "cpd", "compounds")

    def list_enzyme_ids(self) -> list[str]:
        return self._list_ids(KEGG_ENDPOINTS["list_enzymes"], "ec", "enzymes")

    def list_pathway_ids(self) -> list[str]:
        # KEGG's GET endpoint expects `path:mapNNNNN`, not `map:mapNNNNN`.
        return self._list_ids(KEGG_ENDPOINTS["list_pathways"], "path", "pathways")

    # ---------- batch get ----------
    def _batch_get(self, ids: Iterable[str], out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        batch: list[str] = []
        todo = [i for i in ids if not (out_dir / f"{i.split(':', 1)[1]}.txt").exists()]
        log.info("Fetching %d entries into %s (already cached: skipped)", len(todo), out_dir.name)

        for i, entry_id in enumerate(todo, 1):
            batch.append(entry_id)
            if len(batch) >= KEGG_BATCH_SIZE:
                self._fetch_batch(batch, out_dir)
                batch = []
                if i % 500 == 0:
                    log.info("  progress: %d / %d", i, len(todo))
        if batch:
            self._fetch_batch(batch, out_dir)

    def _fetch_batch(self, batch: list[str], out_dir: Path) -> None:
        url = f"{KEGG_ENDPOINTS['get']}/{'+'.join(batch)}"
        try:
            text = self._get(url)
        except (requests.HTTPError, RetryError, requests.RequestException) as e:
            log.warning("Batch failed (%s); falling back to singles + cooldown", e)
            time.sleep(5.0)  # KEGG sometimes returns 403 under load; back off before singles.
            for single in batch:
                try:
                    self._fetch_single(single, out_dir)
                except (requests.HTTPError, RetryError, requests.RequestException) as se:
                    log.warning("  single %s failed: %s", single, se)
            return
        # entries separated by "///"
        entries = [e.strip() for e in text.split("///") if e.strip()]
        # KEGG returns entries in same order as requested, but mismatches happen
        # if an ID is unknown — parse ENTRY line to be safe.
        for entry in entries:
            entry_id = _parse_entry_id(entry)
            if not entry_id:
                continue
            (out_dir / f"{entry_id}.txt").write_text(entry + "\n///\n")

    def _fetch_single(self, entry_id: str, out_dir: Path) -> None:
        url = f"{KEGG_ENDPOINTS['get']}/{entry_id}"
        try:
            text = self._get(url)
        except requests.HTTPError:
            return
        if not text.strip():
            return
        short = entry_id.split(":", 1)[1]
        (out_dir / f"{short}.txt").write_text(text)

    # ---------- link tables ----------
    def fetch_links(self) -> None:
        for key, filename in [
            ("link_enzyme_rxn",   "reaction_to_enzyme.tsv"),
            ("link_pathway_rxn",  "reaction_to_pathway.tsv"),
            ("link_compound_rxn", "reaction_to_compound.tsv"),
        ]:
            out = LINKS_DIR / filename
            if out.exists():
                log.info("Link cache exists: %s", filename)
                continue
            log.info("Fetching link table %s", filename)
            out.write_text(self._get(KEGG_ENDPOINTS[key]))

    # ---------- orchestration ----------
    def fetch_reactions(self) -> None:
        self._batch_get(self.list_reaction_ids(), REACTIONS_DIR)

    def fetch_compounds(self) -> None:
        self._batch_get(self.list_compound_ids(), COMPOUNDS_DIR)

    def fetch_enzymes(self) -> None:
        self._batch_get(self.list_enzyme_ids(), ENZYMES_DIR)

    def fetch_pathways(self) -> None:
        # Keep only reference pathways (path:mapNNNNN) — skip organism-specific ones.
        ids = [i for i in self.list_pathway_ids() if i.startswith("path:map")]
        self._batch_get(ids, PATHWAYS_DIR)

    def fetch_all(self) -> None:
        self.fetch_links()
        self.fetch_reactions()
        self.fetch_compounds()
        self.fetch_enzymes()
        self.fetch_pathways()


def _parse_entry_id(entry_text: str) -> str | None:
    """Return the primary ID from an ENTRY line.

    KEGG enzyme entries look like:  `ENTRY       EC 1.1.1.1                 Enzyme`
    KEGG pathway/reaction/compound: `ENTRY       R00024                     Reaction`
    For enzyme entries, `parts[1] == 'EC'`, so the real ID is `parts[2]`.
    """
    for line in entry_text.splitlines():
        if line.startswith("ENTRY"):
            parts = line.split()
            if len(parts) < 2:
                return None
            if parts[1].upper() == "EC" and len(parts) >= 3:
                return parts[2]
            return parts[1]
    return None


if __name__ == "__main__":
    KEGGFetcher().fetch_all()
