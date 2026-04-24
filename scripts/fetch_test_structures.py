"""Fetch PubChem 2D PNG renders + canonical SMILES for the Phase 6 eval set.

Writes to eval/scenarios/structures/:
  <cid>_<slug>.png  — 2D depiction straight from PubChem
  ground_truth.json — {"<cid>": {"name", "canonical_smiles", "difficulty"}, ...}

PubChem REST is rate-limited (documented ~5 rps). The 500 ms sleep
between requests keeps us well below that ceiling and avoids 503s.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OUT_DIR = Path(__file__).resolve().parents[1] / "eval/scenarios/structures"

# (cid, name, difficulty) — difficulty follows the Phase 6 spec.
STRUCTURES: list[tuple[int, str, str]] = [
    # simple
    (2244, "aspirin", "simple"),
    (2519, "caffeine", "simple"),
    (5793, "glucose", "simple"),
    (750, "glycine", "simple"),
    (702, "ethanol", "simple"),
    # medium
    (3672, "ibuprofen", "medium"),
    (1060, "pyruvate", "medium"),
    (444493, "acetyl_coa", "medium"),
    (925, "nad_plus", "medium"),
    (5957, "atp", "medium"),
    (5997, "cholesterol", "medium"),
    (1183, "vanillin", "medium"),
    (68827, "artemisinin", "medium"),
    # hard
    (36314, "taxol", "hard"),
    (439230, "mevalonate", "hard"),
    (446925, "lycopene", "hard"),
    (643975, "fad", "hard"),
    (5311498, "coenzyme_b12", "hard"),
    # very hard
    (12560, "erythromycin", "very_hard"),
    (5284616, "rapamycin", "very_hard"),
]

SLEEP_S = 0.5
UA = "MetaboAgent-eval/0.1 (+https://github.com/; contact: hbsu)"


def _get(url: str, *, binary: bool) -> bytes | str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as resp:
        body = resp.read()
    return body if binary else body.decode("utf-8").strip()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    failures: list[tuple[int, str, str]] = []

    for i, (cid, name, difficulty) in enumerate(STRUCTURES):
        slug = _slug(name)
        png_path = OUT_DIR / f"{cid}_{slug}.png"
        print(f"[{i+1:>2}/{len(STRUCTURES)}] cid={cid} name={name} difficulty={difficulty}")

        try:
            png = _get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG",
                binary=True,
            )
            png_path.write_bytes(png)
            time.sleep(SLEEP_S)

            smiles = _get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/CanonicalSMILES/TXT",
                binary=False,
            )
            time.sleep(SLEEP_S)
        except (HTTPError, URLError, TimeoutError) as e:
            print(f"    FAIL: {type(e).__name__}: {e}")
            failures.append((cid, name, str(e)))
            continue

        manifest[str(cid)] = {
            "name": name,
            "canonical_smiles": smiles,
            "difficulty": difficulty,
            "image": png_path.name,
        }
        print(f"    ok: png={len(png)} bytes, smiles={smiles[:60]}{'…' if len(smiles) > 60 else ''}")

    (OUT_DIR / "ground_truth.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {len(manifest)}/{len(STRUCTURES)} entries to {OUT_DIR / 'ground_truth.json'}")
    if failures:
        print(f"failed: {len(failures)}")
        for cid, name, err in failures:
            print(f"  {cid} {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
