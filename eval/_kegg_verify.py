"""Eval-side KEGG ID verification (Phase 8.2 extraction).

The current pathway-hallucination eval calls ``rest.kegg.jp`` directly
with a hand-rolled httpx client and returns just a bool — fine for
"did this R-id resolve at all?" but useless for the substrate-relevance
work coming in Phase 8.3 / G4. This module:

  - Returns the parsed canonical fields (equation, name, ec_numbers /
    name, reactions) so callers can do downstream consistency checks.
  - Mirrors the production verify_* tools' regex normalization, KEGG
    parser, and module-scoped cache shape, so behavior stays consistent
    across the agent and the eval harness.
  - DOES NOT respect ``DEMO_MODE``. The production tools stub when
    DEMO_MODE=1; an eval that stubs verification cannot detect
    fabrication, which is the whole point.

Designed to be extended in 8.3 with a substrate-relevance check that
takes the parsed equation and a "claimed substrate" and decides whether
the ID is being cited in the right context.

Rate limit: 400 ms after each network call (KEGG anonymous ceiling is
~3 rps).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

import httpx

from data.ingestion.kegg_parser import parse_entry

log = logging.getLogger(__name__)

KEGG_BASE = "https://rest.kegg.jp/get"
KEGG_SLEEP_S = 0.4
KEGG_TIMEOUT_S = 10.0

_RID_RE = re.compile(r"^(?:rn:)?(R\d{5})$", re.IGNORECASE)
_EC_RE = re.compile(r"^(?:ec:|EC\s?)?(\d+\.\d+\.\d+\.\d+)$", re.IGNORECASE)

_reaction_cache: dict[str, dict[str, Any]] = {}
_ec_cache: dict[str, dict[str, Any]] = {}


# ---- normalization ---------------------------------------------------------

def _normalize_rid(reaction_id: str) -> Optional[str]:
    if not isinstance(reaction_id, str):
        return None
    m = _RID_RE.match(reaction_id.strip())
    return m.group(1).upper() if m else None


def _normalize_ec(ec_number: str) -> Optional[str]:
    if not isinstance(ec_number, str):
        return None
    m = _EC_RE.match(ec_number.strip())
    return m.group(1) if m else None


# ---- parsers (lifted from the production verify_* tools) ------------------

def _parse_reaction_fields(text: str, rid: str) -> dict[str, Any]:
    sections = parse_entry(text)
    equation = " ".join(sections.get("EQUATION", [])).strip() or None
    name_lines = sections.get("NAME", [])
    name = " ; ".join(n.rstrip(";").strip() for n in name_lines)[:300] or None
    ec_numbers: list[str] = []
    for line in sections.get("ENZYME", []):
        for tok in line.split():
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", tok):
                ec_numbers.append(tok)
    return {
        "exists": True,
        "reaction_id": rid,
        "equation": equation,
        "name": name,
        "ec_numbers": ec_numbers,
    }


def _parse_enzyme_fields(text: str, ec: str) -> dict[str, Any]:
    sections = parse_entry(text)
    names = sections.get("NAME", [])
    name = (names[0].rstrip(";").strip() if names else None) or None
    sysnames = sections.get("SYSNAME", [])
    sysname = (sysnames[0].strip() if sysnames else None) or None
    reactions: list[str] = []
    for line in sections.get("REACTION", []):
        for rid in re.findall(r"R\d{5}", line):
            if rid not in reactions:
                reactions.append(rid)
    for line in sections.get("ALL_REAC", []):
        for rid in re.findall(r"R\d{5}", line):
            if rid not in reactions:
                reactions.append(rid)
    return {
        "exists": True,
        "ec_number": ec,
        "name": name,
        "sysname": sysname,
        "reactions": reactions,
    }


# ---- public API ------------------------------------------------------------

def verify_kegg_reaction_id(
    reaction_id: str,
    *,
    client: httpx.Client | None = None,
    sleep_after: bool = True,
) -> dict[str, Any]:
    """Look up a KEGG reaction ID via the public REST endpoint.

    Returns a dict with at minimum ``exists`` (bool). When the id
    resolves, also returns ``reaction_id`` (normalized), ``equation``,
    ``name``, and ``ec_numbers``.

    ``client``: pass a shared ``httpx.Client`` to amortize TCP setup
    across many calls. One is created and torn down per call when None.
    ``sleep_after``: if True (default), sleeps ``KEGG_SLEEP_S`` after the
    network call so callers in tight loops respect KEGG's rate limit.
    """
    norm = _normalize_rid(reaction_id)
    if norm is None:
        return {
            "exists": False,
            "error": "malformed reaction id — expected R##### (optionally rn: prefixed)",
            "input": reaction_id,
        }

    cached = _reaction_cache.get(norm)
    if cached is not None:
        return cached

    own_client = client is None
    c = client or httpx.Client(headers={"User-Agent": "MetaboAgent-eval/1.0"})
    try:
        try:
            r = c.get(f"{KEGG_BASE}/rn:{norm}", timeout=KEGG_TIMEOUT_S)
        except httpx.HTTPError as e:
            log.warning("KEGG request failed for %s: %s", norm, e)
            return {"exists": False, "reaction_id": norm, "error": f"network: {e}"}
        if r.status_code == 200 and r.text.strip():
            result = _parse_reaction_fields(r.text, norm)
        elif r.status_code == 404:
            result = {"exists": False, "reaction_id": norm}
        else:
            log.warning("unexpected KEGG status %d for %s", r.status_code, norm)
            return {
                "exists": False,
                "reaction_id": norm,
                "error": f"status {r.status_code}",
            }
    finally:
        if own_client:
            c.close()
        if sleep_after:
            time.sleep(KEGG_SLEEP_S)

    _reaction_cache[norm] = result
    return result


def verify_ec_number(
    ec_number: str,
    *,
    client: httpx.Client | None = None,
    sleep_after: bool = True,
) -> dict[str, Any]:
    """Look up an EC number via the public KEGG REST endpoint.

    Returns a dict with at minimum ``exists`` (bool). When the EC
    resolves, also returns ``ec_number`` (normalized), ``name`` (the
    recommended name), ``sysname``, and ``reactions`` (list of R-ids).
    """
    norm = _normalize_ec(ec_number)
    if norm is None:
        return {
            "exists": False,
            "error": "malformed EC number — expected d.d.d.d (optionally EC/ec: prefixed)",
            "input": ec_number,
        }

    cached = _ec_cache.get(norm)
    if cached is not None:
        return cached

    own_client = client is None
    c = client or httpx.Client(headers={"User-Agent": "MetaboAgent-eval/1.0"})
    try:
        try:
            r = c.get(f"{KEGG_BASE}/ec:{norm}", timeout=KEGG_TIMEOUT_S)
        except httpx.HTTPError as e:
            log.warning("KEGG request failed for EC %s: %s", norm, e)
            return {"exists": False, "ec_number": norm, "error": f"network: {e}"}
        if r.status_code == 200 and r.text.strip():
            result = _parse_enzyme_fields(r.text, norm)
        elif r.status_code == 404:
            result = {"exists": False, "ec_number": norm}
        else:
            log.warning("unexpected KEGG status %d for EC %s", r.status_code, norm)
            return {
                "exists": False,
                "ec_number": norm,
                "error": f"status {r.status_code}",
            }
    finally:
        if own_client:
            c.close()
        if sleep_after:
            time.sleep(KEGG_SLEEP_S)

    _ec_cache[norm] = result
    return result
