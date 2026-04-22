"""
Verify the resolved MetaboAgent configuration.

Prints every infra-critical path and endpoint, notes whether each path
exists and is writable, and flags whether the utility LLM is configured.
Exits 0 on success; 1 if a required path can't be created or written.

Usage:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m scripts.verify_config
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import config


REQUIRED_PATHS = [
    "DATA_ROOT",
    "RAW_DATA_DIR",
    "PROCESSED_DATA_DIR",
    "CHROMADB_DIR",
    "LOG_DIR",
]


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def main() -> int:
    summary = config.resolved_config_summary()
    print("=== MetaboAgent resolved config ===")
    for key, value in summary.items():
        print(f"  {key:<24} = {value}")

    print("\n=== Path checks ===")
    failed = False
    for key in REQUIRED_PATHS:
        p = Path(getattr(config, key))
        ok = _writable(p)
        marker = "OK" if ok else "FAIL"
        print(f"  [{marker}] {key:<22} {p}")
        if not ok:
            failed = True

    print("\n=== LLM endpoints ===")
    print(f"  PRIMARY: {config.PRIMARY_LLM_BASE_URL} ({config.PRIMARY_LLM_MODEL_NAME})")
    if config.UTILITY_LLM_BASE_URL:
        print(f"  UTILITY: {config.UTILITY_LLM_BASE_URL} ({config.UTILITY_LLM_MODEL_NAME})")
    else:
        print("  UTILITY: (not configured — callers should fall back to primary)")

    print("\n=== Secret check (presence only) ===")
    print(f"  PRIMARY_LLM_API_KEY set: {bool(config.PRIMARY_LLM_API_KEY)}")
    if not config.PRIMARY_LLM_API_KEY:
        print("  NOTE: no API key in env — LLM-client construction will fail.")
        print("        Set PRIMARY_LLM_API_KEY (or VLLM_API_KEY) in .env or your shell.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
