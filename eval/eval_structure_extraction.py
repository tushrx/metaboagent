"""Phase 6.4 accuracy evaluation for parse_structure_image.

Loads eval/scenarios/structures/ground_truth.json, invokes the tool
directly (not via /chat — we want to isolate the tool's behaviour from
agent-loop orchestration), and scores each result into one of four
buckets:

  PASS_STRICT  extracted rdkit_canonical == ground-truth canonical SMILES
               (both re-canonicalised through RDKit to guard against
               PubChem/RDKit canonical-form drift)
  PASS_INCHI   extracted inchi_key == ground-truth inchi_key
               (credit structurally equivalent representations —
               component ordering, protonation, tautomers)
  PARTIAL      model returned RDKit-valid SMILES but wrong molecule
               (inchi_key differs from ground truth)
  FAIL         model returned no SMILES or RDKit rejected it

Writes eval/results/structure_extraction_<timestamp>.json with per-
image verdicts and a roll-up by difficulty tier.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit import RDLogger

RDLogger.DisableLog("rdApp.*")

REPO_ROOT = Path(__file__).resolve().parents[1]
STRUCTURES_DIR = REPO_ROOT / "eval/scenarios/structures"
RESULTS_DIR = REPO_ROOT / "eval/results"

Verdict = str  # "PASS_STRICT" | "PASS_INCHI" | "PARTIAL" | "FAIL"
BUCKET_ORDER = ("PASS_STRICT", "PASS_INCHI", "PARTIAL", "FAIL")
DIFFICULTY_ORDER = ("simple", "medium", "hard", "very_hard")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval")


def _rdkit_canonical(smiles: str) -> str | None:
    mol = Chem.MolFromSmiles(smiles)
    return Chem.MolToSmiles(mol) if mol is not None else None


def _verdict(extracted: dict[str, Any], truth: dict[str, Any]) -> Verdict:
    extracted_canon = extracted.get("rdkit_canonical")
    extracted_key = extracted.get("inchi_key")
    truth_canon = _rdkit_canonical(truth["canonical_smiles"])
    truth_key = truth.get("inchi_key")

    if not extracted.get("smiles") or not extracted_canon:
        return "FAIL"
    if truth_canon and extracted_canon == truth_canon:
        return "PASS_STRICT"
    if truth_key and extracted_key and extracted_key == truth_key:
        return "PASS_INCHI"
    return "PARTIAL"


def _run_one(cid: str, truth: dict, tool) -> dict:
    png_path = STRUCTURES_DIR / truth["image"]
    data = png_path.read_bytes()
    b64 = base64.b64encode(data).decode()

    log.info(
        "CID %s (%s, %s): invoking tool on %s (%d bytes)…",
        cid, truth["name"], truth["difficulty"], truth["image"], len(data),
    )
    try:
        extracted = tool.invoke(
            {"image_data_base64": b64, "mime_type": "image/png"},
        )
    except Exception as e:
        log.exception("tool raised for CID %s", cid)
        extracted = {
            "smiles": None,
            "confidence": "low",
            "alternative_smiles": [],
            "notes": f"tool exception: {type(e).__name__}: {e}",
            "rdkit_canonical": None,
            "inchi_key": None,
            "formula": None,
        }

    verdict = _verdict(extracted, truth)
    log.info(
        "  verdict=%s  extracted_smiles=%r  extracted_inchi_key=%s",
        verdict,
        extracted.get("smiles"),
        extracted.get("inchi_key"),
    )
    return {
        "cid": cid,
        "name": truth["name"],
        "difficulty": truth["difficulty"],
        "image": truth["image"],
        "ground_truth_smiles": truth["canonical_smiles"],
        "ground_truth_inchi_key": truth.get("inchi_key"),
        "extracted": extracted,
        "verdict": verdict,
    }


def _rollup(rows: list[dict]) -> dict[str, Any]:
    by_difficulty: dict[str, dict[str, int]] = {
        d: {b: 0 for b in BUCKET_ORDER} for d in DIFFICULTY_ORDER
    }
    overall: dict[str, int] = {b: 0 for b in BUCKET_ORDER}
    for r in rows:
        overall[r["verdict"]] += 1
        by_difficulty[r["difficulty"]][r["verdict"]] += 1
    return {
        "overall": overall,
        "overall_n": sum(overall.values()),
        "by_difficulty": by_difficulty,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=None,
        help="run only the first N structures (debug).",
    )
    parser.add_argument(
        "--cids", type=str, default=None,
        help="comma-separated CID list; only these structures are scored. "
             "Overrides --limit. Useful for re-running specific timeouts.",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="explicit output path; default is eval/results/structure_extraction_<ts>.json",
    )
    args = parser.parse_args()

    gt_path = STRUCTURES_DIR / "ground_truth.json"
    if not gt_path.is_file():
        log.error("ground_truth.json not found at %s — run scripts/fetch_test_structures.py", gt_path)
        return 1
    ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))

    # Import late so argparse --help works even if e.g. rdkit isn't installed.
    from agent.tools.parse_structure_image import parse_structure_image

    # Order by difficulty then CID so the log reads in a sensible order.
    items = sorted(
        ground_truth.items(),
        key=lambda kv: (DIFFICULTY_ORDER.index(kv[1]["difficulty"]), int(kv[0])),
    )
    if args.cids:
        wanted = {c.strip() for c in args.cids.split(",") if c.strip()}
        missing = wanted - set(ground_truth)
        if missing:
            log.error("CID(s) not in ground truth: %s", sorted(missing))
            return 1
        items = [kv for kv in items if kv[0] in wanted]
    elif args.limit:
        items = items[: args.limit]

    rows: list[dict] = []
    for cid, truth in items:
        rows.append(_run_one(cid, truth, parse_structure_image))

    summary = _rollup(rows)

    # Build output path.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.output) if args.output else RESULTS_DIR / f"structure_extraction_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "timestamp_utc": ts,
                "model": "PRIMARY_LLM (E4B via parse_structure_image)",
                "summary": summary,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    log.info("wrote %s", out_path)
    _print_summary(summary, out_path)
    return 0


def _print_summary(summary: dict, out_path: Path) -> None:
    overall = summary["overall"]
    n = summary["overall_n"]
    print()
    print("=" * 66)
    print(f"Structure extraction eval — {n} images")
    print("=" * 66)
    print(f"{'bucket':<14} {'count':>6} {'pct':>8}")
    for b in BUCKET_ORDER:
        c = overall[b]
        pct = (100.0 * c / n) if n else 0.0
        print(f"  {b:<12} {c:>6} {pct:>7.1f}%")

    print()
    print(f"{'tier':<12} {'n':>4} " + " ".join(f"{b:>12}" for b in BUCKET_ORDER))
    for d in DIFFICULTY_ORDER:
        row = summary["by_difficulty"][d]
        total = sum(row.values())
        parts = []
        for b in BUCKET_ORDER:
            c = row[b]
            pct = (100.0 * c / total) if total else 0.0
            parts.append(f"{c:>4} ({pct:>4.0f}%)")
        print(f"{d:<12} {total:>4} " + " ".join(f"{p:>12}" for p in parts))
    print()
    print(f"results: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
