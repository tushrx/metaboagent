"""
@tool parse_structure_image — chemical-structure image → SMILES.

Flow
  base64 image → E4B (PRIMARY_LLM_*) vision call → JSON-only response
              → RDKit canonicalize + InChIKey + formula → structured dict
  The vision call is a direct ChatOpenAI.invoke (not select_llm / not
  stream) so the model returns one full JSON blob we can parse. RDKit
  is the arbiter of canonical form and validity — the model proposes,
  RDKit disposes.

Routing note
  This tool is E4B-only by design. Both E4B and 26B are vision-capable
  (preflight CHECK 3), but keeping the vision path on PRIMARY_LLM_*
  (:8001) means a 26B-tier chat can still call this tool without
  spilling image context into a slow MoE. 26B stays a text reasoner.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from rdkit import Chem, RDLogger
from rdkit.Chem import rdMolDescriptors

from config import (
    PRIMARY_LLM_API_KEY,
    PRIMARY_LLM_BASE_URL,
    PRIMARY_LLM_MODEL_NAME,
)

log = logging.getLogger(__name__)

# RDKit chatters about valence/aromaticity on hallucinated SMILES;
# we inspect mol is None ourselves, the log spam is noise.
RDLogger.DisableLog("rdApp.*")

_MIME = Literal["image/png", "image/jpeg", "image/webp"]
_CONFIDENCE = Literal["high", "medium", "low"]

_EXTRACTION_PROMPT = (
    "You are looking at a 2D chemical structure drawing. Extract the SMILES "
    "string for the molecule shown. Respond ONLY with a JSON object containing "
    "these exact keys:\n"
    "- smiles: the SMILES string (string)\n"
    "- confidence: one of 'high', 'medium', 'low' (string)\n"
    "- alternative_smiles: alternative interpretations if ambiguous, else empty array\n"
    "- notes: brief caveats about stereochemistry, tautomers, or visual ambiguity "
    "(string, can be empty)\n"
    "Do not include any text outside the JSON. If you cannot extract a valid "
    "SMILES, return smiles: null."
)

_VISION_TIMEOUT_S = 90
_VISION_TEMPERATURE = 0.1  # low but non-zero; leaves room for alt-smiles hedging
_NOTES_TRUNCATE = 200


def _force_ipv4(url: str) -> str:
    return url.replace("localhost", "127.0.0.1")


def _build_vision_llm() -> ChatOpenAI:
    """Direct ChatOpenAI on PRIMARY_LLM (E4B). No bind_tools — this is
    a leaf call, the model isn't allowed to chain further tools here."""
    return ChatOpenAI(
        model=PRIMARY_LLM_MODEL_NAME,
        base_url=_force_ipv4(PRIMARY_LLM_BASE_URL),
        api_key=PRIMARY_LLM_API_KEY or "none",
        temperature=_VISION_TEMPERATURE,
        timeout=_VISION_TIMEOUT_S,
    )


def _empty_result(smiles: Optional[str], notes: str, confidence: _CONFIDENCE = "low") -> dict:
    return {
        "smiles": smiles,
        "confidence": confidence,
        "alternative_smiles": [],
        "notes": notes,
        "rdkit_canonical": None,
        "inchi_key": None,
        "formula": None,
    }


def _rdkit_enrich(smiles: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(rdkit_canonical, inchi_key, formula) — all None if SMILES doesn't parse."""
    if not smiles:
        return None, None, None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None, None, None
    canonical = Chem.MolToSmiles(mol)
    inchi_key = Chem.MolToInchiKey(mol) or None
    formula = rdMolDescriptors.CalcMolFormula(mol) or None
    return canonical, inchi_key, formula


def _parse_model_json(raw: str) -> dict:
    """Extract the expected fields from the model's response.

    Gemma 4 sometimes wraps the JSON in a ```json``` fence or leading
    prose despite the 'ONLY JSON' instruction. Strip fences and try to
    locate the first balanced {...} block before giving up.
    """
    text = raw.strip()
    # Strip ```json fences.
    if text.startswith("```"):
        lines = text.splitlines()
        # drop opening ``` line and closing ``` line if present
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Grab the first {...} block if there's leading prose.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _coerce_confidence(raw: Any) -> _CONFIDENCE:
    if isinstance(raw, str) and raw.lower() in ("high", "medium", "low"):
        return raw.lower()  # type: ignore[return-value]
    return "low"


@tool(parse_docstring=True)
def parse_structure_image(
    image_data_base64: str,
    mime_type: _MIME = "image/png",
) -> dict:
    """Extract canonical SMILES from a chemical structure image.

    Call this when the user attaches an image of a molecular structure
    drawing and wants to identify the compound or get its SMILES.
    Returns the model's raw SMILES plus an RDKit-validated canonical
    form, InChIKey, molecular formula, and a confidence tag. RDKit —
    not the model — is the source of truth for canonicalization and
    validity; if the model's SMILES doesn't parse, rdkit_canonical /
    inchi_key / formula are all None and the caller should treat the
    extraction as failed.

    Args:
        image_data_base64: Base64-encoded image bytes, NO ``data:`` prefix.
            When the runtime hint tells you an image was attached to the
            user message, pass the string ``"ATTACHED"`` here and the
            runtime will splice in the real bytes at call time.
        mime_type: MIME type of the image; one of image/png,
            image/jpeg, image/webp.

    Returns:
        Dict with keys: smiles, confidence, alternative_smiles, notes,
        rdkit_canonical, inchi_key, formula.
    """
    if not image_data_base64:
        return _empty_result(None, "empty image payload")
    try:
        base64.b64decode(image_data_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        return _empty_result(None, f"image could not be decoded: {e}")

    llm = _build_vision_llm()
    data_url = f"data:{mime_type};base64,{image_data_base64}"
    message = HumanMessage(
        content=[
            {"type": "text", "text": _EXTRACTION_PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )

    # Network errors (connection refused, 5xx, timeout) are allowed to
    # bubble up — the agent loop's tool_error handler catches them so
    # the user sees a specific failure rather than a silent empty dict.
    response = llm.invoke([message])
    raw = response.content if isinstance(response.content, str) else str(response.content)

    try:
        data = _parse_model_json(raw)
    except json.JSONDecodeError:
        trimmed = raw.strip().replace("\n", " ")
        return _empty_result(
            None,
            f"model did not return JSON: {trimmed[:_NOTES_TRUNCATE]}",
        )

    smiles = data.get("smiles")
    if not isinstance(smiles, str) or not smiles.strip():
        smiles = None
    else:
        smiles = smiles.strip()

    alt_raw = data.get("alternative_smiles") or []
    if isinstance(alt_raw, list):
        alt = [s.strip() for s in alt_raw if isinstance(s, str) and s.strip()]
    else:
        alt = []

    notes = data.get("notes") if isinstance(data.get("notes"), str) else ""
    confidence = _coerce_confidence(data.get("confidence"))

    canonical, inchi_key, formula = _rdkit_enrich(smiles)

    return {
        "smiles": smiles,
        "confidence": confidence,
        "alternative_smiles": alt,
        "notes": notes,
        "rdkit_canonical": canonical,
        "inchi_key": inchi_key,
        "formula": formula,
    }
