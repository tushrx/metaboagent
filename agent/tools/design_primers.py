"""
@tool design_primers — forward/reverse primer design for cloning a CDS.

Strategy
  1. Trim the gene sequence to its ORF boundaries if we can find them.
  2. Walk from each end expanding the primer length until its Tm (nearest-
     neighbor, BioPython ``MeltingTemp.Tm_NN``) falls within ``tm_target ± 2``
     AND the primer ends on a G/C-clamp when possible.
  3. Prepend cloning overhangs:
       - "gibson": 25 bp vector-homology arm from ``vector_flanks`` (caller
         supplies them; otherwise a standard pET28a NdeI/XhoI flank is used).
       - restriction site name from ``RE_SITES`` (e.g. "NdeI") adds the site
         plus a 3–4 bp protective overhang.

Safety
  The tool caps work on 10 kb of input. Longer inputs are truncated to the
  first 10 kb so the ReAct loop stays responsive.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from Bio.Seq import Seq
from Bio.SeqUtils import MeltingTemp as MT
from langchain_core.tools import tool

log = logging.getLogger(__name__)

_MAX_INPUT_LEN = 10_000
_PRIMER_MIN = 18
_PRIMER_MAX = 35
_TM_DEFAULT = 60.0
_TM_TOL = 2.0

# Common restriction sites: recognition sequence + 4 bp protective 5' cap.
RE_SITES: dict[str, str] = {
    "NdeI":   "CATATG",   # 5' cap: GGAATT
    "XhoI":   "CTCGAG",
    "BamHI":  "GGATCC",
    "EcoRI":  "GAATTC",
    "HindIII":"AAGCTT",
    "NcoI":   "CCATGG",
    "SalI":   "GTCGAC",
    "PstI":   "CTGCAG",
}
_PROTECTIVE_CAP = "GCGC"  # short 4 bp cap added 5' of RE sites

# Default pET28a flanking homology (NdeI...XhoI) for Gibson when the caller
# does not supply flanks of their own.
DEFAULT_GIBSON_FLANKS = (
    # 25 bp upstream of the NdeI cut (includes His-tag coding region)
    "GGCAGCAGCCATCATCATCATCATC",
    # 25 bp downstream of the XhoI cut
    "CTCGAGCACCACCACCACCACCACT",
)


def _clean_seq(seq: str) -> str:
    s = re.sub(r"\s+", "", (seq or "").upper())
    s = re.sub(r"[^ACGTN]", "", s)
    return s[:_MAX_INPUT_LEN]


def _find_orf(seq: str) -> tuple[int, int]:
    """Return (start, end) of the longest ORF in +1 reading frame, or (0,len)."""
    # Quick-and-dirty: pick the first ATG, then translate until a stop codon.
    m = re.search(r"ATG", seq)
    if not m:
        return 0, len(seq)
    start = m.start()
    end = start
    for i in range(start, len(seq) - 2, 3):
        codon = seq[i:i + 3]
        if codon in ("TAA", "TAG", "TGA"):
            end = i + 3
            break
    if end <= start:
        end = len(seq)
    return start, end


def _grow_primer(seq: str, *, tm_target: float, direction: str) -> str:
    """Grow a primer from one end until Tm is in target range.

    direction = "forward" → start at index 0 of the sense strand, grow the
        3' end outward. The primer IS the sense-strand substring.
    direction = "reverse" → take the last N bp of the sense strand and return
        their reverse complement; that antisense oligo anneals to the 3' end
        of the gene.

    We validate Tm / GC-clamp on the *primer itself* (not the template slice),
    so the 3'-end check lines up with the actual oligo we'll order.
    """
    if direction == "forward":
        best = seq[:_PRIMER_MIN]
        for length in range(_PRIMER_MIN, _PRIMER_MAX + 1):
            candidate = seq[:length]
            if _ok_primer(candidate, tm_target):
                return candidate
            best = candidate
        return best
    else:
        tail = seq[-_PRIMER_MAX:] if len(seq) > _PRIMER_MAX else seq
        best = ""
        for length in range(_PRIMER_MIN, _PRIMER_MAX + 1):
            if length > len(tail):
                break
            template_slice = tail[-length:]
            primer = str(Seq(template_slice).reverse_complement())
            if _ok_primer(primer, tm_target):
                return primer
            best = primer
        return best or str(Seq(tail[-_PRIMER_MIN:]).reverse_complement())


def _ok_primer(primer: str, tm_target: float) -> bool:
    if len(primer) < _PRIMER_MIN:
        return False
    try:
        tm = MT.Tm_NN(primer)
    except Exception:  # noqa: BLE001
        return False
    if abs(tm - tm_target) > _TM_TOL:
        return False
    # G/C-clamp preference at the 3' end (last base is G or C).
    if primer[-1] not in "GC":
        return False
    return True


def _gc(seq: str) -> float:
    if not seq:
        return 0.0
    return round(100 * (seq.count("G") + seq.count("C")) / len(seq), 1)


def _tm(seq: str) -> Optional[float]:
    if not seq or len(seq) < 6:
        return None
    try:
        return round(MT.Tm_NN(seq), 1)
    except Exception:  # noqa: BLE001
        return None


def _add_overhangs(
    fwd: str, rev: str, cloning_strategy: str,
    re_enzyme: Optional[str], vector_flanks: Optional[tuple[str, str]],
) -> tuple[str, str, dict]:
    """Return (fwd_full, rev_full, metadata)."""
    strategy = (cloning_strategy or "gibson").lower()
    if strategy == "gibson":
        upstream, downstream = vector_flanks or DEFAULT_GIBSON_FLANKS
        fwd_full = upstream + fwd
        # Downstream flank is in the same strand as the gene end, so we must
        # reverse-complement it before annealing to the sense-strand 3' end.
        rev_full = str(Seq(downstream).reverse_complement()) + rev
        return fwd_full, rev_full, {
            "strategy": "gibson",
            "upstream_flank": upstream,
            "downstream_flank": downstream,
        }
    if strategy in ("restriction", "re", "site"):
        name = re_enzyme or "NdeI"
        if name not in RE_SITES:
            name = "NdeI"
        site = RE_SITES[name]
        fwd_full = _PROTECTIVE_CAP + site + fwd
        rev_full = _PROTECTIVE_CAP + site + rev
        return fwd_full, rev_full, {
            "strategy": "restriction",
            "restriction_enzyme": name,
            "recognition_site": site,
            "protective_cap": _PROTECTIVE_CAP,
        }
    # Unknown strategy → return bare primers.
    return fwd, rev, {"strategy": "bare"}


@tool
def design_primers(
    gene_sequence: str,
    tm_target: float = 60.0,
    cloning_strategy: str = "gibson",
    re_enzyme: str = "NdeI",
    vector_upstream_flank: str = "",
    vector_downstream_flank: str = "",
) -> str:
    """Design forward/reverse cloning primers for a gene CDS.

    Args:
        gene_sequence: DNA sequence (A/C/G/T/N, case-insensitive). Whitespace
            and FASTA-style newlines are tolerated. Capped at 10 kb.
        tm_target: Target melting temperature in °C (default 60).
        cloning_strategy: "gibson" (adds 25-bp vector-homology arms) or
            "restriction" (adds an RE site + protective cap).
        re_enzyme: Restriction enzyme name for the "restriction" strategy —
            one of NdeI, XhoI, BamHI, EcoRI, HindIII, NcoI, SalI, PstI.
        vector_upstream_flank / vector_downstream_flank: Optional 20–30 nt
            flanks from your destination vector (Gibson only). When omitted,
            pET28a NdeI/XhoI defaults are used.

    Returns:
        JSON string with ``forward_primer`` / ``reverse_primer`` (with
        overhangs), their Tm and GC%, the annealing (body) segments, the
        amplicon length, and the applied cloning strategy's metadata.
    """
    seq = _clean_seq(gene_sequence)
    if len(seq) < _PRIMER_MIN * 2:
        return json.dumps({"error": "sequence too short (need at least 36 bp of CDS)"})

    start, end = _find_orf(seq)
    core = seq[start:end]

    fwd_body = _grow_primer(core, tm_target=tm_target, direction="forward")
    rev_body = _grow_primer(core, tm_target=tm_target, direction="reverse")

    flanks = None
    if vector_upstream_flank or vector_downstream_flank:
        flanks = (
            _clean_seq(vector_upstream_flank)[:40] or DEFAULT_GIBSON_FLANKS[0],
            _clean_seq(vector_downstream_flank)[:40] or DEFAULT_GIBSON_FLANKS[1],
        )
    fwd_full, rev_full, strategy_meta = _add_overhangs(
        fwd_body, rev_body, cloning_strategy, re_enzyme, flanks,
    )

    return json.dumps({
        "input_length": len(seq),
        "orf_start": start,
        "orf_end": end,
        "amplicon_length": end - start,
        "forward_primer": fwd_full,
        "reverse_primer": rev_full,
        "forward_body": fwd_body,
        "reverse_body": rev_body,
        "forward": {
            "length": len(fwd_full),
            "tm_body_c": _tm(fwd_body),
            "gc_percent_body": _gc(fwd_body),
            "ends_gc_clamp": fwd_body[-1] in "GC" if fwd_body else False,
        },
        "reverse": {
            "length": len(rev_full),
            "tm_body_c": _tm(rev_body),
            "gc_percent_body": _gc(rev_body),
            "ends_gc_clamp": rev_body[-1] in "GC" if rev_body else False,
        },
        "tm_target_c": tm_target,
        "cloning": strategy_meta,
        "notes": (
            "Tm is calculated with BioPython MeltingTemp.Tm_NN "
            "(nearest-neighbor, default parameters). Review secondary "
            "structure / primer-dimer risk in IDT OligoAnalyzer before "
            "ordering."
        ),
    }, ensure_ascii=False)
