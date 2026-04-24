"""Tests for app.server — hermetic.

We patch ``app.server.run_agent`` (scripted event generator) and
``app.server._probe`` (scripted per-URL status) rather than booting a
vLLM or hitting the network. The 7 test cases mirror the Phase-4 spec:

    a. POST /chat valid → SSE stream
    b. POST /chat invalid tier → 422
    c. POST /chat empty messages → 422
    d. GET  /health all up → 200, overall=ok
    e. GET  /health one down → 200, overall=degraded
    f. GET  /health all down → 503, overall=down
    g. GET  /tools → 15 descriptors, each has name/desc/schema

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 -m unittest tests.test_server
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from fastapi.testclient import TestClient

from app.server import create_app


def _scripted_run_agent(events: list[dict]):
    """Return an async-generator callable that replaces run_agent."""
    async def fake(*_args, **_kwargs):
        for ev in events:
            yield ev
    return fake


def _scripted_probe(status_by_port: dict[str, str]):
    """Replace _probe with a lookup keyed on the port substring of the URL."""
    async def fake(base_url: str) -> str:
        for port, status in status_by_port.items():
            if f":{port}" in base_url:
                return status
        return "down"
    return fake


def _parse_sse_events(raw_lines) -> list[dict]:
    """Extract JSON payloads from `data: ...` SSE lines."""
    out: list[dict] = []
    for line in raw_lines:
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


# ---- a/b/c: /chat endpoint ------------------------------------------------

class ChatEndpointTests(unittest.TestCase):
    def test_valid_body_streams_events(self):
        events = [
            {"type": "token", "content": "Hello "},
            {"type": "token", "content": "world"},
            {"type": "final_answer", "content": "Hello world"},
            {"type": "done", "usage": {"tokens_in": 10, "tokens_out": 5,
                                       "iterations": 1, "tool_calls": 0,
                                       "ms": 42}},
        ]
        with patch("app.server.run_agent", _scripted_run_agent(events)):
            with TestClient(create_app()) as client:
                with client.stream("POST", "/chat", json={
                    "messages": [{"role": "user", "content": "hi"}],
                }) as r:
                    self.assertEqual(r.status_code, 200)
                    self.assertIn("text/event-stream", r.headers["content-type"])
                    received = _parse_sse_events(r.iter_lines())
        self.assertEqual(received, events)

    def test_invalid_tier_422(self):
        with TestClient(create_app()) as client:
            r = client.post("/chat", json={
                "messages": [{"role": "user", "content": "hi"}],
                "tier": "turbo",
            })
        self.assertEqual(r.status_code, 422)
        # Body should mention the offending field
        body = r.json()
        self.assertTrue(
            any("tier" in (err.get("loc") or []) for err in body.get("detail", [])),
            f"422 body should point at tier: {body}",
        )

    def test_empty_messages_422(self):
        with TestClient(create_app()) as client:
            r = client.post("/chat", json={"messages": []})
        self.assertEqual(r.status_code, 422)


# ---- d/e/f: /health endpoint ---------------------------------------------

class HealthEndpointTests(unittest.TestCase):
    def test_all_up_overall_ok(self):
        with patch("app.server._probe", _scripted_probe({
            "8001": "ok", "8002": "ok", "8000": "ok",
        })):
            with TestClient(create_app()) as client:
                r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["overall"], "ok")
        self.assertEqual(body["default"], "ok")
        self.assertEqual(body["deep"], "ok")
        self.assertEqual(body["max_rigor"], "ok")

    def test_one_down_overall_degraded(self):
        with patch("app.server._probe", _scripted_probe({
            "8001": "ok", "8002": "down", "8000": "ok",
        })):
            with TestClient(create_app()) as client:
                r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["overall"], "degraded")
        self.assertEqual(body["deep"], "down")
        self.assertEqual(body["default"], "ok")

    def test_all_down_503(self):
        with patch("app.server._probe", _scripted_probe({
            "8001": "down", "8002": "down", "8000": "down",
        })):
            with TestClient(create_app()) as client:
                r = client.get("/health")
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertEqual(body["overall"], "down")


# ---- g: /tools endpoint ---------------------------------------------------

class ToolsEndpointTests(unittest.TestCase):
    def test_returns_15_well_formed_descriptors(self):
        with TestClient(create_app()) as client:
            r = client.get("/tools")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 15, f"expected 15 tools, got {len(body)}")

        seen_names: set[str] = set()
        for entry in body:
            self.assertIn("name", entry)
            self.assertIn("description", entry)
            self.assertIn("parameters_schema", entry)
            self.assertTrue(entry["name"], f"empty name: {entry}")
            self.assertNotIn(entry["name"], seen_names,
                             f"duplicate name: {entry['name']}")
            seen_names.add(entry["name"])
            self.assertTrue(entry["description"],
                            f"empty description for {entry['name']}")
            schema = entry["parameters_schema"]
            self.assertEqual(schema.get("type"), "object",
                             f"{entry['name']} schema not object: {schema}")


if __name__ == "__main__":
    unittest.main()
