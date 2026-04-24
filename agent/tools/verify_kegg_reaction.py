"""
@tool verify_kegg_reaction — confirm a KEGG R-id exists before citing it.

Defensive check. The Phase 6.5-pre baseline measured 0/4 R-id
fabrications on actual emitted output, so this tool is not the
primary fix for hallucination; it is cheap insurance that covers
regression on larger eval sets and gives the model a way to
double-check when it is uncertain.

Design:
  - GET https://rest.kegg.jp/get/<rid>. 200 → exists, 404 → doesn't.
  - Module-scoped in-memory cache keyed by normalized id so the same
    R-id asked twice in one agent run costs one KEGG call.
  - DEMO_MODE=1 returns a stub so the demo mode contract (offline,
    no live fetches) is honoured from day one; this is the Phase 7
    contract wired in early.
  - Network / 5xx / timeout errors raise — the agent's tool_error
    path surfaces them to the user as a specific failure rather than
    silently claiming the id is invalid.
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
_TIMEOUT_S = 10  # verification must fit comfortably inside the agent loop
_RID_RE = re.compile(r"^(?:rn:)?(R\d{5})$", re.IGNORECASE)

_session = make_session(extra_headers={"Accept": "text/plain,*/*"})
_cache: dict[str, dict[str, Any]] = {}


def _normalize(reaction_id: str) -> Optional[str]:
    """'R00022' / 'rn:R00022' / 'RN:r00022' → 'R00022'. None if malformed."""
    if not isinstance(reaction_id, str):
        return None
    m = _RID_RE.match(reaction_id.strip())
    if not m:
        return None
    return m.group(1).upper()


def _demo_stub(rid: str) -> dict[str, Any]:
    return {
        "exists": False,
        "reaction_id": rid,
        "note": "live fetch disabled (DEMO_MODE=1)",
    }


def _parse_reaction_fields(text: str, rid: str) -> dict[str, Any]:
    sections = parse_entry(text)
    equation = " ".join(sections.get("EQUATION", [])).strip() or None
    name_raw = sections.get("NAME", [])
    name = " ; ".join(n.rstrip(";").strip() for n in name_raw)[:300] or None
    # ENZYME lines contain space-separated EC numbers like "2.3.3.10 2.3.3.8".
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


@tool(parse_docstring=True)
def verify_kegg_reaction(reaction_id: str) -> dict:
    """Verify that a KEGG reaction ID exists and return its canonical data.

    Use this to double-check any KEGG R-id you are about to cite. The
    tool is available — not mandatory — and costs one lightweight HTTP
    call (result cached for repeat lookups within an agent run).

    Args:
        reaction_id: KEGG reaction identifier in R##### form, optionally with an rn: prefix. Case-insensitive.

    Returns:
        Dict with keys: exists (bool), reaction_id (normalized),
        equation, name, ec_numbers (list). When the id does not parse
        or KEGG returns 404, exists is False and equation/name/ec_numbers
        are absent. When DEMO_MODE=1 is set, returns a stub with a note
        instead of calling the network.
    """
    norm = _normalize(reaction_id)
    if norm is None:
        return {
            "exists": False,
            "error": "malformed reaction id — expected R##### (optionally rn: prefixed)",
            "input": reaction_id,
        }

    if os.environ.get("DEMO_MODE") == "1":
        return _demo_stub(norm)

    cached = _cache.get(norm)
    if cached is not None:
        return cached

    url = f"{_BASE}/rn:{norm}"
    try:
        resp = _session.get(url, timeout=_TIMEOUT_S)
    except requests.Timeout as e:
        raise RuntimeError(f"KEGG timeout for {norm}: {e}") from e
    except requests.RequestException as e:
        raise RuntimeError(f"KEGG request failed for {norm}: {e}") from e

    if resp.status_code == 404:
        result: dict[str, Any] = {"exists": False, "reaction_id": norm}
    elif resp.status_code == 200 and resp.text.strip():
        result = _parse_reaction_fields(resp.text, norm)
    else:
        # 5xx or empty 200 — surface as an error so the agent doesn't
        # treat it as "doesn't exist" when the truth is "we don't know".
        raise RuntimeError(
            f"KEGG returned status {resp.status_code} for {norm}"
        )

    _cache[norm] = result
    return result
