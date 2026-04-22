"""
Storage-migration helper — copy data/chroma/logs to /mnt/storage_sdd (or any
target) without deleting the source.

Phase 2 ships this as a read-only planner by default: it prints what would
be copied (via `rsync --dry-run`) and exits. Pass `--apply` to actually
copy. It never deletes the source — the operator removes the repo-local
copies themselves once the new target is validated.

Rationale (from codex_target_deployment.md §4):
- root disk is near-full; data/raw, data/processed, data/chromadb, logs
  should live on the secondary SSD.
- Phase 1 exposed env-driven paths (METABOAGENT_DATA_ROOT, ...,
  METABOAGENT_CHROMADB_DIR, METABOAGENT_LOG_DIR). This script physically
  stages the files; the operator then sets the env vars.

Usage
-----
    # Default: print the rsync plan against /mnt/storage_sdd/metaboagent
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m scripts.migrate_storage

    # Custom target root
    python3 -m scripts.migrate_storage --target /mnt/other/metaboagent

    # Actually copy (non-destructive; source is untouched)
    python3 -m scripts.migrate_storage --apply

    # Only a subset
    python3 -m scripts.migrate_storage --only chromadb logs --apply

After --apply succeeds, set these in the shell profile or systemd unit:
    export METABOAGENT_DATA_ROOT=<target>/data
    export METABOAGENT_LOG_DIR=<target>/logs
    export METABOAGENT_MODEL_CACHE_DIR=<target>/hf-cache   # optional

Caveats
-------
- ChromaDB persistence includes SQLite + HNSW files; rsync -a handles these
  fine for a stopped (or read-only) Chroma client. The UI/agent should be
  stopped during the copy to avoid mid-write artifacts. The script warns
  if a Chroma client appears to be running.
- Re-running is safe: rsync skips unchanged files.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import config


DEFAULT_TARGET = Path("/mnt/storage_sdd/metaboagent")

# (label, source_path, target_subpath)
STAGES = [
    ("raw",       config.RAW_DATA_DIR,       "data/raw"),
    ("processed", config.PROCESSED_DATA_DIR, "data/processed"),
    ("chromadb",  config.CHROMADB_DIR,       "data/chromadb"),
    ("logs",      config.LOG_DIR,            "logs"),
]


def _has_rsync() -> bool:
    return shutil.which("rsync") is not None


def _looks_like_chroma_in_use(chroma_dir: Path) -> bool:
    """Heuristic: if sqlite lock files exist, Chroma may be open."""
    if not chroma_dir.exists():
        return False
    for lock in chroma_dir.rglob("*.sqlite3-wal"):
        if lock.stat().st_size > 0:
            return True
    for lock in chroma_dir.rglob("*.sqlite3-shm"):
        return True
    return False


def _run_rsync(src: Path, dst: Path, apply: bool) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    # Trailing slash on src -> copy *contents* of src into dst
    cmd = ["rsync", "-a", "--human-readable", "--stats"]
    if not apply:
        cmd.append("--dry-run")
    cmd.extend([f"{src}/", f"{dst}/"])
    print(f"  $ {' '.join(cmd)}")
    return subprocess.call(cmd)


def _fallback_copy(src: Path, dst: Path, apply: bool) -> int:
    """Used when rsync is unavailable. Copies files tree-wise."""
    if not apply:
        count = sum(1 for _ in src.rglob("*"))
        print(f"  (plan) {count} entries would be copied under {dst}")
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == item.stat().st_size:
                continue
            shutil.copy2(item, target)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default=str(DEFAULT_TARGET),
                    help="Target root (default: %(default)s)")
    ap.add_argument("--only", nargs="+", choices=[s[0] for s in STAGES],
                    help="Restrict to specific stages")
    ap.add_argument("--apply", action="store_true",
                    help="Actually copy. Default is dry-run.")
    args = ap.parse_args()

    target_root = Path(args.target).expanduser().resolve()
    stages = [s for s in STAGES if not args.only or s[0] in args.only]

    print(f"=== Migration plan (apply={args.apply}) ===")
    print(f"  target_root = {target_root}")
    for label, src, _ in stages:
        exists = "exists" if src.exists() else "MISSING"
        size = ""
        if src.exists():
            try:
                n_files = sum(1 for _ in src.rglob("*") if _.is_file())
                size = f" ({n_files} files)"
            except OSError:
                pass
        print(f"  {label:<9} {src}  [{exists}{size}]")

    # Safety: warn on Chroma in use
    if any(s[0] == "chromadb" for s in stages) and _looks_like_chroma_in_use(config.CHROMADB_DIR):
        print("\n  WARNING: ChromaDB lock/wal files present. Stop the UI/agent before --apply.")
        if args.apply:
            print("  Refusing --apply while Chroma appears in use. Stop processes and retry.")
            return 2

    if not _has_rsync():
        print("  NOTE: rsync not found on PATH; falling back to shutil.copy2.")

    print()
    rc = 0
    for label, src, sub in stages:
        dst = target_root / sub
        if not src.exists():
            print(f"[{label}] source missing, skipping: {src}")
            continue
        print(f"[{label}] {src} -> {dst}")
        if _has_rsync():
            code = _run_rsync(src, dst, apply=args.apply)
        else:
            code = _fallback_copy(src, dst, apply=args.apply)
        if code != 0:
            print(f"  {label}: FAILED (rc={code})")
            rc = code

    print()
    if not args.apply:
        print("(dry run — nothing copied. Re-run with --apply to actually copy.)")
        print("After --apply, set these env vars:")
        print(f"  export METABOAGENT_DATA_ROOT={target_root}/data")
        print(f"  export METABOAGENT_LOG_DIR={target_root}/logs")
    else:
        print("Copy complete. The original source files are unchanged.")
        print("Point the app at the new location via the env vars above, then")
        print("verify with:  python3 -m scripts.verify_config")
    return rc


if __name__ == "__main__":
    sys.exit(main())
