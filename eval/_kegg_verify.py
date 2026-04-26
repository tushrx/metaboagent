"""Eval-side KEGG ID verification (Phase 8.2 extraction; 8.3.B substrate check).

The current pathway-hallucination eval calls ``rest.kegg.jp`` directly
with a hand-rolled httpx client and returns just a bool — fine for
"did this R-id resolve at all?" but useless for the substrate-relevance
work in Phase 8.3 / G4. This module:

  - Returns the parsed canonical fields (equation, name, ec_numbers /
    name, reactions) so callers can do downstream consistency checks.
  - Mirrors the production verify_* tools' regex normalization, KEGG
    parser, and module-scoped cache shape, so behavior stays consistent
    across the agent and the eval harness.
  - DOES NOT respect ``DEMO_MODE``. The production tools stub when
    DEMO_MODE=1; an eval that stubs verification cannot detect
    fabrication, which is the whole point.
  - Phase 8.3.B layers a substrate-relevance check on top of the
    existing equation extraction: ``get_reaction_compounds`` parses the
    LHS / RHS of the equation into KEGG compound IDs, and
    ``verify_reaction_substrate`` decides whether a claimed
    (substrate, product) pair is consistent with the reaction's
    chemistry. Direction-lenient because KEGG ``<=>`` notation is
    reversible — the agent can describe either direction.

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


# ---- substrate-relevance (Phase 8.3.B) ------------------------------------

# KEGG equations use a single ``<=>`` separator between substrates (LHS)
# and products (RHS). Compound IDs are ``Cnnnnn``; coefficients and
# parenthetical terms ride alongside but never collide with the C-ID
# regex.
_EQUATION_SEP = re.compile(r"\s*<=>\s*")
_CID_RE = re.compile(r"\bC\d{5}\b")


def get_reaction_compounds(
    reaction_id: str,
    *,
    client: httpx.Client | None = None,
    sleep_after: bool = True,
) -> dict[str, Any]:
    """Return ``{exists, substrates, products}`` for a KEGG reaction.

    ``substrates`` and ``products`` are lists of KEGG compound IDs
    parsed from the LHS / RHS of the equation. Empty lists when the
    reaction has no equation field or doesn't resolve.
    """
    info = verify_kegg_reaction_id(
        reaction_id, client=client, sleep_after=sleep_after,
    )
    if not info.get("exists"):
        return {
            "exists": False,
            "reaction_id": info.get("reaction_id"),
            "substrates": [],
            "products": [],
        }
    eq = info.get("equation") or ""
    parts = _EQUATION_SEP.split(eq, maxsplit=1)
    if len(parts) != 2:
        return {
            "exists": True,
            "reaction_id": info["reaction_id"],
            "substrates": [],
            "products": [],
            "equation": eq or None,
        }
    lhs, rhs = parts
    substrates = _CID_RE.findall(lhs)
    products = _CID_RE.findall(rhs)
    return {
        "exists": True,
        "reaction_id": info["reaction_id"],
        "substrates": substrates,
        "products": products,
        "equation": eq,
    }


def _classify_substrate_match(
    claimed_substrate_ids: list[str],
    claimed_product_ids: list[str],
    kegg_substrates: list[str],
    kegg_products: list[str],
) -> dict[str, Any]:
    """Pure classifier — separated for unit testing without network.

    Direction-lenient: a claimed compound matches if it appears on
    either side of the ``<=>`` separator. KEGG records reactions in
    one canonical direction, but most are reversible in vivo and the
    agent may describe either direction in a step line.
    """
    all_kegg = set(kegg_substrates) | set(kegg_products)
    sub_set = set(claimed_substrate_ids)
    prod_set = set(claimed_product_ids)
    substrate_matches = bool(sub_set & all_kegg)
    product_matches = bool(prod_set & all_kegg)

    if substrate_matches and product_matches:
        verdict = "fully_matches"
    elif substrate_matches:
        verdict = "substrate_only"
    elif product_matches:
        verdict = "product_only"
    else:
        verdict = "neither"

    return {
        "substrate_matches": substrate_matches,
        "product_matches": product_matches,
        "verdict": verdict,
    }


def verify_reaction_substrate(
    reaction_id: str,
    claimed_substrate: str,
    claimed_product: str,
    *,
    client: httpx.Client | None = None,
    sleep_after: bool = True,
    use_remote_resolver: bool = True,
) -> dict[str, Any]:
    """Verify whether the agent's claimed (substrate, product) pair is
    consistent with the KEGG reaction's chemistry.

    Returns a dict with:
      - ``rid_exists``        — did the R-ID resolve in KEGG?
      - ``substrate_matches`` — claimed substrate appears in equation?
      - ``product_matches``   — claimed product appears in equation?
      - ``substrate_resolved``— did the resolver find any C-ID for the
                                claimed substrate name?
      - ``product_resolved``  — same for the claimed product
      - ``kegg_substrates``   — LHS compounds (raw KEGG storage order)
      - ``kegg_products``     — RHS compounds
      - ``claimed_substrate_ids`` / ``claimed_product_ids`` — resolved
                                C-IDs the matcher used
      - ``verdict`` — one of {"rid_invalid", "fully_matches",
                              "substrate_only", "product_only",
                              "neither"}

    A ``"neither"`` verdict can mean either (a) the reaction's chemistry
    is unrelated to the claimed pair (the real-but-wrong-enzyme failure
    mode this verifier targets) or (b) one or both names didn't
    resolve. Callers distinguish via the ``substrate_resolved`` /
    ``product_resolved`` fields.

    Direction-lenient by design — see ``_classify_substrate_match``.
    """
    # Local import to keep the resolver optional for callers that only
    # want existence/equation lookup (and to keep the import graph
    # one-directional: the resolver does not import this module).
    from eval._kegg_name_resolver import resolve_compound_name

    compounds = get_reaction_compounds(
        reaction_id, client=client, sleep_after=sleep_after,
    )
    if not compounds["exists"]:
        return {
            "rid_exists": False,
            "substrate_matches": False,
            "product_matches": False,
            "substrate_resolved": False,
            "product_resolved": False,
            "kegg_substrates": [],
            "kegg_products": [],
            "claimed_substrate_ids": [],
            "claimed_product_ids": [],
            "verdict": "rid_invalid",
        }

    substrate_ids = resolve_compound_name(
        claimed_substrate,
        client=client,
        sleep_after=sleep_after,
        use_remote_fallback=use_remote_resolver,
    )
    product_ids = resolve_compound_name(
        claimed_product,
        client=client,
        sleep_after=sleep_after,
        use_remote_fallback=use_remote_resolver,
    )

    classification = _classify_substrate_match(
        substrate_ids, product_ids,
        compounds["substrates"], compounds["products"],
    )

    return {
        "rid_exists": True,
        "substrate_matches": classification["substrate_matches"],
        "product_matches": classification["product_matches"],
        "substrate_resolved": bool(substrate_ids),
        "product_resolved": bool(product_ids),
        "kegg_substrates": compounds["substrates"],
        "kegg_products": compounds["products"],
        "claimed_substrate_ids": substrate_ids,
        "claimed_product_ids": product_ids,
        "verdict": classification["verdict"],
    }
