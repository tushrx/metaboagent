"""
MetaboAgent — Central Configuration
All paths, API endpoints, model settings, and constants.

Phase 1 (2026-04-21) refactor:
- Paths (data / raw / processed / chromadb / logs / model cache) are now
  driven by environment variables so the repo can relocate large assets to
  `/mnt/storage_sdd` without breaking local development. Defaults preserve
  the original repo-local layout.
- LLM endpoints are now expressed as `PRIMARY_LLM_*` / `UTILITY_LLM_*` so
  the app can eventually route between a reasoning model (GPUs 0,1) and a
  utility model (GPUs 2,3) as described in codex_target_deployment.md.
  The legacy `VLLM_*` names remain as aliases for backward compatibility.

Environment variables (all optional; defaults match Day-1 behavior):

    # Storage
    METABOAGENT_DATA_ROOT          default: <repo>/data
    METABOAGENT_RAW_DATA_DIR       default: $METABOAGENT_DATA_ROOT/raw
    METABOAGENT_PROCESSED_DATA_DIR default: $METABOAGENT_DATA_ROOT/processed
    METABOAGENT_CHROMADB_DIR       default: $METABOAGENT_DATA_ROOT/chromadb
    METABOAGENT_LOG_DIR            default: <repo>/logs
    METABOAGENT_MODEL_CACHE_DIR    default: unset (HF uses its own default);
                                   if set and HF_HOME is unset, HF_HOME is
                                   populated from this value.

    # Primary/default-tier LLM. Phase 2 topology: Gemma 4 E4B on GPU 0
    # serving on port 8001. (Day-1 had this pointing at 31B dense on :8000;
    # v2 makes E4B the default agentic/tool-calling tier.)
    PRIMARY_LLM_BASE_URL      default: http://127.0.0.1:8001/v1
    PRIMARY_LLM_MODEL_NAME    default: google/gemma-4-E4B-it
    PRIMARY_LLM_API_KEY       default: $VLLM_API_KEY if set, else None.
                              Import never raises; call
                              ``get_primary_llm_api_key()`` at the point an
                              LLM client is constructed to enforce presence.

    # Utility / fast LLM (default target: GPUs 2,3 on port 8001)
    # Unset => utility model is not configured; callers should fall back
    # to the primary model until the second service is deployed.
    UTILITY_LLM_BASE_URL      default: unset
    UTILITY_LLM_MODEL_NAME    default: unset
    UTILITY_LLM_API_KEY       default: $PRIMARY_LLM_API_KEY

Example: relocate data and caches to the secondary SSD:

    export METABOAGENT_DATA_ROOT=/mnt/storage_sdd/metaboagent/data
    export METABOAGENT_LOG_DIR=/mnt/storage_sdd/metaboagent/logs
    export METABOAGENT_MODEL_CACHE_DIR=/mnt/storage_sdd/hf-cache

See `scripts/verify_config.py` for a quick resolved-config dump.
"""
from __future__ import annotations

import logging as _logging
import os as _os
from pathlib import Path

_log = _logging.getLogger(__name__)

# === Project Paths ===
PROJECT_ROOT = Path(__file__).parent


def _path_from_env(var: str, default: Path) -> Path:
    """Resolve `var` from env to an absolute Path, else use `default`."""
    raw = _os.environ.get(var)
    if raw:
        return Path(raw).expanduser().resolve()
    return default


# Data hierarchy. DATA_DIR stays as an alias to DATA_ROOT for backward compat
# with existing imports. Individual dirs can be overridden independently so
# (for example) only `data/raw/` can move to the SSD while processed stays
# repo-local during a migration.
DATA_ROOT = _path_from_env("METABOAGENT_DATA_ROOT", PROJECT_ROOT / "data")
DATA_DIR = DATA_ROOT  # backward-compat alias
RAW_DATA_DIR = _path_from_env("METABOAGENT_RAW_DATA_DIR", DATA_ROOT / "raw")
PROCESSED_DATA_DIR = _path_from_env("METABOAGENT_PROCESSED_DATA_DIR", DATA_ROOT / "processed")
CHROMADB_DIR = _path_from_env("METABOAGENT_CHROMADB_DIR", DATA_ROOT / "chromadb")
LOG_DIR = _path_from_env("METABOAGENT_LOG_DIR", PROJECT_ROOT / "logs")

# Optional: shared Hugging Face / transformers cache. If the user sets
# METABOAGENT_MODEL_CACHE_DIR but not HF_HOME, propagate it so
# sentence-transformers / transformers pick it up on import.
MODEL_CACHE_DIR = _os.environ.get("METABOAGENT_MODEL_CACHE_DIR")
if MODEL_CACHE_DIR:
    MODEL_CACHE_DIR = str(Path(MODEL_CACHE_DIR).expanduser().resolve())
    _os.environ.setdefault("HF_HOME", MODEL_CACHE_DIR)

# Create directories on import. Wrap in try/except so read-only environments
# (e.g. container probes) don't crash at import time — only directories that
# are actually used later will matter.
for d in [
    DATA_ROOT,
    RAW_DATA_DIR,
    PROCESSED_DATA_DIR,
    CHROMADB_DIR,
    LOG_DIR,
    RAW_DATA_DIR / "kegg" / "reactions",
    RAW_DATA_DIR / "kegg" / "compounds",
    RAW_DATA_DIR / "kegg" / "enzymes",
    RAW_DATA_DIR / "kegg" / "pathways",
    RAW_DATA_DIR / "pubmed",
]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as _e:
        # Don't crash at import (read-only envs, container probes), but log
        # so a downstream permission error isn't a total mystery.
        _log.warning("config: could not create %s (%s); "
                     "callers that touch this path will fail.", d, _e)

# === KEGG REST API ===
KEGG_BASE_URL = _os.environ.get("KEGG_BASE_URL", "https://rest.kegg.jp")
KEGG_BATCH_SIZE = 10          # max entries per batch GET
KEGG_RATE_LIMIT_DELAY = 0.15  # seconds between requests (conservative)
KEGG_ENDPOINTS = {
    "list_reactions":     f"{KEGG_BASE_URL}/list/reaction",
    "list_compounds":     f"{KEGG_BASE_URL}/list/compound",
    "list_enzymes":       f"{KEGG_BASE_URL}/list/enzyme",
    "list_pathways":      f"{KEGG_BASE_URL}/list/pathway",
    "get":                f"{KEGG_BASE_URL}/get",        # + /rn:R00001
    "find_compound":      f"{KEGG_BASE_URL}/find/compound",  # + /lycopene
    "link_enzyme_rxn":    f"{KEGG_BASE_URL}/link/enzyme/reaction",
    "link_pathway_rxn":   f"{KEGG_BASE_URL}/link/pathway/reaction",
    "link_compound_rxn":  f"{KEGG_BASE_URL}/link/compound/reaction",
}

# === PubMed E-utilities ===
PUBMED_BASE_URL = _os.environ.get(
    "PUBMED_BASE_URL", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
)
# Original broad terms (Day-1 corpus, 13k abstracts).
PUBMED_SEARCH_TERMS = [
    "metabolic engineering",
    "biosynthesis pathway design",
    "synthetic biology microbial",
    "enzyme engineering biocatalysis",
    "microbial cell factory",
    "heterologous expression pathway",
]
# Pathway-family expansion terms (Day-2). Used in addition to PUBMED_SEARCH_TERMS.
# Each is issued as `<term>[MeSH Terms] OR <term>[Title/Abstract]` by the fetcher.
PUBMED_EXPANSION_TERMS = [
    # Terpenoids
    "terpenoid biosynthesis",
    "isoprenoid biosynthesis",
    "MEP pathway",
    "mevalonate pathway",
    "sesquiterpene synthase",
    "diterpene synthase",
    "carotenoid biosynthesis",
    # Polyketides
    "polyketide biosynthesis",
    "polyketide synthase",
    "type I PKS",
    "type III PKS",
    # Alkaloids
    "alkaloid biosynthesis",
    "benzylisoquinoline alkaloid",
    "monoterpene indole alkaloid",
    # Shikimate / aromatic
    "shikimate pathway",
    "aromatic amino acid biosynthesis",
    "chorismate metabolism",
    # Fatty acids
    "fatty acid biosynthesis",
    "fatty acid synthase microbial",
    "omega fatty acid production",
    # Cross-cutting
    "cytochrome P450 biosynthesis heterologous",
    "cofactor regeneration NADPH engineering",
]
# All terms the fetcher will iterate through.
PUBMED_ALL_TERMS = PUBMED_SEARCH_TERMS + PUBMED_EXPANSION_TERMS
PUBMED_MAX_ABSTRACTS = int(_os.environ.get("PUBMED_MAX_ABSTRACTS", "100000"))
PUBMED_BATCH_SIZE = 200  # efetch batch size

# === Embedding Model (runs on cuda:0 since Phase 1) ===
# Day-1 placed PubMedBERT on CPU to keep all 4 L40s free for the 31B vLLM.
# Phase 1 moves it to cuda:0 because (a) TP=4 leaves ~2 GB free on each L40,
# (b) PubMedBERT-base (~110M params) needs ~500 MB in bf16 + activations,
# and (c) GPU embedding makes retrieval latency dominant-by-network, not
# dominant-by-compute. Override with EMBEDDING_DEVICE=cpu if vLLM is
# reconfigured to take all of cuda:0 (e.g. Phase 2 E4B on a single L40).
EMBEDDING_MODEL_NAME = _os.environ.get(
    "EMBEDDING_MODEL_NAME",
    "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
)
EMBEDDING_DEVICE = _os.environ.get("EMBEDDING_DEVICE", "cuda:0")
EMBEDDING_BATCH_SIZE = int(_os.environ.get("EMBEDDING_BATCH_SIZE", "64"))
EMBEDDING_DIMENSION = 768      # PubMedBERT output dim

# === ChromaDB Collections ===
COLLECTION_REACTIONS = "kegg_reactions"
COLLECTION_COMPOUNDS = "kegg_compounds"
COLLECTION_LITERATURE = "literature"

# === LLM endpoints (primary + optional utility) ===
#
# Day-1 used a single vLLM instance (`VLLM_*`). The target deployment in
# codex_target_deployment.md splits GPUs into two NUMA-local pairs, each
# hosting a model server:
#   - Primary reasoning model on GPUs 0,1, port 8000
#   - Utility/verifier model on GPUs 2,3, port 8001
#
# Phase 1 only introduces the config surface. A request router will be added
# in a later phase; for now callers should read PRIMARY_LLM_* and, if they
# need a utility model, check whether UTILITY_LLM_BASE_URL is set.

PRIMARY_LLM_BASE_URL = _os.environ.get(
    "PRIMARY_LLM_BASE_URL",
    _os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8001/v1"),
)
PRIMARY_LLM_MODEL_NAME = _os.environ.get(
    "PRIMARY_LLM_MODEL_NAME",
    _os.environ.get("VLLM_MODEL_NAME", "google/gemma-4-E4B-it"),
)
# API key validation is lazy: importing ``config`` must never raise for a
# missing secret (tests, path tools, and ingestion scripts all import this
# module without needing the LLM). Callers that actually construct an LLM
# client must go through ``get_primary_llm_api_key()`` below.
PRIMARY_LLM_API_KEY: str | None = (
    _os.environ.get("PRIMARY_LLM_API_KEY") or _os.environ.get("VLLM_API_KEY")
)

# Utility model: only honored when a base URL is explicitly configured.
# Model name falls back to the primary so a single deployed server can serve
# both roles during transition.
UTILITY_LLM_BASE_URL = _os.environ.get("UTILITY_LLM_BASE_URL") or None
UTILITY_LLM_MODEL_NAME = (
    _os.environ.get("UTILITY_LLM_MODEL_NAME") or (PRIMARY_LLM_MODEL_NAME if UTILITY_LLM_BASE_URL else None)
)
UTILITY_LLM_API_KEY: str | None = _os.environ.get("UTILITY_LLM_API_KEY") or PRIMARY_LLM_API_KEY

# === Gemma 4 tier endpoints (Phase 3 router) ===
#
# The v2 architecture runs three Gemma 4 tiers concurrently. The router in
# agent/router.py maps tier → endpoint:
#   "default"   → PRIMARY_LLM_* (E4B on :8001 in the v2 deployment — set via .env)
#   "deep"      → DEEP_LLM_*    (26B MoE on :8002)
#   "max_rigor" → MAX_RIGOR_LLM_* (31B dense on :8000, only when systemd
#                                  service is up; router does not health-check)
#
# All three tiers reuse the same API key (PRIMARY_LLM_API_KEY / VLLM_API_KEY)
# — one key, three endpoints. Do not introduce per-tier keys.
DEEP_LLM_BASE_URL = _os.environ.get(
    "DEEP_LLM_BASE_URL", "http://127.0.0.1:8002/v1"
)
DEEP_LLM_MODEL_NAME = _os.environ.get(
    "DEEP_LLM_MODEL_NAME", "google/gemma-4-26B-A4B-it"
)
MAX_RIGOR_LLM_BASE_URL = _os.environ.get(
    "MAX_RIGOR_LLM_BASE_URL", "http://127.0.0.1:8000/v1"
)
MAX_RIGOR_LLM_MODEL_NAME = _os.environ.get(
    "MAX_RIGOR_LLM_MODEL_NAME", "google/gemma-4-31B-it"
)

# Backward-compatibility aliases. Existing code (agent/metabo_agent.py,
# vectorstore/retriever.py) imports VLLM_*; keep these names working until
# the router phase migrates callers.
VLLM_BASE_URL = PRIMARY_LLM_BASE_URL
VLLM_MODEL_NAME = PRIMARY_LLM_MODEL_NAME
VLLM_API_KEY: str | None = PRIMARY_LLM_API_KEY

LLM_TEMPERATURE = float(_os.environ.get("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(_os.environ.get("LLM_MAX_TOKENS", "4096"))
LLM_TIMEOUT = int(_os.environ.get("LLM_TIMEOUT", "120"))

# === Retrieval Settings ===
RETRIEVAL_TOP_K = int(_os.environ.get("RETRIEVAL_TOP_K", "10"))
RERANK_TOP_K = int(_os.environ.get("RERANK_TOP_K", "5"))
SEMANTIC_WEIGHT = 0.6
METADATA_WEIGHT = 0.4

# === Agent Settings ===
AGENT_MAX_ITERATIONS = int(_os.environ.get("AGENT_MAX_ITERATIONS", "15"))
AGENT_VERBOSE = _os.environ.get("AGENT_VERBOSE", "1") not in ("0", "false", "False", "")

# === Host Organism Database (built-in knowledge) ===
CHASSIS_ORGANISMS = {
    "ecoli": {
        "name": "Escherichia coli K-12 MG1655",
        "native_pathways": ["MEP", "glycolysis", "TCA", "pentose_phosphate", "shikimate"],
        "genetic_tools": "excellent",
        "growth_rate": "fast",
        "kegg_org": "eco",
    },
    "scerevisiae": {
        "name": "Saccharomyces cerevisiae S288c",
        "native_pathways": ["MVA", "glycolysis", "TCA", "pentose_phosphate", "shikimate"],
        "genetic_tools": "excellent",
        "growth_rate": "moderate",
        "kegg_org": "sce",
    },
    "cglutamicum": {
        "name": "Corynebacterium glutamicum ATCC 13032",
        "native_pathways": ["MEP", "glycolysis", "TCA", "amino_acid_biosynthesis"],
        "genetic_tools": "good",
        "growth_rate": "moderate",
        "kegg_org": "cgl",
    },
    "bsubtilis": {
        "name": "Bacillus subtilis 168",
        "native_pathways": ["MEP", "glycolysis", "TCA"],
        "genetic_tools": "good",
        "growth_rate": "fast",
        "kegg_org": "bsu",
    },
    "pputida": {
        "name": "Pseudomonas putida KT2440",
        "native_pathways": ["MEP", "glycolysis", "TCA", "aromatic_degradation"],
        "genetic_tools": "good",
        "growth_rate": "fast",
        "kegg_org": "ppu",
    },
}

# === UI Settings ===
UI_HOST = _os.environ.get("UI_HOST", "0.0.0.0")
UI_PORT = int(_os.environ.get("UI_PORT", "7860"))
UI_TITLE = "MetaboAgent — AI Microbial Strain Designer"
UI_DESCRIPTION = (
    "Design microbial strains to synthesize any target molecule. "
    "Powered by Gemma 4 31B-IT with RAG over KEGG, BRENDA, and scientific literature."
)


def get_primary_llm_api_key() -> str:
    """Return the primary LLM API key; raise if not configured.

    Import-time validation would force every caller (tests, ingestion,
    path tooling) to set a secret they never use. Call this at the point
    an LLM client is constructed — fast fail, clear message, no global
    crash.
    """
    if not PRIMARY_LLM_API_KEY:
        raise RuntimeError(
            "PRIMARY_LLM_API_KEY (or VLLM_API_KEY) is not set. "
            "Export it in your shell or set it in .env before starting "
            "the LLM backend."
        )
    return PRIMARY_LLM_API_KEY


def get_log_path(name: str) -> Path:
    """Return an absolute path inside the configured LOG_DIR.

    Callers (UI, agent, ingestion scripts) that want to write a file-based
    log should use this instead of constructing ``Path("logs") / ...``. The
    directory is created on demand so the caller does not need to.

    Example:
        log_file = get_log_path("ui_showcase.log")
        # => $METABOAGENT_LOG_DIR/ui_showcase.log, defaulting to <repo>/logs/
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / name


def resolved_config_summary() -> dict:
    """Return a dict of resolved infra-critical config values.

    Used by `scripts/verify_config.py` and tests. Intentionally excludes
    secret material (API keys) — callers that need to display keys should
    reference them directly.
    """
    return {
        "PROJECT_ROOT": str(PROJECT_ROOT),
        "DATA_ROOT": str(DATA_ROOT),
        "RAW_DATA_DIR": str(RAW_DATA_DIR),
        "PROCESSED_DATA_DIR": str(PROCESSED_DATA_DIR),
        "CHROMADB_DIR": str(CHROMADB_DIR),
        "LOG_DIR": str(LOG_DIR),
        "MODEL_CACHE_DIR": MODEL_CACHE_DIR,
        "HF_HOME": _os.environ.get("HF_HOME"),
        "PRIMARY_LLM_BASE_URL": PRIMARY_LLM_BASE_URL,
        "PRIMARY_LLM_MODEL_NAME": PRIMARY_LLM_MODEL_NAME,
        "UTILITY_LLM_BASE_URL": UTILITY_LLM_BASE_URL,
        "UTILITY_LLM_MODEL_NAME": UTILITY_LLM_MODEL_NAME,
        "EMBEDDING_MODEL_NAME": EMBEDDING_MODEL_NAME,
        "EMBEDDING_DEVICE": EMBEDDING_DEVICE,
        "KEGG_BASE_URL": KEGG_BASE_URL,
        "PUBMED_BASE_URL": PUBMED_BASE_URL,
        "UI_HOST": UI_HOST,
        "UI_PORT": UI_PORT,
    }
