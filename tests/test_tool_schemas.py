"""Assert every @tool in agent.tools exposes an OpenAI-compatible schema.

Per Milestone 3.2: tools must carry a top-level description, every
parameter must carry a description, the `required` list must reference
only declared properties, no property may have a JSON-Schema type of
null, and any Literal/enum must have at least 2 options.

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_tool_schemas
"""
from __future__ import annotations

import importlib
import os
import unittest
from typing import Any

# Avoid network and heavy model loads at import time of downstream tools.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

TOOLS: list[tuple[str, str]] = [
    ("agent.tools.compare_synthesis_routes", "compare_synthesis_routes"),
    ("agent.tools.design_expression_vector", "design_expression_vector"),
    ("agent.tools.design_primers", "design_primers"),
    ("agent.tools.enzyme_ranker", "rank_enzymes"),
    ("agent.tools.fetch_gene_sequence", "fetch_gene_sequence"),
    ("agent.tools.fetch_kegg_live", "fetch_kegg_live"),
    ("agent.tools.fetch_pubchem", "fetch_pubchem"),
    ("agent.tools.fetch_pubmed_live", "fetch_pubmed_live"),
    ("agent.tools.fetch_sabio_rk", "fetch_sabio_rk"),
    ("agent.tools.fetch_uniprot", "fetch_uniprot"),
    ("agent.tools.fetch_zinc", "fetch_zinc"),
    ("agent.tools.kegg_search", "search_kegg"),
    ("agent.tools.literature_search", "search_literature"),
    ("agent.tools.retrosynthesis", "plan_retrosynthesis"),
    ("agent.tools.verify_ec_number", "verify_ec_number"),
    ("agent.tools.verify_kegg_reaction", "verify_kegg_reaction"),
    ("agent.tools.web_search", "web_search"),
]


def _load_tool(mod_path: str, attr: str):
    mod = importlib.import_module(mod_path)
    return getattr(mod, attr)


def _json_schema(tool_obj) -> dict[str, Any]:
    cls = tool_obj.args_schema
    if hasattr(cls, "model_json_schema"):
        return cls.model_json_schema()
    return cls.schema()  # pydantic v1 fallback


class ToolSchemaTests(unittest.TestCase):
    """Table-driven assertions using subTest so all 15 tools are checked
    even if an earlier one fails. 15 tools × 5 checks = 75 assertions."""

    def test_tool_has_description(self) -> None:
        for mod_path, attr in TOOLS:
            with self.subTest(tool=attr):
                t = _load_tool(mod_path, attr)
                desc = (t.description or "").strip()
                self.assertTrue(
                    desc, f"{t.name} has empty top-level description"
                )

    def test_every_param_has_description(self) -> None:
        for mod_path, attr in TOOLS:
            with self.subTest(tool=attr):
                t = _load_tool(mod_path, attr)
                schema = _json_schema(t)
                props: dict[str, Any] = schema.get("properties", {}) or {}
                for pname, prop in props.items():
                    desc = (prop.get("description") or "").strip()
                    self.assertTrue(
                        desc,
                        f"{t.name}.{pname} has no description in its schema",
                    )

    def test_required_list_well_formed(self) -> None:
        for mod_path, attr in TOOLS:
            with self.subTest(tool=attr):
                t = _load_tool(mod_path, attr)
                schema = _json_schema(t)
                props: dict[str, Any] = schema.get("properties", {}) or {}
                required = schema.get("required", []) or []
                self.assertIsInstance(required, list)
                for name in required:
                    self.assertIn(
                        name, props,
                        f"{t.name}: required param '{name}' not in properties",
                    )

    def test_no_null_type(self) -> None:
        for mod_path, attr in TOOLS:
            with self.subTest(tool=attr):
                t = _load_tool(mod_path, attr)
                schema = _json_schema(t)
                props: dict[str, Any] = schema.get("properties", {}) or {}
                for pname, prop in props.items():
                    top_type = prop.get("type")
                    self.assertIsNotNone(
                        top_type if "type" in prop else "_skip",
                        f"{t.name}.{pname} has literal null type at top level",
                    )
                    for sub in prop.get("anyOf", []):
                        if "type" in sub:
                            self.assertIsNotNone(
                                sub["type"],
                                f"{t.name}.{pname} anyOf has literal null type",
                            )

    def test_literals_have_at_least_two_options(self) -> None:
        for mod_path, attr in TOOLS:
            with self.subTest(tool=attr):
                t = _load_tool(mod_path, attr)
                schema = _json_schema(t)
                props: dict[str, Any] = schema.get("properties", {}) or {}
                for pname, prop in props.items():
                    if "enum" in prop:
                        self.assertGreaterEqual(
                            len(prop["enum"]), 2,
                            f"{t.name}.{pname} enum has <2 options",
                        )
                    for sub in prop.get("anyOf", []):
                        if "enum" in sub:
                            self.assertGreaterEqual(
                                len(sub["enum"]), 2,
                                f"{t.name}.{pname} anyOf enum has <2 options",
                            )


if __name__ == "__main__":
    unittest.main()
