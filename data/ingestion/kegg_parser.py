"""
KEGG flat-file parser.

Converts raw KEGG entries (saved by kegg_fetcher.py) into normalized
JSON documents ready for embedding.

Output files, one JSONL per type:
- data/processed/kegg_reactions.jsonl
- data/processed/kegg_compounds.jsonl
- data/processed/kegg_enzymes.jsonl
- data/processed/kegg_pathways.jsonl

Each JSONL record has:
    id              canonical KEGG id (e.g., R00024, C05432)
    doc_text        human-readable embedding input
    metadata        dict of structured fields for filter-based retrieval
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from config import PROCESSED_DATA_DIR, RAW_DATA_DIR

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

KEGG_RAW = RAW_DATA_DIR / "kegg"
LINKS_DIR = KEGG_RAW / "links"


# ---------- flat-file section parser ----------
_SECTION_RE = re.compile(r"^([A-Z_]{2,})\s+(.*)$")


def parse_entry(text: str) -> dict[str, list[str]]:
    """Split a KEGG flat-file entry into section -> list of lines."""
    sections: dict[str, list[str]] = defaultdict(list)
    current = None
    for raw in text.splitlines():
        if raw.startswith("///"):
            break
        if not raw.strip():
            continue
        m = _SECTION_RE.match(raw)
        if m and not raw.startswith(" "):
            current = m.group(1)
            sections[current].append(m.group(2).rstrip())
        else:
            if current is None:
                continue
            sections[current].append(raw.strip())
    return dict(sections)


# ---------- link tables ----------
def _load_link_table(path: Path) -> dict[str, list[str]]:
    """Load a KEGG link file (tab-separated: left<TAB>right) keyed by left id."""
    mapping: dict[str, list[str]] = defaultdict(list)
    if not path.exists():
        log.warning("Link table missing: %s", path)
        return mapping
    for line in path.read_text().splitlines():
        if "\t" not in line:
            continue
        left, right = line.split("\t", 1)
        mapping[left.strip()].append(right.strip())
    return dict(mapping)


def load_links() -> tuple[dict, dict, dict]:
    rxn_to_ec = _load_link_table(LINKS_DIR / "reaction_to_enzyme.tsv")
    rxn_to_path = _load_link_table(LINKS_DIR / "reaction_to_pathway.tsv")
    rxn_to_cpd = _load_link_table(LINKS_DIR / "reaction_to_compound.tsv")
    return rxn_to_ec, rxn_to_path, rxn_to_cpd


# ---------- per-type parsers ----------
def parse_reaction(text: str, links: tuple[dict, dict, dict]) -> dict | None:
    rxn_to_ec, rxn_to_path, rxn_to_cpd = links
    s = parse_entry(text)
    if "ENTRY" not in s:
        return None
    rxn_id = s["ENTRY"][0].split()[0]
    key = f"rn:{rxn_id}"
    equation = " ".join(s.get("EQUATION", []))
    name = " ".join(s.get("NAME", []))
    definition = " ".join(s.get("DEFINITION", []))
    ec_numbers = [e.replace("ec:", "") for e in rxn_to_ec.get(key, [])]
    pathway_ids = [p.replace("path:", "") for p in rxn_to_path.get(key, [])]
    compound_ids = [c.replace("cpd:", "") for c in rxn_to_cpd.get(key, [])]
    substrates, products = _split_equation(equation)

    doc_text = (
        f"KEGG Reaction {rxn_id}. Name: {name}. Definition: {definition}. "
        f"Equation: {equation}. EC numbers: {', '.join(ec_numbers) or 'n/a'}. "
        f"Pathways: {', '.join(pathway_ids) or 'n/a'}."
    )
    return {
        "id": rxn_id,
        "doc_text": doc_text,
        "metadata": {
            "kegg_id": rxn_id,
            "type": "reaction",
            "name": name,
            "equation": equation,
            "ec_numbers": ec_numbers,
            "pathway_ids": pathway_ids,
            "compound_ids": compound_ids,
            "substrates": substrates,
            "products": products,
        },
    }


def parse_compound(text: str) -> dict | None:
    s = parse_entry(text)
    if "ENTRY" not in s:
        return None
    cpd_id = s["ENTRY"][0].split()[0]
    names = [n.rstrip(";") for n in s.get("NAME", [])]
    formula = " ".join(s.get("FORMULA", [])).strip()
    mw_raw = " ".join(s.get("EXACT_MASS", []) or s.get("MOL_WEIGHT", [])).strip()
    try:
        mol_weight = float(mw_raw.split()[0]) if mw_raw else 0.0
    except ValueError:
        mol_weight = 0.0
    pathway_ids = _extract_referenced_ids(s.get("PATHWAY", []), prefix="map")
    reaction_ids = _extract_referenced_ids(s.get("REACTION", []), prefix="R")

    doc_text = (
        f"KEGG Compound {cpd_id}. Names: {'; '.join(names)}. "
        f"Formula: {formula}. MW: {mol_weight}. "
        f"Pathways: {', '.join(pathway_ids) or 'n/a'}."
    )
    return {
        "id": cpd_id,
        "doc_text": doc_text,
        "metadata": {
            "kegg_id": cpd_id,
            "type": "compound",
            "names": names,
            "primary_name": names[0] if names else "",
            "formula": formula,
            "molecular_weight": mol_weight,
            "pathway_ids": pathway_ids,
            "reaction_ids": reaction_ids,
        },
    }


def parse_enzyme(text: str) -> dict | None:
    s = parse_entry(text)
    if "ENTRY" not in s:
        return None
    parts = s["ENTRY"][0].split()
    ec_id = parts[1] if len(parts) > 1 and parts[0].upper() == "EC" else parts[0]
    names = [n.rstrip(";") for n in s.get("NAME", [])]
    sysname = " ".join(s.get("SYSNAME", []))
    reactions = _extract_referenced_ids(s.get("REACTION", []), prefix="R")
    substrates = [ln.split(";")[0] for ln in s.get("SUBSTRATE", [])]
    products = [ln.split(";")[0] for ln in s.get("PRODUCT", [])]
    organisms = s.get("GENES", [])  # list of "ORG: gene1 gene2 ..."
    org_codes = [ln.split(":", 1)[0].strip().lower() for ln in organisms if ":" in ln]

    doc_text = (
        f"EC {ec_id}. Names: {'; '.join(names)}. Systematic: {sysname}. "
        f"Substrates: {'; '.join(substrates[:5])}. Products: {'; '.join(products[:5])}. "
        f"Reactions: {', '.join(reactions) or 'n/a'}."
    )
    return {
        "id": ec_id,
        "doc_text": doc_text,
        "metadata": {
            "ec_number": ec_id,
            "type": "enzyme",
            "names": names,
            "sysname": sysname,
            "reaction_ids": reactions,
            "organism_codes": org_codes,
        },
    }


def parse_pathway(text: str) -> dict | None:
    s = parse_entry(text)
    if "ENTRY" not in s:
        return None
    path_id = s["ENTRY"][0].split()[0]
    name = " ".join(s.get("NAME", []))
    description = " ".join(s.get("DESCRIPTION", []))
    class_ = " ".join(s.get("CLASS", []))
    compound_ids = _extract_referenced_ids(s.get("COMPOUND", []), prefix="C")
    reaction_ids = _extract_referenced_ids(s.get("REACTION", []), prefix="R")
    module_ids = _extract_referenced_ids(s.get("MODULE", []), prefix="M")

    doc_text = (
        f"KEGG Pathway {path_id}. Name: {name}. Class: {class_}. "
        f"Description: {description}."
    )
    return {
        "id": path_id,
        "doc_text": doc_text,
        "metadata": {
            "pathway_id": path_id,
            "type": "pathway",
            "name": name,
            "class": class_,
            "compound_ids": compound_ids,
            "reaction_ids": reaction_ids,
            "module_ids": module_ids,
        },
    }


# ---------- helpers ----------
def _split_equation(equation: str) -> tuple[list[str], list[str]]:
    if not equation:
        return [], []
    arrow = "<=>" if "<=>" in equation else ("=>" if "=>" in equation else "=")
    if arrow not in equation:
        return [], []
    lhs, rhs = equation.split(arrow, 1)
    return _extract_compound_tokens(lhs), _extract_compound_tokens(rhs)


def _extract_compound_tokens(side: str) -> list[str]:
    return re.findall(r"\bC\d{5}\b", side)


def _extract_referenced_ids(lines: list[str], prefix: str) -> list[str]:
    ids: list[str] = []
    pattern = re.compile(rf"\b{prefix}\d{{4,5}}\b")
    for ln in lines:
        ids.extend(pattern.findall(ln))
    # de-duplicate while preserving order
    seen = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


# ---------- top-level ----------
def _parse_dir(src_dir: Path, out_path: Path, parse_fn, *args) -> int:
    if not src_dir.exists():
        log.warning("Missing source dir: %s", src_dir)
        return 0
    count = 0
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for file in sorted(src_dir.iterdir()):
            if not file.is_file() or file.suffix != ".txt":
                continue
            try:
                doc = parse_fn(file.read_text(), *args)
            except Exception as e:  # noqa: BLE001
                log.warning("Failed to parse %s: %s", file.name, e)
                continue
            if not doc:
                continue
            f.write(json.dumps(doc) + "\n")
            count += 1
    log.info("Wrote %d records to %s", count, out_path.name)
    return count


def parse_all() -> None:
    links = load_links()
    _parse_dir(KEGG_RAW / "reactions", PROCESSED_DATA_DIR / "kegg_reactions.jsonl", parse_reaction, links)
    _parse_dir(KEGG_RAW / "compounds", PROCESSED_DATA_DIR / "kegg_compounds.jsonl", parse_compound)
    _parse_dir(KEGG_RAW / "enzymes",   PROCESSED_DATA_DIR / "kegg_enzymes.jsonl",   parse_enzyme)
    _parse_dir(KEGG_RAW / "pathways",  PROCESSED_DATA_DIR / "kegg_pathways.jsonl",  parse_pathway)


if __name__ == "__main__":
    parse_all()
