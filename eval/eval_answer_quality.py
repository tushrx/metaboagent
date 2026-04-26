"""Phase 8.3.A — answer-quality rubric eval.

Six biochem questions (eval/scenarios/answer_quality/questions.json),
each with 4-6 scoreable rubric points. The agent produces a free-text
answer; a separate judge model (26B MoE on :8002) scores the answer
against the rubric and returns a per-point bool array.

Two-pass pipeline:
  1. For each question: drive run_agent at the question's specified
     tier and capture final_answer.
  2. For each question: call the judge model with (question, answer,
     rubric points) and parse a strict JSON object out of its reply.

Outputs land in eval/results/:
  answer_quality_<ts>.json            — per-question scores + aggregate
  answer_quality_<ts>_judge_raw.json  — raw judge replies for spot-check

Run:
    PYTHONPATH=/home/tusharmicro/metaboagent python3 eval/eval_answer_quality.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from openai import OpenAI

import config
from eval._runner import drain_agent_turn, timestamp_utc, write_result

REPO_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = REPO_ROOT / "eval/scenarios/answer_quality/questions.json"

JUDGE_MODEL = config.DEEP_LLM_MODEL_NAME
JUDGE_BASE_URL = config.DEEP_LLM_BASE_URL
JUDGE_API_KEY = config.PRIMARY_LLM_API_KEY or "EMPTY"

JUDGE_SYSTEM_PROMPT = (
    "You are evaluating an answer to a biochemistry question against a "
    "rubric. For each rubric point, decide if the answer covers the "
    "point. Answer ONLY with a single JSON object on one line, no "
    "prose, no markdown, no code fences. Schema:\n"
    '  {"scores": [bool, bool, ...], "notes": "optional brief explanation"}\n'
    "Be strict but fair — the answer must explicitly address the point, "
    "not merely imply it. Return exactly as many bool values in scores "
    "as there are rubric points, in the same order."
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval_answer_quality")


def _judge_user_message(question: str, answer: str, rubric: list[dict]) -> str:
    rubric_lines = "\n".join(
        f"  {i + 1}. {p['point']}" for i, p in enumerate(rubric)
    )
    return (
        f"QUESTION:\n{question}\n\n"
        f"AGENT'S ANSWER:\n{answer}\n\n"
        f"RUBRIC (score each point true/false in order):\n{rubric_lines}\n"
    )


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_judge_reply(raw: str, expected_n: int) -> dict[str, Any]:
    """Best-effort extraction of {scores: [bool], notes: str} from a judge reply.

    Tolerates code fences and surrounding prose. Returns
    {"scores": [...], "notes": "..."} on success or
    {"scores": None, "notes": "<parse error>", "raw": raw} on failure.
    """
    text = raw.strip()
    # Strip code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
    m = _JSON_OBJ_RE.search(text)
    if not m:
        return {"scores": None, "notes": f"no JSON object found in reply", "raw": raw}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"scores": None, "notes": f"json decode error: {e}", "raw": raw}
    scores = obj.get("scores")
    notes = obj.get("notes", "")
    if not isinstance(scores, list):
        return {"scores": None, "notes": "scores field missing or wrong type", "raw": raw}
    if len(scores) != expected_n:
        return {
            "scores": None,
            "notes": f"score length mismatch: got {len(scores)}, expected {expected_n}",
            "raw": raw,
        }
    coerced = []
    for s in scores:
        if isinstance(s, bool):
            coerced.append(s)
        elif isinstance(s, (int, float)):
            coerced.append(bool(s))
        else:
            return {"scores": None, "notes": "non-bool entry in scores", "raw": raw}
    return {"scores": coerced, "notes": str(notes)}


def _judge(client: OpenAI, question: str, answer: str, rubric: list[dict]) -> dict[str, Any]:
    expected_n = len(rubric)
    resp = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0.0,
        max_tokens=512,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user",
             "content": _judge_user_message(question, answer, rubric)},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    parsed = _parse_judge_reply(raw, expected_n)
    return {"raw": raw, **parsed}


async def _answer_one(question: str, tier: str, max_iterations: int) -> dict[str, Any]:
    events, final_answer, usage = await drain_agent_turn(
        [HumanMessage(content=question)],
        tier=tier,
        max_iterations=max_iterations,
    )
    return {
        "events": events,
        "final_answer": final_answer,
        "usage": usage,
    }


async def _run_all(questions: list[dict], max_iterations: int) -> tuple[list[dict], list[dict]]:
    """Pass 1: collect agent answers. Pass 2: score with the judge.

    Two passes (rather than interleaving) so that an unstable judge
    doesn't poison answers we already paid to generate, and so the
    raw judge log is one continuous block.
    """
    answers: list[dict] = []
    for i, q in enumerate(questions, 1):
        log.info("=== answer pass [%d/%d] %s (tier=%s) ===",
                 i, len(questions), q["id"], q["tier"])
        a = await _answer_one(q["question"], q["tier"], max_iterations)
        log.info(
            "  answered: iters=%d duration_ms=%d  final_len=%d",
            a["usage"]["iterations"], a["usage"]["duration_ms"],
            len(a["final_answer"]),
        )
        answers.append({"question": q, "answer": a["final_answer"], "usage": a["usage"]})

    judge_client = OpenAI(base_url=JUDGE_BASE_URL, api_key=JUDGE_API_KEY)
    judge_rows: list[dict] = []
    for i, ans in enumerate(answers, 1):
        q = ans["question"]
        log.info("=== judge pass [%d/%d] %s ===", i, len(answers), q["id"])
        verdict = _judge(judge_client, q["question"], ans["answer"], q["rubric"])
        if verdict["scores"] is None:
            log.warning("  judge parse failed: %s", verdict.get("notes"))
        else:
            log.info("  scores=%s", verdict["scores"])
        judge_rows.append({
            "id": q["id"],
            "question": q["question"],
            "agent_answer": ans["answer"],
            "rubric": q["rubric"],
            "judge_raw": verdict["raw"],
            "judge_scores": verdict["scores"],
            "judge_notes": verdict["notes"],
            "agent_usage": ans["usage"],
        })

    return answers, judge_rows


def _score(judge_rows: list[dict]) -> dict[str, Any]:
    per_question: list[dict] = []
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"score": 0, "max": 0})
    total_score = 0
    total_max = 0
    parse_failures = 0

    for row in judge_rows:
        rubric = row["rubric"]
        scores = row["judge_scores"]
        max_score = sum(p.get("weight", 1) for p in rubric)
        if scores is None:
            parse_failures += 1
            per_question.append({
                "id": row["id"],
                "score": 0,
                "max": max_score,
                "rubric_breakdown": [],
                "judge_notes": row["judge_notes"],
                "judge_parse_failed": True,
            })
            total_max += max_score
            continue
        weights = [p.get("weight", 1) for p in rubric]
        achieved = sum(w for s, w in zip(scores, weights) if s)
        total_score += achieved
        total_max += max_score
        # Question-type rollup: pull from the question on the row's
        # rubric? No — type lives on the question. Look it up by id.
        per_question.append({
            "id": row["id"],
            "score": achieved,
            "max": max_score,
            "rubric_breakdown": list(scores),
            "judge_notes": row["judge_notes"],
        })

    return {
        "per_question": per_question,
        "aggregate": {
            "total_score": total_score,
            "max_score": total_max,
            "pct": round(100.0 * total_score / total_max, 1) if total_max else 0.0,
            "parse_failures": parse_failures,
        },
        "by_question_type": {},  # filled in by main() with question-type lookup
    }


def _by_type(per_question: list[dict], questions: list[dict]) -> dict[str, dict]:
    qmap = {q["id"]: q["question_type"] for q in questions}
    out: dict[str, dict] = defaultdict(lambda: {"score": 0, "max": 0, "n": 0})
    for r in per_question:
        t = qmap.get(r["id"], "unknown")
        out[t]["score"] += r["score"]
        out[t]["max"] += r["max"]
        out[t]["n"] += 1
    for t, v in out.items():
        v["pct"] = round(100.0 * v["score"] / v["max"], 1) if v["max"] else 0.0
    return dict(out)


def _print_summary(scoring: dict[str, Any], questions: list[dict]) -> None:
    a = scoring["aggregate"]
    print()
    print("=" * 66)
    print("Answer-quality eval")
    print("=" * 66)
    print(f"Total: {a['total_score']} / {a['max_score']} ({a['pct']}%)")
    if a["parse_failures"]:
        print(f"  WARNING: {a['parse_failures']} judge replies failed to parse")
    print()
    print("Per question:")
    for r in scoring["per_question"]:
        breakdown = "[" + " ".join("Y" if b else "n" for b in r["rubric_breakdown"]) + "]"
        if r.get("judge_parse_failed"):
            breakdown = "[parse_failed]"
        print(f"  {r['id']:25s} {r['score']}/{r['max']}  {breakdown}")
    print()
    print("By question type:")
    for t, v in scoring["by_question_type"].items():
        print(f"  {t:18s} {v['score']}/{v['max']}  ({v['pct']}%)  n={v['n']}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids", type=str, default=None,
        help="comma-separated question IDs to run (default: all).",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=8,
        help="agent loop cap per question (default 8).",
    )
    args = parser.parse_args()

    if not QUESTIONS_PATH.is_file():
        log.error("questions.json missing at %s", QUESTIONS_PATH)
        return 1
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        questions = [q for q in questions if q["id"] in wanted]
        if not questions:
            log.error("no questions match --ids=%s", args.ids)
            return 1

    log.info("loaded %d questions, judge=%s @ %s", len(questions), JUDGE_MODEL, JUDGE_BASE_URL)
    answers, judge_rows = asyncio.run(_run_all(questions, args.max_iterations))
    scoring = _score(judge_rows)
    scoring["by_question_type"] = _by_type(scoring["per_question"], questions)

    ts = timestamp_utc()
    main_payload = {
        "timestamp_utc": ts,
        "judge_model": JUDGE_MODEL,
        "n_questions": len(questions),
        **scoring,
    }
    main_path = write_result("answer_quality", main_payload, ts=ts)

    raw_path = write_result(
        "answer_quality_judge_raw",
        {
            "timestamp_utc": ts,
            "judge_model": JUDGE_MODEL,
            "rows": judge_rows,
        },
        ts=ts,
    )

    log.info("wrote %s", main_path)
    log.info("wrote %s", raw_path)
    _print_summary(scoring, questions)
    return 0 if scoring["aggregate"]["parse_failures"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
