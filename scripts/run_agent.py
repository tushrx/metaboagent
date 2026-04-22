"""CLI entry point for the agent."""
from __future__ import annotations

import argparse
import json
import logging

from agent.metabo_agent import build_agent, run


def main():
    parser = argparse.ArgumentParser(description="Run MetaboAgent on a query.")
    parser.add_argument("query", help="Free-text design brief or question.")
    parser.add_argument("--json", action="store_true", help="Output the full JSON trace.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = build_agent()
    result = run(agent, args.query)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("\n=== ANSWER ===\n")
        print(result["answer"])
        print("\n=== TOOL TRACE ===")
        for s in result["steps"]:
            print(f" - {s['tool']}  {str(s['input'])[:120]}")


if __name__ == "__main__":
    main()
