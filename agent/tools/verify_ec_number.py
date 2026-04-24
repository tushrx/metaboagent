"""
@tool verify_ec_number — confirm an EC number exists before citing it.

Companion to verify_kegg_reaction. Same design: module-scoped cache,
DEMO_MODE stub, network errors raise. Hits
https://rest.kegg.jp/get/ec:<ec>, which returns the full enzyme entry
(SYSNAME, REACTION cross-refs, etc.).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import requests
from langchain_core.tools import tool

from agent.tools._http import make_session
from data.ingestion.kegg_parser import parse_entry

log = logging.getLogger(__name__)

_BASE = "https://rest.kegg.jp/get"
_TIMEOUT_S = 10
# Accept "1.2.3.4", "ec:1.2.3.4", "EC 1.2.3.4". Partial (incomplete) EC
# classes like "1.-.-.-" are NOT accepted here — the product's use case
# is citing a concrete enzyme, not a class.
_EC_RE = re.compile(r"^(?:ec:|EC\s?)?(\d+\.\d+\.\d+\.\d+)$", re.IGNORECASE)

_session = make_session(extra_headers={"Accept": "text/plain,*/*"})
_cache: dict[str, dict[str, Any]] = {}


def _normalize(ec_number: str) -> Optional[str]:
    if not isinstance(ec_number, str):
        return None
    m = _EC_RE.match(ec_number.strip())
    if not m:
        return None
    return m.group(1)


def _demo_stub(ec: str) -> dict[str, Any]:
    return {
        "exists": False,
        "ec_number": ec,
        "note": "live fetch disabled (DEMO_MODE=1)",
    }


def _parse_enzyme_fields(text: str, ec: str) -> dict[str, Any]:
    sections = parse_entry(text)
    names = sections.get("NAME", [])
    recommended_name = (names[0].rstrip(";").strip() if names else None) or None
    sysnames = sections.get("SYSNAME", [])
    sysname = (sysnames[0].strip() if sysnames else None) or None
    # REACTION lines contain references like "[RN:R00022 R00479]"; extract Rids.
    reactions: list[str] = []
    for line in sections.get("REACTION", []):
        for rid in re.findall(r"R\d{5}", line):
            if rid not in reactions:
                reactions.append(rid)
    # Also ALL_REAC sometimes carries the canonical R-id list.
    for line in sections.get("ALL_REAC", []):
        for rid in re.findall(r"R\d{5}", line):
            if rid not in reactions:
                reactions.append(rid)
    return {
        "exists": True,
        "ec_number": ec,
        "recommended_name": recommended_name,
        "sysname": sysname,
        "reactions": reactions,
    }


@tool(parse_docstring=True)
def verify_ec_number(ec_number: str) -> dict:
    """Verify that an EC number exists and return the enzyme it names.

    Use this to double-check any EC number you are about to cite.
    Returns the recommended name, systematic name, and the KEGG
    reactions the enzyme catalyses. Results are cached per agent run.

    Args:
        ec_number: Enzyme Commission number in dotted form like 1.3.99.31, optionally with an EC or ec: prefix. Partial-class IDs (1.-.-.-) are not accepted.

    Returns:
        Dict with keys: exists (bool), ec_number (normalized),
        recommended_name, sysname, reactions (list of R-ids). On
        malformed input or 404: exists False and the other fields
        absent. When DEMO_MODE=1, returns a stub instead of hitting
        the network.
    """
    norm = _normalize(ec_number)
    if norm is None:
        return {
            "exists": False,
            "error": "malformed EC number — expected d.d.d.d (optionally EC/ec: prefixed)",
            "input": ec_number,
        }

    if os.environ.get("DEMO_MODE") == "1":
        return _demo_stub(norm)

    cached = _cache.get(norm)
    if cached is not None:
        return cached

    url = f"{_BASE}/ec:{norm}"
    try:
        resp = _session.get(url, timeout=_TIMEOUT_S)
    except requests.Timeout as e:
        raise RuntimeError(f"KEGG timeout for EC {norm}: {e}") from e
    except requests.RequestException as e:
        raise RuntimeError(f"KEGG request failed for EC {norm}: {e}") from e

    if resp.status_code == 404:
        result: dict[str, Any] = {"exists": False, "ec_number": norm}
    elif resp.status_code == 200 and resp.text.strip():
        result = _parse_enzyme_fields(resp.text, norm)
    else:
        raise RuntimeError(
            f"KEGG returned status {resp.status_code} for EC {norm}"
        )

    _cache[norm] = result
    return result
