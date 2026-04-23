"""
@tool design_expression_vector — recommend a plasmid backbone + regulatory
elements for heterologous expression, and emit a circular plasmid-map SVG.

The tool is rule-based (not an LLM call). For each supported host we encode a
small catalog of common backbones with their promoter, RBS/Kozak, selection
marker, induction cue, standard cloning sites, and a sensible affinity tag.

Promoter-strength preset
  "low"  → constitutive weak / leaky induction
  "med"  → standard inducible (default)
  "high" → strong induction, high-copy backbone

SVG output
  A compact circular plasmid map drawn with simple annotated arcs for
  backbone, promoter, gene insert, terminator, selection marker, and origin.
  The UI lifts the ``<plasmid-map>`` block out of the final answer and
  renders it with the ``.plasmid-map`` theme.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Literal, Optional

from langchain_core.tools import tool

log = logging.getLogger(__name__)

HostOrganism = Literal["ecoli", "scerevisiae", "cglutamicum", "bsubtilis", "pputida"]
PromoterStrength = Literal["low", "med", "high"]


_VECTOR_CATALOG: dict[str, dict[str, dict]] = {
    "ecoli": {
        "low": {
            "backbone": "pBAD24",
            "promoter": "pBAD (arabinose-inducible, tunable)",
            "rbs": "pBAD native RBS",
            "tag": "none",
            "selection": "ampR (100 μg/mL ampicillin)",
            "origin": "pBR322 (~20 copies)",
            "terminator": "rrnB T1",
            "cloning_sites": ["NcoI", "EcoRI", "HindIII"],
            "induction": "0.02–0.2% L-arabinose",
        },
        "med": {
            "backbone": "pET28a(+)",
            "promoter": "T7lac (IPTG-inducible)",
            "rbs": "g10 RBS (strong)",
            "tag": "N-terminal His6-thrombin",
            "selection": "kanR (50 μg/mL kanamycin)",
            "origin": "pMB1 (~40 copies)",
            "terminator": "T7 term",
            "cloning_sites": ["NdeI", "BamHI", "EcoRI", "XhoI"],
            "induction": "0.1–1.0 mM IPTG",
        },
        "high": {
            "backbone": "pETDuet-1 (high-copy, dual MCS)",
            "promoter": "T7lac ×2 (IPTG-inducible)",
            "rbs": "g10 RBS",
            "tag": "His6 + S-tag",
            "selection": "ampR (100 μg/mL)",
            "origin": "ColE1 (high-copy)",
            "terminator": "T7 term",
            "cloning_sites": ["NcoI", "BamHI", "NdeI", "XhoI"],
            "induction": "0.1–1.0 mM IPTG",
        },
    },
    "scerevisiae": {
        "low": {
            "backbone": "pYC2/CT",
            "promoter": "pCYC1 (low constitutive)",
            "rbs": "Kozak (GCCACC)",
            "tag": "C-terminal V5",
            "selection": "URA3 auxotrophic",
            "origin": "CEN6/ARS4 (single-copy)",
            "terminator": "CYC1 term",
            "cloning_sites": ["HindIII", "EcoRI", "XhoI"],
            "induction": "constitutive",
        },
        "med": {
            "backbone": "p416-GAL1",
            "promoter": "pGAL1 (galactose-inducible)",
            "rbs": "Kozak (GCCACC)",
            "tag": "optional C-terminal His6",
            "selection": "URA3 auxotrophic",
            "origin": "CEN6/ARS4",
            "terminator": "CYC1 term",
            "cloning_sites": ["EcoRI", "BamHI", "XhoI"],
            "induction": "2% galactose",
        },
        "high": {
            "backbone": "pYES2 (high-copy 2μ)",
            "promoter": "pGAL1 (galactose-inducible)",
            "rbs": "Kozak (GCCACC)",
            "tag": "N-terminal His6-TEV",
            "selection": "URA3",
            "origin": "2μ (~40 copies)",
            "terminator": "CYC1 term",
            "cloning_sites": ["HindIII", "BamHI", "EcoRI", "XhoI"],
            "induction": "2% galactose",
        },
    },
    "cglutamicum": {
        "med": {
            "backbone": "pEKEx2",
            "promoter": "Ptac (IPTG-inducible)",
            "rbs": "lacZ RBS",
            "tag": "none",
            "selection": "kanR (25 μg/mL)",
            "origin": "pBL1/pACYC (low-copy)",
            "terminator": "rrnB T1",
            "cloning_sites": ["BamHI", "EcoRI", "PstI"],
            "induction": "1 mM IPTG",
        },
        "high": {
            "backbone": "pVWEx1",
            "promoter": "Ptac (IPTG-inducible, strong)",
            "rbs": "lacZ RBS",
            "tag": "optional N-terminal Strep-II",
            "selection": "kanR",
            "origin": "pHM1519 (~15 copies)",
            "terminator": "rrnB T1",
            "cloning_sites": ["BamHI", "EcoRI", "SalI"],
            "induction": "1 mM IPTG",
        },
    },
    "bsubtilis": {
        "med": {
            "backbone": "pHT01",
            "promoter": "Pgrac (IPTG-inducible)",
            "rbs": "gsiB RBS",
            "tag": "optional C-terminal His6",
            "selection": "cmR (5 μg/mL chloramphenicol)",
            "origin": "pMB1 + theta (Bacillus)",
            "terminator": "lacZα term",
            "cloning_sites": ["BamHI", "XhoI", "SmaI"],
            "induction": "1 mM IPTG",
        },
    },
    "pputida": {
        "med": {
            "backbone": "pSEVA234",
            "promoter": "Ptrc (IPTG-inducible)",
            "rbs": "synthetic RBS",
            "tag": "none",
            "selection": "kanR",
            "origin": "RSF1010 (broad host)",
            "terminator": "T0/T1 combined",
            "cloning_sites": ["EcoRI", "PacI", "SpeI"],
            "induction": "0.5 mM IPTG",
        },
    },
}


_SUPPORTED_HOSTS = list(_VECTOR_CATALOG.keys())


def _resolve_host(host: str) -> str:
    h = (host or "").strip().lower()
    aliases = {
        "e. coli": "ecoli", "e.coli": "ecoli", "escherichia coli": "ecoli",
        "saccharomyces cerevisiae": "scerevisiae", "yeast": "scerevisiae",
        "corynebacterium glutamicum": "cglutamicum",
        "bacillus subtilis": "bsubtilis",
        "pseudomonas putida": "pputida",
    }
    if h in aliases:
        return aliases[h]
    return h if h in _VECTOR_CATALOG else "ecoli"


def _pick_preset(host_key: str, strength: str) -> tuple[str, dict]:
    s = (strength or "med").lower()
    table = _VECTOR_CATALOG[host_key]
    if s not in table:
        # fall back to the middle strength available for the host
        s = "med" if "med" in table else next(iter(table))
    return s, dict(table[s])


def _render_plasmid_svg(
    *, backbone: str, promoter: str, gene_label: str, terminator: str,
    selection: str, origin: str, tag: str,
) -> str:
    """Compact circular plasmid SVG. ~320×320 pixels, annotated arcs."""
    cx, cy, r = 160, 160, 110
    ring = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#0F6E56" stroke-width="3" />'

    # Arc segments (start_deg, end_deg, color, label).
    segments = [
        (300, 0,   "#0F6E56", f"P_promoter: {promoter[:24]}"),
        (0,   120, "#F5B02E", f"gene: {gene_label[:24]}"),
        (120, 150, "#6B7A8F", f"term: {terminator[:16]}"),
        (150, 220, "#1a1a2e", f"sel: {selection[:20]}"),
        (220, 300, "#9AA3B2", f"ori: {origin[:18]}"),
    ]

    def pt(deg: float, radius: float) -> tuple[float, float]:
        rad = math.radians(deg - 90)
        return cx + radius * math.cos(rad), cy + radius * math.sin(rad)

    arcs = []
    labels = []
    for start, end, color, label in segments:
        # SVG arc, outer ring offset so segments sit just outside the circle.
        outer_r = r + 8
        x1, y1 = pt(start, outer_r)
        x2, y2 = pt(end if end > start else end + 360, outer_r)
        large = 1 if ((end - start) % 360) > 180 else 0
        arcs.append(
            f'<path d="M {x1:.1f} {y1:.1f} A {outer_r} {outer_r} 0 {large} 1 '
            f'{x2:.1f} {y2:.1f}" fill="none" stroke="{color}" stroke-width="10" '
            f'stroke-linecap="round" />'
        )
        # Label at midpoint, pushed outside.
        mid = (start + (end if end > start else end + 360)) / 2
        lx, ly = pt(mid, outer_r + 22)
        anchor = "start" if lx > cx else "end"
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
            f'font-family="JetBrains Mono, monospace" font-size="10" '
            f'fill="#1a1a2e">{label}</text>'
        )

    center = [
        f'<text x="{cx}" y="{cy - 6}" text-anchor="middle" '
        f'font-family="Inter, sans-serif" font-size="14" font-weight="700" '
        f'fill="#0F6E56">{backbone}</text>',
        f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" '
        f'font-family="JetBrains Mono, monospace" font-size="10" '
        f'fill="#6B7A8F">tag: {tag}</text>',
    ]

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320" '
        f'role="img" aria-label="Plasmid map: {backbone}">'
        + ring
        + "".join(arcs)
        + "".join(labels)
        + "".join(center)
        + "</svg>"
    )
    return svg


@tool(parse_docstring=True)
def design_expression_vector(
    target_gene: str,
    host: HostOrganism = "ecoli",
    promoter_strength: PromoterStrength = "med",
) -> str:
    """Recommend an expression-vector design for a target gene in a host.

    Args:
        target_gene: Gene symbol or protein name (e.g., "crtE", "ADS", "GGPPS").
        host: Host chassis key, one of ecoli, scerevisiae, cglutamicum, bsubtilis, pputida.
        promoter_strength: One of "low", "med", "high". Defaults to "med".

    Returns:
        JSON string with ``recommendation`` (backbone + promoter + RBS + tag +
        selection + origin + cloning sites + induction cue) and
        ``plasmid_map_svg`` — an inline SVG ready to drop into a
        ``<plasmid-map>...</plasmid-map>`` block in the Final Answer.
    """
    host_key = _resolve_host(host)
    strength_used, preset = _pick_preset(host_key, promoter_strength)

    gene_label = (target_gene or "<gene>").strip() or "<gene>"
    svg = _render_plasmid_svg(
        backbone=preset["backbone"],
        promoter=preset["promoter"],
        gene_label=gene_label,
        terminator=preset["terminator"],
        selection=preset["selection"],
        origin=preset["origin"],
        tag=preset["tag"],
    )

    return json.dumps({
        "target_gene": gene_label,
        "host_requested": host,
        "host_resolved": host_key,
        "host_supported": host_key in _SUPPORTED_HOSTS,
        "promoter_strength_requested": promoter_strength,
        "promoter_strength_used": strength_used,
        "recommendation": preset,
        "plasmid_map_svg": svg,
        "notes": (
            "Rule-based recommendation — for novel hosts fall back to "
            "ecoli/scerevisiae pSEVA-style broad-host backbones and verify "
            "selection marker compatibility with the strain's auxotrophies."
        ),
    }, ensure_ascii=False)
