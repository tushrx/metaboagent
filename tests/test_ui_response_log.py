import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ui.app import _append_response_log, _append_session_log


class UiResponseLogTests(unittest.TestCase):
    def test_append_response_log_writes_jsonl_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "agent_responses.jsonl"
            steps = [
                {"kind": "thought", "text": "reasoning"},
                {"kind": "tool", "tool": "fetch_pubmed", "input": "vanillin", "output": "ok"},
            ]
            with patch("ui.app.get_log_path", return_value=log_path):
                _append_response_log(
                    user_msg="tell me about vanillin",
                    final_answer="Vanillin can be produced microbially.",
                    rendered_answer="<p>Vanillin can be produced microbially.</p>",
                    steps=steps,
                    duration_ms=1234,
                    status="ok",
                )

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["duration_ms"], 1234)
            self.assertEqual(record["user_msg"], "tell me about vanillin")
            self.assertEqual(record["final_answer"], "Vanillin can be produced microbially.")
            self.assertEqual(record["step_count"], 2)
            self.assertEqual(len(record["tool_calls"]), 1)
            self.assertEqual(record["tool_calls"][0]["tool"], "fetch_pubmed")
            self.assertIn("ts_utc", record)

    def test_append_session_log_writes_session_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "agent_sessions.jsonl"
            history = [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ]
            with patch("ui.app.get_log_path", return_value=log_path):
                _append_session_log(
                    session_id="abc123",
                    turn_index=2,
                    user_msg="next question",
                    final_answer="next answer",
                    chat_history=history,
                    status="ok",
                )

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["session_id"], "abc123")
            self.assertEqual(record["turn_index"], 2)
            self.assertEqual(record["message_count"], 2)
            self.assertEqual(record["chat_history"][0]["role"], "user")
            self.assertEqual(record["chat_history"][1]["content"], "world")


if __name__ == "__main__":
    unittest.main()
