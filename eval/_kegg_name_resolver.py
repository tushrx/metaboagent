"""Compound name → KEGG ID(s) resolver for the substrate-relevance verifier.

The pathway-hallucination eval (Phase 6.5 / 8.3.B) emits step lines like
``Step 1: pyruvate -> acetyl-CoA``. To ask KEGG whether a cited reaction
ID actually involves those compounds, we have to resolve the names to
KEGG compound IDs (``Cnnnnn``).

Strategy:
  1. Local lookup populated by hand for ~30 metabolites we expect across
     the pathway-design eval prompts (mevalonate, isoprenoid, shikimate,
     core central-carbon). Pre-canonicalized; multiple aliases mapped
     to the same C-ID. Zero-network and isomer-aware (returns multiple
     C-IDs when KEGG splits 15-cis / all-trans / etc. across entries).
  2. Fallback: KEGG ``/find/compound/<name>`` for misses. Cached so the
     same name never costs two round trips. Conservative: only accepts
     exact name matches in the returned listing — substring matches
     would mis-resolve "phenylalanine" → tens of derivatives.

The 400 ms KEGG rate limit and 10 s timeout match ``_kegg_verify.py``.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

KEGG_FIND_BASE = "https://rest.kegg.jp/find/compound"
KEGG_SLEEP_S = 0.4
KEGG_TIMEOUT_S = 10.0

# Local lookup. Keys are lowercase + whitespace-normalized canonical names
# and aliases; values are lists of plausible KEGG compound IDs (multiple
# when isomers / common synonyms split across records). Populated from
# the 8.3.B starter list — extend rather than duplicate.
_LOCAL_LOOKUP: dict[str, list[str]] = {
    # Central carbon / TCA
    "acetyl-coa": ["C00024"],
    "acetyl coa": ["C00024"],
    "acetylcoa": ["C00024"],
    "acetyl-coenzyme a": ["C00024"],
    "hmg-coa": ["C00356"],
    "hmgcoa": ["C00356"],
    "3-hydroxy-3-methylglutaryl-coa": ["C00356"],
    "(s)-3-hydroxy-3-methylglutaryl-coa": ["C00356"],
    "mevalonate": ["C00418"],
    "mevalonic acid": ["C00418"],
    "(r)-mevalonate": ["C00418"],
    "glucose": ["C00031"],
    "d-glucose": ["C00031"],
    "pyruvate": ["C00022"],
    "pyruvic acid": ["C00022"],
    "oxaloacetate": ["C00036"],
    "oxaloacetic acid": ["C00036"],
    "oaa": ["C00036"],
    "citrate": ["C00158"],
    "citric acid": ["C00158"],
    "succinate": ["C00042"],
    "succinic acid": ["C00042"],
    "fumarate": ["C00122"],
    "fumaric acid": ["C00122"],
    "malate": ["C00149"],
    "(s)-malate": ["C00149"],
    "malic acid": ["C00149"],
    "alpha-ketoglutarate": ["C00026"],
    "α-ketoglutarate": ["C00026"],
    "2-oxoglutarate": ["C00026"],
    "akg": ["C00026"],
    # Cofactors
    "nadh": ["C00004"],
    "nad+": ["C00003"],
    "nad": ["C00003"],
    "nadph": ["C00005"],
    "nadp+": ["C00006"],
    "nadp": ["C00006"],
    "atp": ["C00002"],
    "adp": ["C00008"],
    "amp": ["C00020"],
    "fad": ["C00016"],
    "fadh2": ["C01352"],
    "coa": ["C00010"],
    "coa-sh": ["C00010"],
    "coenzyme a": ["C00010"],
    "h2o": ["C00001"],
    "water": ["C00001"],
    "co2": ["C00011"],
    "carbon dioxide": ["C00011"],
    "ppi": ["C00013"],
    "pyrophosphate": ["C00013"],
    "diphosphate": ["C00013"],
    "pi": ["C00009"],
    "phosphate": ["C00009"],
    "orthophosphate": ["C00009"],
    "nh3": ["C00014"],
    "ammonia": ["C00014"],
    "h+": ["C00080"],
    "proton": ["C00080"],
    # Isoprenoid pathway
    "ipp": ["C00129"],
    "isopentenyl diphosphate": ["C00129"],
    "isopentenyl pyrophosphate": ["C00129"],
    "dmapp": ["C00235"],
    "dimethylallyl diphosphate": ["C00235"],
    "dimethylallyl pyrophosphate": ["C00235"],
    "ggpp": ["C00353"],
    "geranylgeranyl diphosphate": ["C00353"],
    "geranylgeranyl pyrophosphate": ["C00353"],
    "lycopene": ["C05432"],
    # KEGG splits phytoene into 15-cis (C05421) and all-trans (C05423).
    # Either is plausible mid-carotenoid-pathway, so we accept both.
    "phytoene": ["C05421", "C05423"],
    "15-cis-phytoene": ["C05421"],
    "all-trans-phytoene": ["C05423"],
    # Shikimate / phenylpropanoid (resveratrol, vanillin precursors)
    "tyrosine": ["C00082"],
    "l-tyrosine": ["C00082"],
    "phenylalanine": ["C00079"],
    "l-phenylalanine": ["C00079"],
    "shikimate": ["C00493"],
    "shikimic acid": ["C00493"],
    "chorismate": ["C00251"],
    "chorismic acid": ["C00251"],
    "p-coumaric acid": ["C00811"],
    "p-coumarate": ["C00811"],
    "4-coumaric acid": ["C00811"],
    "4-coumarate": ["C00811"],
    "p-coumaroyl-coa": ["C00223"],
    "4-coumaroyl-coa": ["C00223"],
    "ferulic acid": ["C01494"],
    "ferulate": ["C01494"],
    "feruloyl-coa": ["C00323"],
    "vanillin": ["C00755"],
    "resveratrol": ["C03582"],
    # Mevalonate / acetoacetyl pathway scaffolding
    "acetoacetyl-coa": ["C00332"],
    "(s)-mevalonate": ["C00418"],
    # Amorpha / artemisinin precursors
    "farnesyl diphosphate": ["C00448"],
    "farnesyl pyrophosphate": ["C00448"],
    "fpp": ["C00448"],
    "amorphadiene": ["C16028"],
    "artemisinic acid": ["C20459"],
}

_remote_cache: dict[str, list[str]] = {}


def _normalize(name: str) -> str:
    """Lowercase, collapse whitespace, strip outer punctuation noise."""
    if not isinstance(name, str):
        return ""
    s = name.strip().lower()
    # Strip a trailing arrow-fragment if a step-line sliver leaked in.
    s = re.split(r"\s*(?:->|→|=>)\s*", s)[0]
    # Strip leading/trailing parentheticals (e.g. "(activated)").
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    s = re.sub(r"^\s*\([^)]*\)\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Strip surrounding markdown emphasis if present.
    s = s.strip("*_`")
    return s


def resolve_compound_name(
    name: str,
    *,
    client: Optional[httpx.Client] = None,
    sleep_after: bool = True,
    use_remote_fallback: bool = True,
) -> list[str]:
    """Resolve a compound name to a list of KEGG compound IDs.

    Returns the full list of plausible C-IDs (most resolutions return a
    single ID; isomer-prone names return 2-3). Empty list when no match
    is confident enough — never guesses.

    ``client``: shared ``httpx.Client`` for amortized TCP setup. One is
    created and torn down per call when None.
    ``sleep_after``: when True (default), sleeps ``KEGG_SLEEP_S`` after
    a remote call to respect the public KEGG rate limit.
    ``use_remote_fallback``: set False in unit tests to avoid network.
    """
    norm = _normalize(name)
    if not norm:
        return []
    if norm in _LOCAL_LOOKUP:
        return list(_LOCAL_LOOKUP[norm])
    if not use_remote_fallback:
        return []
    if norm in _remote_cache:
        return list(_remote_cache[norm])
    return _resolve_remote(norm, client=client, sleep_after=sleep_after)


def _resolve_remote(
    norm: str,
    *,
    client: Optional[httpx.Client] = None,
    sleep_after: bool = True,
) -> list[str]:
    own_client = client is None
    c = client or httpx.Client(headers={"User-Agent": "MetaboAgent-eval/1.0"})
    try:
        try:
            r = c.get(f"{KEGG_FIND_BASE}/{quote(norm)}", timeout=KEGG_TIMEOUT_S)
        except httpx.HTTPError as e:
            log.warning("KEGG find failed for %r: %s", norm, e)
            return []
        if r.status_code != 200 or not r.text.strip():
            _remote_cache[norm] = []
            return []
        ids: list[str] = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            id_part, names_part = parts
            m = re.match(r"^cpd:(C\d{5})$", id_part.strip())
            if not m:
                continue
            cid = m.group(1)
            names = [n.strip().lower() for n in names_part.split(";")]
            if norm in names:
                ids.append(cid)
        seen: set[str] = set()
        uniq: list[str] = []
        for cid in ids:
            if cid not in seen:
                seen.add(cid)
                uniq.append(cid)
        _remote_cache[norm] = uniq
        return list(uniq)
    finally:
        if own_client:
            c.close()
        if sleep_after:
            time.sleep(KEGG_SLEEP_S)


def reset_remote_cache() -> None:
    """Test helper — clears the network-fallback cache only."""
    _remote_cache.clear()
